from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete
import json
import base64
import io
from datetime import datetime, timedelta
from pydantic import BaseModel, Field, field_validator
from pydantic import EmailStr, ValidationError
from ..database import get_db
from ..models.setting import Setting
from ..schemas.setting import SettingResponse, NotificationSettingsRequest, NotificationSettingsResponse, TestNotificationResponse
from ..models.audit_log import AuditLog
from ..models.alert import AlertNotification
from ..config import settings as app_config
from ..services.alert_service import AlertService
from ..api.dependencies import require_super_admin
from ..utils.logger import get_logger

router = APIRouter()
logger = get_logger()

NOTIFICATION_SETTINGS_KEY = "notification_settings"
AI_INSPECTION_SETTINGS_KEY = "ai_inspection_settings"
LOG_SETTINGS_KEY = "log_settings"
COMPANY_INFO_KEY = "company_info"
BRAND_SETTINGS_KEY = "brand_settings"
IP_WHITELIST_KEY = "security.ip_whitelist"

# 默认品牌设置
BRAND_SETTINGS_DEFAULTS = {
    "brand_name_zh": "基石",
    "brand_name_en": "Cornerstone",
    "brand_slogan": "智能运维，尽在掌控",
    "brand_subtitle": "企业级IT基础设施智能运维平台",
    "brand_logo_url": "",
}

# 需要脱敏的字段（含密码/密钥）
_SENSITIVE_FIELDS = {"smtp_password", "api_key", "password", "secret", "token"}


def _mask_setting_value(key: str, value: str | None) -> str:
    """对配置值脱敏后返回，便于安全输出到日志。"""
    if value is None:
        return "<None>"
    # company_logo 是 base64 图片，过长，只记录长度
    if key == "company_logo":
        return f"<base64 image, {len(value)} chars>"
    # 通知设置等 JSON 含敏感字段，逐项脱敏
    try:
        data = json.loads(value)
        if isinstance(data, dict):
            masked = {
                k: ("***" if any(s in k.lower() for s in _SENSITIVE_FIELDS) else v)
                for k, v in data.items()
            }
            return json.dumps(masked, ensure_ascii=False)
        if isinstance(data, list):
            masked = [
                {kk: ("***" if any(s in kk.lower() for s in _SENSITIVE_FIELDS) else vv) for kk, vv in item.items()}
                if isinstance(item, dict) else item
                for item in data
            ]
            return json.dumps(masked, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        pass
    # 普通字符串超长则截断
    return value if len(value) <= 500 else value[:500] + f"...(truncated, {len(value)} chars)"


def _log_setting_before(user: str, action: str, key: str, old_setting: Setting | None) -> None:
    """记录配置变更前的状态。"""
    if old_setting:
        logger.info(
            "[配置变更-前] user=%s action=%s key=%s 存在=是 旧值=%s",
            user, action, key, _mask_setting_value(key, old_setting.value),
        )
    else:
        logger.info(
            "[配置变更-前] user=%s action=%s key=%s 存在=否（将新建）",
            user, action, key,
        )


def _log_setting_after(user: str, action: str, key: str, new_value: str | None, created: bool) -> None:
    """记录配置变更后的状态。"""
    logger.info(
        "[配置变更-后] user=%s action=%s key=%s 结果=%s 新值=%s",
        user, action, key, "新建" if created else ("删除" if new_value is None else "更新"),
        _mask_setting_value(key, new_value) if new_value is not None else "<已删除>",
    )


async def _audit_setting(
    db: AsyncSession,
    request: Request,
    user,
    action: str,
    detail: str,
) -> None:
    """设置类写操作写入 audit_logs 表（与用户/SSO 模块同轨，便于系统内追溯）。"""
    from ..utils.ip_whitelist import get_client_ip_from_request

    audit_log = AuditLog(
        user=user.username,
        action=action,
        resource="system_settings",
        detail=detail,
        ip_address=get_client_ip_from_request(request),
        success="true",
    )
    db.add(audit_log)
    await db.commit()


class BrandSettingsRequest(BaseModel):
    brand_slogan: str = Field(default=BRAND_SETTINGS_DEFAULTS["brand_slogan"], max_length=200)
    brand_subtitle: str = Field(default=BRAND_SETTINGS_DEFAULTS["brand_subtitle"], max_length=200)
    brand_logo_url: str = Field(default="", max_length=500)

    @field_validator("brand_slogan", "brand_subtitle")
    @classmethod
    def strip_and_limit(cls, v: str, info) -> str:
        v = v.strip()
        limits = {"brand_slogan": 50, "brand_subtitle": 100}
        limit = limits.get(info.field_name)
        if limit and len(v) > limit:
            raise ValueError(f"{info.field_name} 长度不能超过 {limit} 个字符")
        return v

class BrandSettingsResponse(BaseModel):
    brand_name_zh: str
    brand_name_en: str
    brand_slogan: str
    brand_subtitle: str
    brand_logo_url: str

@router.get("/brand", response_model=BrandSettingsResponse)
async def get_brand_settings(
    db: AsyncSession = Depends(get_db),
):
    """获取品牌设置，公共接口，不需要登录"""
    result = await db.execute(select(Setting).filter(Setting.key == BRAND_SETTINGS_KEY))
    setting = result.scalars().first()
    
    if setting:
        try:
            config = json.loads(setting.value)
            return BrandSettingsResponse(**config)
        except json.JSONDecodeError:
            pass
    
    return BrandSettingsResponse(**BRAND_SETTINGS_DEFAULTS)

@router.get("/public/brand", response_model=BrandSettingsResponse)
async def get_public_brand_settings(
    db: AsyncSession = Depends(get_db),
):
    """公开获取品牌设置，不需要登录，用于登录页显示"""
    result = await db.execute(select(Setting).filter(Setting.key == BRAND_SETTINGS_KEY))
    setting = result.scalars().first()
    
    if setting:
        try:
            config = json.loads(setting.value)
            return BrandSettingsResponse(**config)
        except json.JSONDecodeError:
            pass
    
    return BrandSettingsResponse(**BRAND_SETTINGS_DEFAULTS)

@router.put("/brand", response_model=dict)
async def update_brand_settings(
    request: BrandSettingsRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_super_admin),
):
    """更新品牌设置，仅超级管理员。系统名称（基石/Cornerstone）已锁定，不可修改"""
    config_dict = {
        "brand_name_zh": BRAND_SETTINGS_DEFAULTS["brand_name_zh"],
        "brand_name_en": BRAND_SETTINGS_DEFAULTS["brand_name_en"],
        "brand_slogan": request.brand_slogan or BRAND_SETTINGS_DEFAULTS["brand_slogan"],
        "brand_subtitle": request.brand_subtitle or BRAND_SETTINGS_DEFAULTS["brand_subtitle"],
        "brand_logo_url": request.brand_logo_url,
    }
    config_json = json.dumps(config_dict, ensure_ascii=False)

    result = await db.execute(select(Setting).filter(Setting.key == BRAND_SETTINGS_KEY))
    setting = result.scalars().first()
    _log_setting_before(current_user.username, "更新品牌设置", BRAND_SETTINGS_KEY, setting)

    created = setting is None
    if setting:
        setting.value = config_json
    else:
        setting = Setting(key=BRAND_SETTINGS_KEY, value=config_json)
        db.add(setting)

    await db.commit()
    _log_setting_after(current_user.username, "更新品牌设置", BRAND_SETTINGS_KEY, config_json, created)
    await _audit_setting(db, http_request, current_user, "brand_update", "更新品牌设置（标语/副标题）")

    return {"message": "品牌设置更新成功"}

