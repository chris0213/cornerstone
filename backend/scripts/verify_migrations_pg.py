"""在本地 / CI 的一次性 PostgreSQL 库上验证 Alembic 迁移可用性。

会依次执行：
    alembic upgrade head
    alembic downgrade -1
    alembic upgrade head

用法（务必指向一次性空库，脚本会修改该库）：
    DATABASE_URL_SYNC="postgresql://user:pass@localhost:5432/cornerstone_migrate_test" \
    DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/cornerstone_migrate_test" \
    SECRET_KEY="local-verify-secret-key-0123456789abcdef" \
    .venv/bin/python scripts/verify_migrations_pg.py

也可直接传 --url，脚本会自动补出 async 连接串：
    .venv/bin/python scripts/verify_migrations_pg.py --url postgresql://user:pass@localhost/testdb
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

STEPS = [
    ("upgrade head", ["upgrade", "head"]),
    ("downgrade -1", ["downgrade", "-1"]),
    ("upgrade head (again)", ["upgrade", "head"]),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="测试库的同步连接串（postgresql://...）")
    args = parser.parse_args()

    env = dict(os.environ)
    if args.url:
        env["DATABASE_URL_SYNC"] = args.url
        env["DATABASE_URL"] = args.url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if "DATABASE_URL_SYNC" not in env:
        print("缺少 DATABASE_URL_SYNC（或用 --url 指定）", file=sys.stderr)
        return 2
    if not env["DATABASE_URL_SYNC"].startswith("postgresql"):
        print("该脚本只用于 PostgreSQL 验证", file=sys.stderr)
        return 2
    env.setdefault("SECRET_KEY", "local-verify-secret-key-0123456789abcdef")

    for label, cmd in STEPS:
        print(f"\n===== alembic {' '.join(cmd)} ({label}) =====", flush=True)
        code = subprocess.run([sys.executable, "-m", "alembic", *cmd], cwd=BACKEND, env=env).returncode
        if code != 0:
            print(f"FAILED: {label}, exit={code}", file=sys.stderr)
            return code

    print("\nPASS: upgrade head → downgrade -1 → upgrade head 全部成功")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
