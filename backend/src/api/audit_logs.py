from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert

from ..database import get_db
from ..models import AuditLog, Role
from ..schemas import AuditLogResponse
from .dependencies import get_current_active_user, get_current_superuser, PageParams, pagination

router = APIRouter()

from datetime import datetime, timezone

@router.get("/")
async def read_logs(
    page: PageParams = Depends(pagination()),
    user: str = None,
    action: str = None,
    category: str = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_active_user)
):
    query = select(AuditLog)

    # 获取用户角色名
    role_name = current_user.role.name if current_user.role else None

    # viewer 角色强制只返回登录和高危操作
    LOGIN_ACTIONS = ['用户登录', '用户登出', '登录失败']
    DANGEROUS_ACTIONS = [
        '删除设备', '删除专线', '回滚', '配置回滚',
        '创建用户', '修改角色', '删除用户', '启用用户', '停用用户'
    ]

    if role_name == 'viewer':
        query = query.where(AuditLog.action.in_(LOGIN_ACTIONS + DANGEROUS_ACTIONS))
    elif category:
        if category == 'login':
            query = query.where(AuditLog.action.in_(LOGIN_ACTIONS))
        elif category == 'dangerous':
            query = query.where(AuditLog.action.in_(DANGEROUS_ACTIONS))

    if user:
        query = query.where(AuditLog.user.like(f"%{user}%"))
    if action:
        query = query.where(AuditLog.action.like(f"%{action}%"))
    query = query.order_by(AuditLog.created_at.desc())
    result = await db.execute(query.offset(page.skip).limit(page.limit))
    logs = result.scalars().all()
    
    # 手动序列化并确保时间带 UTC 时区标记
    result = []
    for log in logs:
        created_at = log.created_at
        if created_at:
            # 数据库存储的是 UTC 时间，标记为 UTC
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            created_at_str = created_at.isoformat()
        else:
            created_at_str = None
        
        result.append({
            "id": log.id,
            "user": log.user,
            "action": log.action,
            "resource": log.resource,
            "detail": log.detail,
            "ipAddress": log.ip_address,
            "createdAt": created_at_str,
            "success": log.success
        })
    
    return result

@router.get("/{log_id}", response_model=AuditLogResponse)
async def read_log(
    log_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(AuditLog).where(AuditLog.id == log_id))
    log = result.scalar_one_or_none()
    if log is None:
        raise HTTPException(status_code=404, detail="Log not found")
    return log

@router.post("/", response_model=AuditLogResponse, status_code=status.HTTP_201_CREATED)
async def create_log(
    log: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_superuser)
):
    """手动写入审计日志（仅超级管理员，防止任意登录用户伪造审计记录）"""
    stmt = insert(AuditLog).values(**log).returning(AuditLog)
    result = await db.execute(stmt)
    await db.commit()
    return result.scalar_one()