@router.post("/brand/reset", response_model=dict)
async def reset_brand_settings(
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_super_admin),
):
    """重置为默认品牌设置（仅重置标语/副标题，不影响 Logo 与公司信息）"""
    result = await db.execute(select(Setting).filter(Setting.key == BRAND_SETTINGS_KEY))
    setting = result.scalars().first()
    _log_setting_before(current_user.username, "重置品牌设置", BRAND_SETTINGS_KEY, setting)

    if setting:
        await db.delete(setting)
        await db.commit()
    _log_setting_after(current_user.username, "重置品牌设置", BRAND_SETTINGS_KEY, None, False)
    await _audit_setting(db, http_request, current_user, "brand_reset", "重置品牌设置为默认值")

    return {"message": "已恢复为默认品牌设置"}


# ============ Logo API ============

# 各图片格式的魔数（文件头字节）
_IMAGE_MAGIC_SIGNATURES = {
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/gif": [b"GIF87a", b"GIF89a"],
    "image/webp": [b"RIFF"],  # 需额外校验 8-12 字节为 WEBP
}


def _verify_image_magic(content: bytes) -> bool:
    """按文件头字节 + 解码验证校验图片内容是否为白名单中的真实图片格式。

    第一层：文件头魔数匹配（快速拦截明显非图片的内容）。
    第二层：Pillow 解码验证（防止伪造魔数头的垃圾文件绕过，
    如「PNG 头 + 任意字节」的文件）。
    """
    matched = False
    for sigs in _IMAGE_MAGIC_SIGNATURES.values():
        for sig in sigs:
            if content[:len(sig)] == sig:
                if sig == b"RIFF":
                    # WebP：RIFF 容器头后 4 字节必须是 WEBP
                    if not (len(content) >= 12 and content[8:12] == b"WEBP"):
                        return False
                matched = True
                break
        if matched:
            break
    if not matched:
        return False

    # 第二层：完整解码验证（防伪造魔数头的损坏/伪造文件）
    from PIL import Image
    try:
        with Image.open(io.BytesIO(content)) as img:
            img.verify()
        return True
    except Exception:
        return False


class CompanyInfoRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=200)
    company_short_name: str = Field(default="", max_length=100)
    it_department_name: str = Field(default="信息技术部", max_length=100)
    it_contact_name: str = Field(default="", max_length=50)
    it_contact_email: str = Field(default="", max_length=254)

    @field_validator("company_name", "company_short_name", "it_department_name", "it_contact_name")
    @classmethod
    def strip_fields(cls, v: str) -> str:
        return v.strip()

    @field_validator("company_name")
    @classmethod
    def company_name_required(cls, v: str) -> str:
        if not v:
            raise ValueError("公司全称不能为空")
        return v

    @field_validator("it_contact_email")
    @classmethod
    def email_optional(cls, v: str) -> str:
        v = v.strip()
        if not v:
            return ""
        # 空串合法；非空时校验邮箱格式（用 EmailStr 做一次校验后返回原值，避免强转）
        try:
            EmailStr._validate(v)
        except ValidationError:
            raise ValueError("IT负责人邮箱格式不正确")
        return v


class TestNotificationRequest(BaseModel):
    channel: str  # dingtalk, wechat, feishu, email


class AIInspectionSettingsRequest(BaseModel):
    enabled: bool = False


class AIInspectionSettingsResponse(BaseModel):
    enabled: bool = False


class AIPrivacySettingsRequest(BaseModel):
    """AI 外发隐私设置：开启后所有 LLM 调用链路跳过（走本地降级）"""
    block_external: bool = False


class AIPrivacySettingsResponse(BaseModel):
    block_external: bool = False


AI_PRIVACY_SETTINGS_KEY = "ai_privacy_settings"


class LogSettingsRequest(BaseModel):
    log_retention_days: int = 90
    login_log_retention_days: int = 180
    log_auto_cleanup: bool = True
    login_max_attempts: int = 5
    session_timeout_minutes: int = 120
    allow_concurrent_login: bool = True
    alert_on_foreign_login: bool = False
    log_query_operations: bool = False
    log_export_operations: bool = True
    log_login_operations: bool = True
    require_confirm_dangerous: bool = True


class LogSettingsResponse(BaseModel):
    log_retention_days: int
    login_log_retention_days: int
    log_auto_cleanup: bool
    login_max_attempts: int
    session_timeout_minutes: int
    allow_concurrent_login: bool
    alert_on_foreign_login: bool
    log_query_operations: bool
    log_export_operations: bool
    log_login_operations: bool
    require_confirm_dangerous: bool


class CleanupResponse(BaseModel):
    deleted_count: int
    duration_ms: int

@router.get("/logo", response_model=SettingResponse)
async def get_logo(db: AsyncSession = Depends(get_db)):
    """获取当前Logo"""
    result = await db.execute(select(Setting).filter(Setting.key == "company_logo"))
    setting = result.scalars().first()
    if setting:
        return {"key": setting.key, "value": setting.value}
    return {"key": "company_logo", "value": ""}

@router.post("/logo")
async def upload_logo(
    http_request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_super_admin)
):
    """上传Logo"""
    # 验证文件类型（Content-Type 白名单）
    allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="不支持的图片格式")

    # 验证文件大小（最大2MB）
    max_size = 2 * 1024 * 1024
    content = await file.read()
    if len(content) > max_size:
        raise HTTPException(status_code=400, detail="图片大小不能超过2MB")

    # 魔数校验：文件头字节必须与声明格式一致（防止伪装 Content-Type 上传任意文件）
    if not _verify_image_magic(content):
        raise HTTPException(status_code=400, detail="图片内容与格式不符或文件已损坏")

    # 存储到数据库
    logo_value = base64.b64encode(content).decode('ascii')
    result = await db.execute(select(Setting).filter(Setting.key == "company_logo"))
    setting = result.scalars().first()
    _log_setting_before(current_user.username, "上传Logo", "company_logo", setting)

    created = setting is None
    if setting:
        setting.value = logo_value
    else:
        setting = Setting(key="company_logo", value=logo_value)
        db.add(setting)
    await db.commit()
    _log_setting_after(current_user.username, "上传Logo", "company_logo", logo_value, created)
    await _audit_setting(db, http_request, current_user, "logo_upload", f"上传Logo（{file.content_type}，{len(content)} 字节）")

    return {"message": "Logo上传成功"}

@router.delete("/logo")
async def delete_logo(
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_super_admin)
):
    """删除Logo"""
    result = await db.execute(select(Setting).filter(Setting.key == "company_logo"))
    setting = result.scalars().first()
    _log_setting_before(current_user.username, "删除Logo", "company_logo", setting)

    if setting:
        await db.delete(setting)
        await db.commit()
    _log_setting_after(current_user.username, "删除Logo", "company_logo", None, False)
    await _audit_setting(db, http_request, current_user, "logo_delete", "删除Logo（恢复默认）")

    return {"message": "Logo已删除"}

