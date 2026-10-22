"""系统配置API"""
import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, insert
from pydantic import BaseModel

from ..database import get_db
from ..models import SystemConfig, AuditLog
from ..api.dependencies import get_current_superuser
from ..models import User
from ..utils.ip_whitelist import get_client_ip_from_request
from ..utils.crypto import encrypt_password, decrypt_password

router = APIRouter()

# 加密密文前缀：迁移脚本与读取逻辑据此判断是否已加密
SECRET_ENC_PREFIX = "enc:"


def encrypt_secret(plain: str) -> str:
    """加密 secret 并加 enc: 前缀（与存量明文区分）。"""
    return SECRET_ENC_PREFIX + encrypt_password(plain)


def decrypt_secret(stored: str) -> str:
    """解密 secret：带 enc: 前缀的解密，无前缀的兼容返回明文（迁移前旧数据）。"""
    if not stored:
        return ""
    if stored.startswith(SECRET_ENC_PREFIX):
        return decrypt_password(stored[len(SECRET_ENC_PREFIX):])
    return stored


class SSOConfigModel(BaseModel):
    """SSO配置模型"""
    enabled: bool = False
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    authorize_url: Optional[str] = None
    token_url: Optional[str] = None
    userinfo_url: Optional[str] = None
    redirect_url: Optional[str] = None
    login_methods: str = "local,oauth2,saml"
    allowed_redirect_hosts: Optional[str] = None  # 可选：redirect_url 域名白名单（逗号分隔）


# 登录方式白名单；local 必须保留，否则会把本地登录从登录页挤掉
ALLOWED_LOGIN_METHODS = {"local", "oauth2", "saml"}


def _validate_login_methods(login_methods: str) -> str:
    """校验并规范化 login_methods（去空白、去重、保序、必含 local）。"""
    methods = [m.strip().lower() for m in (login_methods or "").split(",") if m.strip()]
    invalid = [m for m in methods if m not in ALLOWED_LOGIN_METHODS]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的登录方式: {', '.join(invalid)}（可选: local, oauth2, saml）"
        )
    if "local" not in methods:
        raise HTTPException(status_code=400, detail="登录方式必须包含 local（本地登录）")
    # 去重保序
    seen = []
    for m in methods:
        if m not in seen:
            seen.append(m)
    return ",".join(seen)


def _validate_redirect_url(redirect_url: Optional[str], allowed_hosts: Optional[str]):
    """redirect_url 强制 https；配置了域名白名单时域名必须在白名单内。"""
    if not redirect_url or not redirect_url.strip():
        return
    url = redirect_url.strip()
    if not url.lower().startswith("https://"):
        raise HTTPException(status_code=400, detail="回调地址 redirect_url 必须以 https:// 开头")
    if not allowed_hosts or not allowed_hosts.strip():
        return  # 未配置白名单 → 仅要求 https，不拦截（避免打挂现有配置）
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    whitelist = [h.strip().lower().lstrip("*.") for h in allowed_hosts.split(",") if h.strip()]
    if host not in whitelist:
        raise HTTPException(
            status_code=400,
            detail=f"回调地址域名 {host} 不在白名单内（允许: {', '.join(whitelist)}）"
        )


async def _load_sso_raw(db: AsyncSession) -> dict:
    """读取库中 sso_config 原始 JSON（无则返回空 dict）。"""
    result = await db.execute(
        select(SystemConfig).where(SystemConfig.key == "sso_config")
    )
    config = result.scalar_one_or_none()
    if not config or not config.value:
        return {}
    try:
        return json.loads(config.value)
    except Exception:
        return {}


def _audit(db: AsyncSession, current_user: User, request, action: str, detail: str):
    """写系统配置审计日志（不提交，由调用方统一 commit）。"""
    db.add(AuditLog(
        user=current_user.username,
        action=action,
        resource="系统",
        detail=detail,
        ip_address=get_client_ip_from_request(request) if request else None,
        success="true"
    ))


