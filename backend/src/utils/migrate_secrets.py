"""存量 SSO/LDAP secret 明文加密迁移脚本（M1）。

用法（在 backend/ 目录下执行）:
    .venv/bin/python -m src.utils.migrate_secrets            # 正向：明文 -> enc:密文
    .venv/bin/python -m src.utils.migrate_secrets --dry-run  # 只预览，不写库
    .venv/bin/python -m src.utils.migrate_secrets --rollback # 回滚: enc:密文 -> 明文

特性:
- 幂等: 已带 enc: 前缀的值跳过，重复执行无副作用
- 可回滚: --rollback 按同规则去掉 enc: 前缀还原明文
- 仅处理 system_configs 表的 sso_config / ldap_config 两个 key
"""
import argparse
import asyncio
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import async_session
from src.models import SystemConfig
from src.utils.crypto import encrypt_password, decrypt_password

SECRET_ENC_PREFIX = "enc:"

# key -> JSON 中存 secret 的字段名
TARGET_FIELDS = {
    "sso_config": ["client_secret"],
    "ldap_config": ["bind_password"],
}


async def _migrate_with_session(db: AsyncSession, dry_run: bool):
    migrated = 0
    skipped = 0
    for config_key, fields in TARGET_FIELDS.items():
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == config_key)
        )
        record = result.scalar_one_or_none()
        if not record or not record.value:
            print(f"[跳过] {config_key}: 无配置记录")
            continue

        data = json.loads(record.value)
        changed = False
        for field in fields:
            value = data.get(field)
            if not value:
                print(f"[跳过] {config_key}.{field}: 为空")
                continue
            if value.startswith(SECRET_ENC_PREFIX):
                print(f"[跳过] {config_key}.{field}: 已加密")
                skipped += 1
                continue
            data[field] = SECRET_ENC_PREFIX + encrypt_password(value)
            changed = True
            migrated += 1
            print(f"[迁移] {config_key}.{field}: 明文 -> 已加密")

        if changed and not dry_run:
            record.value = json.dumps(data, ensure_ascii=False, indent=2)
            await db.commit()
    return migrated, skipped


async def _rollback_with_session(db: AsyncSession):
    restored = 0
    skipped = 0
    for config_key, fields in TARGET_FIELDS.items():
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == config_key)
        )
        record = result.scalar_one_or_none()
        if not record or not record.value:
            print(f"[跳过] {config_key}: 无配置记录")
            continue

        data = json.loads(record.value)
        changed = False
        for field in fields:
            value = data.get(field)
            if not value or not value.startswith(SECRET_ENC_PREFIX):
                print(f"[跳过] {config_key}.{field}: 非加密值")
                skipped += 1
                continue
            # 解密验证可还原，再写回明文
            plain = decrypt_password(value[len(SECRET_ENC_PREFIX):])
            data[field] = plain
            changed = True
            restored += 1
            print(f"[还原] {config_key}.{field}: 已加密 -> 明文")

        if changed:
            record.value = json.dumps(data, ensure_ascii=False, indent=2)
            await db.commit()
    return restored, skipped


async def migrate(db: AsyncSession | None = None, dry_run: bool = False) -> int:
    """正向迁移: 明文 -> enc:密文。返回迁移的字段数。"""
    if db is not None:
        migrated, _ = await _migrate_with_session(db, dry_run)
        return migrated
    async with async_session() as session:
        migrated, _ = await _migrate_with_session(session, dry_run)
        return migrated


async def rollback(db: AsyncSession | None = None) -> int:
    """回滚: enc:密文 -> 明文。返回还原的字段数。"""
    if db is not None:
        restored, _ = await _rollback_with_session(db)
        return restored
    async with async_session() as session:
        restored, _ = await _rollback_with_session(session)
        return restored


def main() -> None:
    parser = argparse.ArgumentParser(description="SSO/LDAP secret 存量明文加密迁移")
    parser.add_argument("--dry-run", action="store_true", help="只预览不写库")
    parser.add_argument("--rollback", action="store_true", help="回滚为明文")
    args = parser.parse_args()

    async def run():
        if args.rollback:
            async with async_session() as session:
                restored, skipped = await _rollback_with_session(session)
            print(f"\n完成: 还原 {restored} 个字段，跳过 {skipped} 个")
        else:
            async with async_session() as session:
                migrated, skipped = await _migrate_with_session(session, args.dry_run)
            if args.dry_run:
                print(f"\n[dry-run] 预计迁移 {migrated} 个字段，实际未写库")
            else:
                print(f"\n完成: 迁移 {migrated} 个字段，跳过已加密 {skipped} 个")

    asyncio.run(run())


if __name__ == "__main__":
    main()