@router.get("/notification", response_model=NotificationSettingsResponse)
async def get_notification_settings(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_super_admin)
):
    """获取通知渠道配置（密钥字段只回 has_xxx + 尾 8 字符，不回原文）"""
    from ..utils.notification_store import load_stored_config, mask_config_for_display

    stored = await load_stored_config(db)
    if stored:
        masked = mask_config_for_display(stored)
        return NotificationSettingsResponse(**masked)

    # 无库配置：回落环境变量（同样只回 has_xxx 形态）
    n = app_config.notification
    return NotificationSettingsResponse(
        has_dingtalk_webhook_url=bool(n.dingtalk_webhook_url),
        has_wechat_webhook_url=bool(n.wechat_webhook_url),
        has_feishu_webhook_url=bool(n.feishu_webhook_url),
        has_smtp_password=bool(n.smtp_password),
        dingtalk_webhook_url_tail=(n.dingtalk_webhook_url or "")[-8:],
        wechat_webhook_url_tail=(n.wechat_webhook_url or "")[-8:],
        feishu_webhook_url_tail=(n.feishu_webhook_url or "")[-8:],
        smtp_password_tail=(n.smtp_password or "")[-8:],
        smtp_host=n.smtp_host,
        smtp_port=n.smtp_port,
        smtp_username=n.smtp_username,
        smtp_from_email=n.smtp_from_email,
        smtp_security="starttls",
        channel_enabled={},
    )

@router.put("/notification", response_model=NotificationSettingsResponse)
async def update_notification_settings(
    request: NotificationSettingsRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_super_admin)
):
    """更新通知渠道配置

    - 密钥字段（webhook/smtp_password）传 None/空串 = 留空不修改（保留库中旧值）
    - 密钥字段加密落库（enc: 前缀）
    - webhook 强制 https + 域名白名单
    - 写审计日志（脱敏 detail）
    """
    from ..utils.notification_store import (
        load_stored_config, save_stored_config, validate_webhook_url,
        mask_config_for_display, DEFAULT_CHANNEL_ENABLED,
    )

    # webhook 校验（PUT 与 test 双重校验的第一重）
    try:
        validate_webhook_url(request.dingtalk_webhook_url or "", "钉钉")
        validate_webhook_url(request.wechat_webhook_url or "", "企业微信")
        validate_webhook_url(request.feishu_webhook_url or "", "飞书")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    smtp_security = (request.smtp_security or "starttls").lower()
    if smtp_security not in ("none", "starttls", "ssl"):
        raise HTTPException(status_code=422, detail="SMTP 加密方式仅支持 none/starttls/ssl")

    old_stored = await load_stored_config(db)
    _log_setting_before(current_user.username, "更新通知设置", NOTIFICATION_SETTINGS_KEY,
                        type("S", (), {"value": json.dumps(old_stored, ensure_ascii=False)})() if old_stored else None)

    # 留空不修改：密钥字段为空时保留旧值
    def _keep_old(new_val: str | None, field: str) -> str | None:
        if new_val and str(new_val).strip():
            return str(new_val).strip()
        return old_stored.get(field)

    # 明文字段：None 表示未传；区分「清空」与「留空不修改」仅对密钥字段生效
    new_config = {
        "dingtalk_webhook_url": _keep_old(request.dingtalk_webhook_url, "dingtalk_webhook_url") or "",
        "wechat_webhook_url": _keep_old(request.wechat_webhook_url, "wechat_webhook_url") or "",
        "feishu_webhook_url": _keep_old(request.feishu_webhook_url, "feishu_webhook_url") or "",
        "smtp_host": request.smtp_host if request.smtp_host is not None else old_stored.get("smtp_host"),
        "smtp_port": request.smtp_port if request.smtp_port is not None else old_stored.get("smtp_port", 25),
        "smtp_username": request.smtp_username if request.smtp_username is not None else old_stored.get("smtp_username"),
        "smtp_password": _keep_old(request.smtp_password, "smtp_password") or "",
        "smtp_from_email": request.smtp_from_email if request.smtp_from_email is not None else old_stored.get("smtp_from_email"),
        "smtp_security": smtp_security,
        "channel_enabled": request.channel_enabled if request.channel_enabled is not None
            else old_stored.get("channel_enabled") or dict(DEFAULT_CHANNEL_ENABLED),
    }

    await save_stored_config(db, new_config)

    masked = mask_config_for_display(new_config)
    _log_setting_after(current_user.username, "更新通知设置", NOTIFICATION_SETTINGS_KEY,
                       json.dumps(masked, ensure_ascii=False), not old_stored)

    # 审计（脱敏：只记渠道开关与「哪些密钥字段有值」，不记任何密钥内容）
    changed_secrets = [f for f in ("dingtalk_webhook_url", "wechat_webhook_url", "feishu_webhook_url", "smtp_password")
                       if request.__getattribute__(f)]
    enabled_channels = [k for k, v in new_config["channel_enabled"].items() if v]
    await _audit_setting(
        db, http_request, current_user, "notification_update",
        f"更新通知配置：已配置渠道={enabled_channels or '无'}，"
        f"更新密钥字段={changed_secrets or '无（全部留空）'}，"
        f"SMTP加密={smtp_security}",
    )

    return NotificationSettingsResponse(**mask_config_for_display(new_config))


@router.get("/ai-inspection", response_model=AIInspectionSettingsResponse)
async def get_ai_inspection_settings(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_super_admin)
):
    """获取巡检 AI 二次研判开关配置"""
    result = await db.execute(select(Setting).filter(Setting.key == AI_INSPECTION_SETTINGS_KEY))
    setting = result.scalars().first()

    if setting:
        try:
            config = json.loads(setting.value)
            return AIInspectionSettingsResponse(enabled=bool(config.get("enabled", False)))
        except json.JSONDecodeError:
            pass

    return AIInspectionSettingsResponse(enabled=False)


