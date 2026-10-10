"""仪表盘公共依赖"""
from fastapi import HTTPException
from src.models.user import User


def require_manager_or_admin(current_user: User) -> None:
    """验证用户角色为 viewer 或 super_admin"""
    if current_user.role.name not in ['viewer', 'super_admin']:
        raise HTTPException(status_code=403, detail="此接口需要IT负责人或管理员权限")
