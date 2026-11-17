"""手动重置用户密码的运维脚本（不随应用启动，需显式执行）。

安全约束（修复 #13 硬编码弱口令）：
- 不再内置任何明文口令；新密码必须来自命令行参数、环境变量或交互式输入。
- 强制最小强度校验，避免把账号重置成弱口令。

用法：
    python reset_password.py <username>
    RESET_PASSWORD='强口令' python reset_password.py <username>   # 非交互
环境变量 RESET_PASSWORD 缺省时回退到交互式 getpass 输入（不落 shell 历史）。
"""
import asyncio
import getpass
import os
import sys

from sqlalchemy import select

from src.database import async_engine
from src.models import User
from src.utils.security import get_password_hash

MIN_LENGTH = 12


def _validate_strength(password: str) -> None:
    """最小强度校验：长度 + 至少含大写、小写、数字各一。不达标直接拒绝。"""
    if len(password) < MIN_LENGTH:
        raise ValueError(f"密码长度至少 {MIN_LENGTH} 位，当前 {len(password)} 位")
    if not any(c.isupper() for c in password):
        raise ValueError("密码必须包含至少一个大写字母")
    if not any(c.islower() for c in password):
        raise ValueError("密码必须包含至少一个小写字母")
    if not any(c.isdigit() for c in password):
        raise ValueError("密码必须包含至少一个数字")


async def reset_password(username: str, new_password: str) -> None:
    async with async_engine.begin() as conn:
        exists = (await conn.execute(
            select(User.id).where(User.username == username)
        )).first()
        if not exists:
            raise SystemExit(f"用户不存在: {username}")
        await conn.execute(
            User.__table__.update()
            .where(User.username == username)
            .values(hashed_password=get_password_hash(new_password))
        )
    print(f"用户 {username} 密码已重置。")


def _resolve_inputs() -> tuple[str, str]:
    username = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("RESET_USERNAME")
    if not username:
        raise SystemExit("用法: python reset_password.py <username>（或设置 RESET_USERNAME）")

    password = os.environ.get("RESET_PASSWORD")
    if not password:
        password = getpass.getpass(f"为 {username} 设置新密码: ")
    if not password:
        raise SystemExit("新密码不能为空")

    _validate_strength(password)
    return username, password


if __name__ == "__main__":
    username, new_password = _resolve_inputs()
    asyncio.run(reset_password(username, new_password))