@router.put("/ai-inspection", response_model=AIInspectionSettingsResponse)
async def update_ai_inspection_settings(
    request: AIInspectionSettingsRequest,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_super_admin)
):
    """更新巡检 AI 二次研判开关配置"""
    config_dict = {"enabled": bool(request.enabled)}
    config_json = json.dumps(config_dict)

    result = await db.execute(select(Setting).filter(Setting.key == AI_INSPECTION_SETTINGS_KEY))
    setting = result.scalars().first()
    _log_setting_before(current_user.username, "更新巡检AI二次研判开关", AI_INSPECTION_SETTINGS_KEY, setting)

    created = setting is None
    if setting:
        setting.value = config_json
    else:
        setting = Setting(key=AI_INSPECTION_SETTINGS_KEY, value=config_json)
        db.add(setting)

    await db.commit()
    _log_setting_after(current_user.username, "更新巡检AI二次研判开关", AI_INSPECTION_SETTINGS_KEY, config_json, created)

    return AIInspectionSettingsResponse(**config_dict)


@router.get("/ai-privacy", response_model=AIPrivacySettingsResponse)
async def get_ai_privacy_settings(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_super_admin)
):
    """获取 AI 外发隐私设置（禁止外发开关）"""
    result = await db.execute(select(Setting).filter(Setting.key == AI_PRIVACY_SETTINGS_KEY))
    setting = result.scalars().first()

    if setting:
        try:
            config = json.loads(setting.value)
            return AIPrivacySettingsResponse(block_external=bool(config.get("block_external", False)))
        except json.JSONDecodeError:
            pass

    return AIPrivacySettingsResponse(block_external=False)


@router.put("/ai-privacy", response_model=AIPrivacySettingsResponse)
async def update_ai_privacy_settings(
    request: AIPrivacySettingsRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_super_admin)
):
    """更新 AI 外发隐私设置（禁止外发开关）"""
    config_dict = {"block_external": bool(request.block_external)}
    config_json = json.dumps(config_dict)

    result = await db.execute(select(Setting).filter(Setting.key == AI_PRIVACY_SETTINGS_KEY))
    setting = result.scalars().first()

    created = setting is None
    if setting:
        setting.value = config_json
    else:
        setting = Setting(key=AI_PRIVACY_SETTINGS_KEY, value=config_json)
        db.add(setting)

    await db.commit()
    _log_setting_after(current_user.username, "更新AI外发隐私设置", AI_PRIVACY_SETTINGS_KEY, config_json, created)

    await _audit_setting(
        db, http_request, current_user, "ai_privacy_update",
        f"更新AI外发隐私设置：禁止外发={'开启（所有LLM调用跳过）' if request.block_external else '关闭（允许外发）'}",
    )

    return AIPrivacySettingsResponse(**config_dict)


# 测试发送进程内限频：每渠道 N 秒内只允许 1 次（沿 credential_test_rate_limit_seconds 模式）
_notification_test_last: dict[str, float] = {}


@router.post("/notification/test", response_model=TestNotificationResponse)
async def test_notification(
    request: TestNotificationRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_super_admin)
):
    """测试通知渠道：限频 + 审计 + 结果落 alert_notifications"""
    import time as _time
    from ..utils.notification_store import get_notification_config, validate_webhook_url

    channel = request.channel
    if channel not in ("dingtalk", "wechat", "feishu", "email"):
        raise HTTPException(status_code=400, detail="不支持的通知渠道")

    # 限频：同渠道 N 秒 1 次
    limit_seconds = app_config.credential_test_rate_limit_seconds or 10
    now_ts = _time.time()
    last_ts = _notification_test_last.get(channel, 0)
    if limit_seconds > 0 and now_ts - last_ts < limit_seconds:
        raise HTTPException(
            status_code=429,
            detail=f"测试发送过于频繁，请 {int(limit_seconds - (now_ts - last_ts)) + 1} 秒后再试",
        )
    _notification_test_last[channel] = now_ts

    config = await get_notification_config(db)

    test_message = "【测试通知】这是一条来自基石系统的测试消息，通知渠道配置成功！"
    senders = {
        "dingtalk": (lambda: AlertService._send_dingtalk_notification(config["dingtalk_webhook_url"], test_message),
                     "钉钉Webhook地址未配置", lambda: validate_webhook_url(config["dingtalk_webhook_url"], "钉钉")),
        "wechat": (lambda: AlertService._send_wechat_notification(config["wechat_webhook_url"], test_message),
                   "企业微信Webhook地址未配置", lambda: validate_webhook_url(config["wechat_webhook_url"], "企业微信")),
        "feishu": (lambda: AlertService._send_feishu_notification(config["feishu_webhook_url"], test_message),
                   "飞书Webhook地址未配置", lambda: validate_webhook_url(config["feishu_webhook_url"], "飞书")),
        "email": (lambda: AlertService._send_email_notification(config, test_message),
                  "邮件服务器配置不完整", None),
    }
    sender, not_configured_msg, webhook_validator = senders[channel]

    # 第二重校验：发送前对库中已存 webhook 再校验一次（防存量脏数据直发内网）
    if webhook_validator:
        try:
            webhook_validator()
        except ValueError as e:
            await _audit_setting(db, http_request, current_user, "notification_test",
                                 f"测试发送 {channel} 被拒绝：{e}")
            raise HTTPException(status_code=422, detail=str(e))

    if channel == "email":
        if not all([config.get("smtp_host"), config.get("smtp_username"),
                    config.get("smtp_password"), config.get("smtp_from_email")]):
            await _audit_setting(db, http_request, current_user, "notification_test",
                                 f"测试发送 email 失败：{not_configured_msg}")
            raise HTTPException(status_code=400, detail=not_configured_msg)
    else:
        if not config.get(f"{channel}_webhook_url"):
            await _audit_setting(db, http_request, current_user, "notification_test",
                                 f"测试发送 {channel} 失败：{not_configured_msg}")
            raise HTTPException(status_code=400, detail=not_configured_msg)

    # 结果落 alert_notifications（record_id 为空表示手动测试，无关联告警）
    notification = AlertNotification(
        record_id=None,
        channel=f"{channel}(test)",
        target="",
        status="pending",
    )
    db.add(notification)

    error: str | None = None
    try:
        await sender()
        notification.status = "sent"
        notification.sent_at = datetime.now()
        message = f"{channel} 测试通知发送成功"
        success = True
    except Exception as e:
        notification.status = "failed"
        notification.error_message = str(e)[:500]
        error = str(e)
        message = f"发送失败: {str(e)}"
        success = False
    await db.commit()

    await _audit_setting(
        db, http_request, current_user, "notification_test",
        f"测试发送 {channel}：{'成功' if success else '失败'}" + (f"（{error}）" if error else ""),
    )

    return TestNotificationResponse(
        success=success, message=message, channel=channel,
        status=notification.status or "failed", error=error,
    )


