"""LDAP认证API路由"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update
import json

from ..database import get_db
from ..models import User, Role, AuditLog, SystemConfig
from ..services.ldap_service import ldap_service, LDAPException as LDAPAuthException
from ..utils.ip_whitelist import get_client_ip_from_request
from ..utils.login_throttle import check_login_allowed, record_login_failure, reset_login_failures, LoginThrottled
from .dependencies import get_current_superuser
from ..api.system import encrypt_secret, decrypt_secret


router = APIRouter()
logger = logging.getLogger(__name__)

# Request body models
class LDAPLoginRequest(BaseModel):
    """LDAP登录请求体"""
    username: str
    password: str

class LDAPConfigRequest(BaseModel):
    """LDAP配置请求体"""
    enabled: bool
    server: str
    port: int = 389
    use_ssl: bool = False
    use_starttls: bool = False
    verify_cert: bool = True
    bind_dn: str = ""
    bind_password: Optional[str] = None  # 留空表示不修改
    base_dn: str = ""
    user_filter: str = "(objectClass=person)"
    username_attr: str = "sAMAccountName"
    display_attr: str = "displayName"
    email_attr: str = "mail"
    phone_attr: str = "mobile"
    department_attr: str = "department"
    group_attr: str = "memberOf"
    default_role: str = "viewer"


async def log_login_attempt(db: AsyncSession, username: str, success: bool, ip_address: str = None,
                            reason: str = None):
    """记录登录尝试日志（只记原因分类，绝不记录密码）"""
    detail = "LDAP登录成功" if success else f"LDAP登录失败：{reason or '用户名或密码错误'}"
    stmt = insert(AuditLog).values(
        user=username,
        action="用户登录",
        resource="系统",
        detail=detail,
        ip_address=ip_address,
        success="true" if success else "false"
    )
    await db.execute(stmt)
    await db.commit()


@router.get("/ldap/enabled")
async def is_ldap_enabled(db: AsyncSession = Depends(get_db)):
    """检查LDAP是否启用"""
    config = await ldap_service.get_config(db)
    return {"enabled": config.enabled}


@router.get("/ldap/config")
async def get_ldap_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """获取LDAP配置（仅super_admin，不回显 bind_password 明文）"""
    config = await ldap_service.get_config(db)
    return config.to_dict()


@router.put("/ldap/config")
async def update_ldap_config(
    request: LDAPConfigRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """更新LDAP配置（仅super_admin；bind_password 留空则保留原值）"""
    # 读取库中现有配置，用于「留空不修改」
    stmt = select(SystemConfig).where(SystemConfig.key == "ldap_config")
    result = await db.execute(stmt)
    db_config = result.scalar_one_or_none()

    existing_data = {}
    if db_config and db_config.value:
        try:
            existing_data = json.loads(db_config.value)
        except Exception:
            existing_data = {}

    config_data = request.model_dump()

    # bind_password 处理：非空 → 加密存储；空/None → 保留原值
    submitted_password = (request.bind_password or "").strip()
    if submitted_password:
        config_data["bind_password"] = encrypt_secret(submitted_password)
    else:
        config_data["bind_password"] = existing_data.get("bind_password", "")

    if db_config:
        stmt = update(SystemConfig).where(
            SystemConfig.key == "ldap_config"
        ).values(value=json.dumps(config_data))
        await db.execute(stmt)
    else:
        db_config = SystemConfig(
            key="ldap_config",
            value=json.dumps(config_data),
            description="LDAP认证配置"
        )
        db.add(db_config)

    # 记录审计日志（只记字段名，不记字段值）
    stmt = insert(AuditLog).values(
        user=current_user.username,
        action="修改LDAP配置",
        resource="系统",
        detail="更新LDAP认证配置，修改字段: " + ", ".join(config_data.keys()),
        success="true"
    )
    await db.execute(stmt)
    await db.commit()

    return {"message": "LDAP配置更新成功"}


@router.post("/ldap/test")
async def test_ldap_connection(
    request: LDAPConfigRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """测试LDAP连接（仅super_admin；bind_password 留空时自动取已存配置）"""
    from ..services.ldap_service import LDAPConfig

    config = LDAPConfig()
    config.enabled = request.enabled
    config.server = request.server
    config.port = request.port
    config.use_ssl = request.use_ssl
    config.use_starttls = request.use_starttls
    config.verify_cert = request.verify_cert
    config.bind_dn = request.bind_dn
    config.base_dn = request.base_dn

    # 留空时用库中已存的密码（解密），避免前端回传明文
    submitted_password = (request.bind_password or "").strip()
    if submitted_password:
        config.bind_password = submitted_password
    else:
        stmt = select(SystemConfig).where(SystemConfig.key == "ldap_config")
        result = await db.execute(stmt)
        db_config = result.scalar_one_or_none()
        if db_config and db_config.value:
            try:
                stored = json.loads(db_config.value).get("bind_password", "")
                config.bind_password = decrypt_secret(stored)
            except Exception:
                config.bind_password = ""

    success = await ldap_service.test_connection(config)

    # 记录审计日志
    stmt = insert(AuditLog).values(
        user=current_user.username,
        action="测试LDAP配置",
        resource="系统",
        detail="测试LDAP连接: " + ("成功" if success else "失败"),
        success="true" if success else "false"
    )
    await db.execute(stmt)
    await db.commit()

    if success:
        return {"success": True, "message": "LDAP连接测试成功"}
    else:
        return {"success": False, "message": "LDAP连接测试失败"}


@router.post("/ldap/login")
async def ldap_login(
    request: Request,
    body: LDAPLoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """LDAP用户登录（与本地登录共用同一套限流：用户名锁定 + IP 限流）"""
    client_ip = get_client_ip_from_request(request)
    user_agent = request.headers.get("User-Agent", "")

    try:
        await check_login_allowed(body.username, client_ip)
    except LoginThrottled as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    try:
        result = await ldap_service.login(db, body.username, body.password, client_ip, user_agent)
        await reset_login_failures(body.username, client_ip)
        return result
    except LDAPAuthException as e:
        logger.warning(f"LDAP 登录认证失败 username={body.username}: {e}")
        await log_login_attempt(db, body.username, False, client_ip)
        await record_login_failure(body.username, client_ip)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    except Exception as e:
        # LDAP 服务故障不属于认证失败，不计入限流，但记审计
        logger.error(f"LDAP 登录异常 username={body.username}", exc_info=True)
        await log_login_attempt(db, body.username, False, client_ip, reason="LDAP服务暂不可用")
        raise HTTPException(status_code=500, detail="LDAP 服务暂不可用，请稍后重试")