@router.get("/sso-config")
async def get_sso_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser)
):
    """获取SSO配置（仅super_admin，secret 只回显是否已设置）"""
    data = await _load_sso_raw(db)
    if not data:
        return {**SSOConfigModel().model_dump(), "has_client_secret": False}

    has_secret = bool(data.get("client_secret"))
    data.pop("client_secret", None)  # 永不回显 secret
    payload = SSOConfigModel(**data).model_dump()
    payload.pop("client_secret", None)  # 键也不保留
    return {**payload, "has_client_secret": has_secret}


@router.post("/sso-config")
async def save_sso_config(
    config: SSOConfigModel,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    """保存SSO配置（仅super_admin；client_secret 留空则保留原值）"""
    # login_methods 白名单校验（必含 local）；redirect_url 强制 https + 可选域名白名单
    config.login_methods = _validate_login_methods(config.login_methods)
    _validate_redirect_url(config.redirect_url, config.allowed_redirect_hosts)

    existing = await _load_sso_raw(db)

    # client_secret 处理：空 → 保留原值；非空 → 加密存储
    submitted_secret = (config.client_secret or "").strip()
    if submitted_secret:
        stored_secret = encrypt_secret(submitted_secret)
    else:
        stored_secret = existing.get("client_secret")  # 留空不修改（兼容存量明文/密文）

    config_data = config.model_dump(exclude={"client_secret"})
    config_data["client_secret"] = stored_secret
    config_json = json.dumps(config_data)

    result = await db.execute(
        select(SystemConfig).where(SystemConfig.key == "sso_config")
    )
    existing_config = result.scalar_one_or_none()

    if existing_config:
        existing_config.value = config_json
    else:
        db.add(SystemConfig(
            key="sso_config",
            value=config_json,
            description="SSO单点登录配置"
        ))

    _audit(db, current_user, None, "修改SSO配置", "更新SSO单点登录配置")
    await db.commit()
    return {"message": "SSO配置保存成功"}


@router.post("/sso-config/test")
async def test_sso_config(
    config: SSOConfigModel,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    """测试SSO配置（仅super_admin；client_secret 留空时自动取已存配置）"""
    import httpx

    if not config.client_id or not config.authorize_url:
        raise HTTPException(status_code=400, detail="缺少必要的配置参数")

    # 与保存同规则校验，避免测完再存才发现非法
    _validate_login_methods(config.login_methods)
    _validate_redirect_url(config.redirect_url, config.allowed_redirect_hosts)

    # 留空时用库中已存 secret（解密），避免前端回传明文
    secret = (config.client_secret or "").strip()
    if not secret:
        existing = await _load_sso_raw(db)
        secret = decrypt_secret(existing.get("client_secret") or "")

    try:
        # 测试连接到授权端点
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(config.authorize_url, follow_redirects=True)

            if response.status_code in [200, 302, 400, 401, 403]:
                # 这些状态码都表示端点可达
                _audit(db, current_user, None, "测试SSO配置",
                       f"SSO授权端点可达 (状态码: {response.status_code})")
                await db.commit()
                return {"message": f"授权端点可达 (状态码: {response.status_code})"}
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"授权端点返回异常状态码: {response.status_code}"
                )
    except httpx.TimeoutException:
        raise HTTPException(status_code=400, detail="连接超时")
    except httpx.ConnectError:
        raise HTTPException(status_code=400, detail="无法连接到授权端点")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"测试失败: {str(e)}")


@router.delete("/sso-config")
async def reset_sso_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    """重置SSO配置（仅super_admin）"""
    await db.execute(
        delete(SystemConfig).where(SystemConfig.key == "sso_config")
    )
    _audit(db, current_user, None, "重置SSO配置", "重置SSO单点登录配置")
    await db.commit()

    return {"message": "SSO配置已重置"}