# ============ 日志设置 API ============

@router.get("/logs", response_model=LogSettingsResponse)
async def get_log_settings(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_super_admin)
):
    """获取日志设置（仅 super_admin）"""
    result = await db.execute(select(Setting).filter(Setting.key == LOG_SETTINGS_KEY))
    setting = result.scalars().first()
    
    if setting:
        try:
            config = json.loads(setting.value)
            return LogSettingsResponse(**config)
        except json.JSONDecodeError:
            pass
    
    # 返回默认值
    return LogSettingsResponse(
        log_retention_days=90,
        login_log_retention_days=180,
        log_auto_cleanup=True,
        login_max_attempts=5,
        session_timeout_minutes=120,
        allow_concurrent_login=True,
        alert_on_foreign_login=False,
        log_query_operations=False,
        log_export_operations=True,
        log_login_operations=True,
        require_confirm_dangerous=True
    )


@router.put("/logs", response_model=LogSettingsResponse)
async def update_log_settings(
    request: LogSettingsRequest,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_super_admin)
):
    """保存日志设置（仅 super_admin）"""
    # log_login_operations 不可修改，保持为 True
    config_dict = {
        "log_retention_days": request.log_retention_days,
        "login_log_retention_days": request.login_log_retention_days,
        "log_auto_cleanup": request.log_auto_cleanup,
        "login_max_attempts": request.login_max_attempts,
        "session_timeout_minutes": request.session_timeout_minutes,
        "allow_concurrent_login": request.allow_concurrent_login,
        "alert_on_foreign_login": request.alert_on_foreign_login,
        "log_query_operations": request.log_query_operations,
        "log_export_operations": request.log_export_operations,
        "log_login_operations": True,  # 强制为 True，不可修改
        "require_confirm_dangerous": request.require_confirm_dangerous
    }
    
    config_json = json.dumps(config_dict)

    result = await db.execute(select(Setting).filter(Setting.key == LOG_SETTINGS_KEY))
    setting = result.scalars().first()
    _log_setting_before(current_user.username, "更新日志设置", LOG_SETTINGS_KEY, setting)

    created = setting is None
    if setting:
        setting.value = config_json
    else:
        setting = Setting(key=LOG_SETTINGS_KEY, value=config_json)
        db.add(setting)

    await db.commit()
    _log_setting_after(current_user.username, "更新日志设置", LOG_SETTINGS_KEY, config_json, created)

    return LogSettingsResponse(**config_dict)


