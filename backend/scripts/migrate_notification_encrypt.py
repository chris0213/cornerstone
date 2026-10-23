"""存量通知配置密钥明文迁移脚本（幂等、可回滚）

功能：
  读取 settings 表 notification_settings 行，把 4 个密钥字段
  （dingtalk/wechat/feishu webhook URL + smtp_password）中未加密的明文
  加密为 enc: 前缀密文回写。已加密的字段跳过（幂等，可重复执行）。

用法：
  python scripts/migrate_notification_encrypt.py            # 迁移（加密）
  python scripts/migrate_notification_encrypt.py --rollback # 回滚（从备份还原明文）

安全性：
  - 迁移前将原始 JSON 备份到 settings 表 key=notification_settings_backup_migrate
  - 回滚 = 用备份覆盖 notification_settings（备份行保留，人工确认后再删）
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from src.database import async_session
from src.models.setting import Setting
from src.utils.notification_store import (
    NOTIFICATION_SETTINGS_KEY, SECRET_FIELDS, SECRET_ENC_PREFIX, encrypt_config,
)

BACKUP_KEY = "notification_settings_backup_migrate"


async def migrate():
    async with async_session() as session:
        result = await session.execute(
            select(Setting).filter(Setting.key == NOTIFICATION_SETTINGS_KEY)
        )
        setting = result.scalars().first()
        if not setting:
            print("✓ 无 notification_settings 配置，无需迁移")
            return

        try:
            config = json.loads(setting.value)
        except json.JSONDecodeError:
            print("✗ 配置值不是合法 JSON，中止（请人工检查）")
            sys.exit(1)

        if not isinstance(config, dict):
            print("✗ 配置值不是 dict，中止")
            sys.exit(1)

        plain_fields = [f for f in SECRET_FIELDS
                        if config.get(f) and not str(config[f]).startswith(SECRET_ENC_PREFIX)]
        already = [f for f in SECRET_FIELDS
                   if config.get(f) and str(config[f]).startswith(SECRET_ENC_PREFIX)]

        if not plain_fields:
            print(f"✓ 所有密钥字段已加密（已加密: {already or '无'}），无需迁移")
            return

        # 备份原文（幂等：已有备份则不覆盖最早的明文备份）
        backup_result = await session.execute(select(Setting).filter(Setting.key == BACKUP_KEY))
        backup_setting = backup_result.scalars().first()
        if not backup_setting:
            session.add(Setting(key=BACKUP_KEY, value=setting.value))
            print(f"✓ 已备份原文到 settings.key={BACKUP_KEY}")
        else:
            print(f"✓ 备份已存在（settings.key={BACKUP_KEY}），保留原备份")

        # 加密回写
        encrypted = encrypt_config(config)
        setting.value = json.dumps(encrypted, ensure_ascii=False)
        await session.commit()

        print(f"✓ 迁移完成：本次加密 {plain_fields}，之前已加密 {already or '无'}")
        print("  验证：GET /api/v1/settings/notification 应只回 has_xxx；发送链路应正常解密")


async def rollback():
    async with async_session() as session:
        backup_result = await session.execute(select(Setting).filter(Setting.key == BACKUP_KEY))
        backup_setting = backup_result.scalars().first()
        if not backup_setting:
            print("✗ 无备份（settings.key=%s），无法回滚" % BACKUP_KEY)
            sys.exit(1)

        result = await session.execute(
            select(Setting).filter(Setting.key == NOTIFICATION_SETTINGS_KEY)
        )
        setting = result.scalars().first()
        if not setting:
            print("✗ 当前无 notification_settings 行，异常状态，中止")
            sys.exit(1)

        setting.value = backup_setting.value
        await session.commit()
        print("✓ 已回滚：notification_settings 恢复为迁移前明文原文")
        print(f"  备份行 settings.key={BACKUP_KEY} 已保留，确认无需后再删除")


if __name__ == "__main__":
    if "--rollback" in sys.argv:
        asyncio.run(rollback())
    else:
        asyncio.run(migrate())
