"""仪表盘公共依赖"""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from src.models.user import User

BJT = timezone(timedelta(hours=8))  # 北京时间


def to_naive_bjt(dt: datetime) -> datetime:
    """DB 时间转北京挂钟 naive（PG timestamptz 返回 aware UTC，SQLite 返回 naive）

    用于 naive 时间运算（如 now - db_value）以及显示日期，避免 aware/naive 混算抛 TypeError。
    """
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(BJT).replace(tzinfo=None)


def require_manager_or_admin(current_user: User) -> None:
    """验证用户角色为 viewer 或 super_admin"""
    if current_user.role.name not in ['viewer', 'super_admin']:
        raise HTTPException(status_code=403, detail="此接口需要IT负责人或管理员权限")