@router.post("/logs/cleanup", response_model=CleanupResponse)
async def cleanup_logs(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_super_admin)
):
    """手动触发清理过期日志（仅 super_admin）"""
    start_time = datetime.now()
    
    # 获取日志保留设置
    result = await db.execute(select(Setting).filter(Setting.key == LOG_SETTINGS_KEY))
    setting = result.scalars().first()
    
    log_retention_days = 90
    login_log_retention_days = 180
    
    if setting:
        try:
            config = json.loads(setting.value)
            log_retention_days = config.get("log_retention_days", 90)
            login_log_retention_days = config.get("login_log_retention_days", 180)
        except json.JSONDecodeError:
            pass
    
    # 计算截止日期
    audit_cutoff = datetime.now() - timedelta(days=log_retention_days)
    login_cutoff = datetime.now() - timedelta(days=login_log_retention_days)
    
    # 删除过期审计日志
    deleted_count = 0
    
    # 删除审计日志（登录日志除外）
    audit_result = await db.execute(
        delete(AuditLog).where(
            AuditLog.created_at < audit_cutoff,
            AuditLog.action != 'login',
            AuditLog.action != 'logout'
        )
    )
    deleted_count += audit_result.rowcount
    
    # 删除登录日志
    login_result = await db.execute(
        delete(AuditLog).where(
            AuditLog.created_at < login_cutoff,
            AuditLog.action.in_(['login', 'logout'])
        )
    )
    deleted_count += login_result.rowcount
    
    await db.commit()
    
    end_time = datetime.now()
    duration_ms = int((end_time - start_time).total_seconds() * 1000)
    
    # 记录清理操作到审计日志
    cleanup_log = AuditLog(
        user=current_user.username,
        action='log_cleanup',
        resource='system',
        detail=f"清理了 {deleted_count} 条过期日志（审计日志保留{log_retention_days}天，登录日志保留{login_log_retention_days}天）"
    )
    db.add(cleanup_log)
    await db.commit()
    
    return CleanupResponse(deleted_count=deleted_count, duration_ms=duration_ms)


# ============ 公司信息 API ============

@router.get("/company")
async def get_company_info(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_super_admin)
):
    """获取公司信息配置"""
    result = await db.execute(select(Setting).filter(Setting.key == COMPANY_INFO_KEY))
    setting = result.scalars().first()
    
    if setting:
        try:
            config = json.loads(setting.value)
            return config
        except json.JSONDecodeError:
            pass
    
    return {
        "company_name": "",
        "company_short_name": "",
        "it_department_name": "信息技术部",
        "it_contact_name": "",
        "it_contact_email": ""
    }


@router.put("/company")
async def update_company_info(
    request: CompanyInfoRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_super_admin)
):
    """保存公司信息配置"""
    config_dict = request.model_dump()
    config_json = json.dumps(config_dict, ensure_ascii=False)

    result = await db.execute(select(Setting).filter(Setting.key == COMPANY_INFO_KEY))
    setting = result.scalars().first()
    _log_setting_before(current_user.username, "更新公司信息", COMPANY_INFO_KEY, setting)

    created = setting is None
    if setting:
        setting.value = config_json
    else:
        setting = Setting(key=COMPANY_INFO_KEY, value=config_json)
        db.add(setting)

    await db.commit()
    _log_setting_after(current_user.username, "更新公司信息", COMPANY_INFO_KEY, config_json, created)
    await _audit_setting(
        db, http_request, current_user, "company_update",
        f"更新公司信息（公司全称：{config_dict['company_name']}）",
    )

    return {"message": "公司信息已更新"}


# ============ IP 白名单 API ============

class IPWhitelistRequest(BaseModel):
    whitelist: str  # 每行一个 IP 或 CIDR；# 开头行为注释
    force: bool = False  # True 时允许保存不含操作者 IP 的名单（二次确认）


class IPWhitelistResponse(BaseModel):
    whitelist: str
    enabled: bool
    valid_lines: int = 0      # 解析成功的网段数
    invalid_lines: list[int] = []  # 非法行行号（1 起）
    operator_ip: str = ""     # 当前操作者解析出的客户端 IP
    operator_ip_in_list: bool = True  # 操作者 IP 是否在（解析后的）名单内


class IPPreviewRequest(BaseModel):
    ip: str  # 待预演的 IP 地址


class IPPreviewResponse(BaseModel):
    ip: str
    allowed: bool
    reason: str  # allowed/denied 的原因说明


class MyIPResponse(BaseModel):
    ip: str
    source: str  # x-forwarded-for / x-real-ip / direct


# 白名单锁定错误：结构化错误码，前端据此弹二次确认（force=true 重试）
IP_WHITELIST_LOCKOUT_CODE = "IP_WHITELIST_LOCKOUT"


@router.get("/security/ip-whitelist", response_model=IPWhitelistResponse)
async def get_ip_whitelist(
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_super_admin),
):
    """获取IP白名单配置（仅 super_admin）"""
    from src.utils.ip_whitelist import (
        get_client_ip_with_source,
        parse_whitelist_value,
        is_ip_in_networks,
    )

    result = await db.execute(select(Setting).filter(Setting.key == IP_WHITELIST_KEY))
    setting = result.scalars().first()

    whitelist_text = setting.value if setting else ""
    networks = parse_whitelist_value(whitelist_text)
    client_ip, _source = get_client_ip_with_source(http_request)
    is_loopback = client_ip in ("127.0.0.1", "::1", "localhost")

    return IPWhitelistResponse(
        whitelist=whitelist_text,
        enabled=len(whitelist_text.strip()) > 0,
        valid_lines=len(networks),
        invalid_lines=[],
        operator_ip=client_ip,
        operator_ip_in_list=(
            is_loopback  # 回环默认放行，视为在名单内
            or not networks  # 名单为空（实际全放行）视为在名单内
            or is_ip_in_networks(client_ip, networks)
        ),
    )


@router.put("/security/ip-whitelist", response_model=IPWhitelistResponse)
async def update_ip_whitelist(
    request: IPWhitelistRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_super_admin),
):
    """更新IP白名单配置（仅 super_admin）

    保存校验：
    1. 逐行解析，非法行返回 422 并附带具体行号；
    2. 防自锁：解析后的名单非空且不含操作者 IP 时，拒绝保存并返回
       结构化错误码 IP_WHITELIST_LOCKOUT，前端弹二次确认后带 force=true 重试
       才允许保存（不再静默追加，避免追加被伪造的 IP）。
    """
    from src.utils.ip_whitelist import (
        invalidate_cache,
        get_client_ip_with_source,
        parse_whitelist_lines,
        is_ip_in_networks,
    )

    whitelist_text = request.whitelist.strip()

    # 1) 行级格式校验：非法行带行号报错
    networks, invalid_lines = parse_whitelist_lines(whitelist_text)
    if invalid_lines:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "IP_WHITELIST_INVALID_LINES",
                "invalid_lines": invalid_lines,
                "message": f"第 {', '.join(map(str, invalid_lines))} 行不是合法的 IP 或 CIDR 格式",
            },
        )

    client_ip, _source = get_client_ip_with_source(http_request)

    # 2) 防自锁：名单非空且操作者不在其中 → 拒绝（除非 force=true 二次确认）
    is_loopback = client_ip in ("127.0.0.1", "::1", "localhost")
    if whitelist_text and networks and not is_loopback and not is_ip_in_networks(client_ip, networks):
        if not request.force:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": IP_WHITELIST_LOCKOUT_CODE,
                    "operator_ip": client_ip,
                    "message": (
                        f"您当前的访问 IP（{client_ip}）不在新名单中，保存后您将无法访问系统。"
                        "请确认已包含您的 IP，或使用强制保存。"
                    ),
                },
            )
        logger.warning(
            f"[IP白名单] 用户 {current_user.username} 强制保存不含自身 IP（{client_ip}）的名单"
        )

    result = await db.execute(select(Setting).filter(Setting.key == IP_WHITELIST_KEY))
    setting = result.scalars().first()

    _log_setting_before(current_user.username, "更新IP白名单", IP_WHITELIST_KEY, setting)

    created = setting is None
    if setting:
        setting.value = whitelist_text
    else:
        setting = Setting(key=IP_WHITELIST_KEY, value=whitelist_text)
        db.add(setting)

    await db.commit()
    _log_setting_after(current_user.username, "更新IP白名单", IP_WHITELIST_KEY, whitelist_text, created)

    # 审计落库（与其他设置一致；detail 含修改前后摘要与来源 IP）
    if created:
        action = "ip_whitelist_create"
        detail = f"创建IP白名单（{len(networks)} 个网段），来源IP：{client_ip}"
    elif not whitelist_text:
        action = "ip_whitelist_clear"
        detail = f"清空IP白名单，来源IP：{client_ip}"
    else:
        action = "ip_whitelist_update"
        detail = f"更新IP白名单（{len(networks)} 个网段），来源IP：{client_ip}"
        if request.force:
            detail += "，已强制保存（不含操作者IP）"
    await _audit_setting(db, http_request, current_user, action, detail)

    # 失效缓存，下次请求重新加载
    invalidate_cache()

    return IPWhitelistResponse(
        whitelist=whitelist_text,
        enabled=len(whitelist_text) > 0,
        valid_lines=len(networks),
        invalid_lines=[],
        operator_ip=client_ip,
        operator_ip_in_list=(
            is_loopback
            or not networks
            or is_ip_in_networks(client_ip, networks)
        ),
    )


@router.get("/security/my-ip", response_model=MyIPResponse)
async def get_my_ip(
    http_request: Request,
    current_user = Depends(require_super_admin),
):
    """返回当前请求解析出的客户端 IP 及来源（仅 super_admin）"""
    from src.utils.ip_whitelist import get_client_ip_with_source

    client_ip, source = get_client_ip_with_source(http_request)
    return MyIPResponse(ip=client_ip, source=source)


@router.post("/security/preview", response_model=IPPreviewResponse)
async def preview_ip(
    request: IPPreviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_super_admin),
):
    """预演指定 IP 在当前白名单下是否允许访问（仅 super_admin）"""
    import ipaddress as _ipaddress
    from src.utils.ip_whitelist import get_cached_whitelist, is_ip_in_networks

    ip = request.ip.strip()
    try:
        _ipaddress.ip_address(ip)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"非法 IP 地址：{ip}")

    networks = await get_cached_whitelist(db)

    if ip in ("127.0.0.1", "::1"):
        return IPPreviewResponse(ip=ip, allowed=True, reason="回环地址默认放行")
    if not networks:
        return IPPreviewResponse(ip=ip, allowed=True, reason="白名单为空，当前放行所有 IP")
    if is_ip_in_networks(ip, networks):
        return IPPreviewResponse(ip=ip, allowed=True, reason="命中白名单网段")
    return IPPreviewResponse(ip=ip, allowed=False, reason="不在白名单任何网段内")

