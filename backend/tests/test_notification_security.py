"""通知渠道配置安全加固测试（阶段 2）

覆盖：
- 加密落库（enc: 前缀，与 SSO/LDAC 一致）
- GET 只回 has_xxx + 尾 8 字符（不回密钥原文）
- 留空不修改（PUT 空串保留库中旧值）
- webhook 校验（https 强制 + 域名白名单，422）
- test 接口限频（429）
- 审计（notification_update / notification_test 写 audit_logs）
- 测试发送结果落 alert_notifications（mock 发送，不向真实地址发消息）
- 渠道开关过滤（is_channel_enabled）
- SMTP 加密方式（none/starttls/ssl）
"""
import json
import pytest
from sqlalchemy import select

from src.models import Setting, User
from src.models.alert import AlertNotification
from src.services.permission_service import pwd_context
from src.utils.crypto import encrypt_password, decrypt_password
from src.utils.notification_store import (
    NOTIFICATION_SETTINGS_KEY,
    SECRET_ENC_PREFIX,
    load_stored_config,
    save_stored_config,
    encrypt_config,
    decrypt_config,
    mask_config_for_display,
    get_notification_config,
    is_channel_enabled,
    validate_webhook_url,
    get_allowed_webhook_hosts,
)
import src.api.settings as settings_module


async def _login(client, username: str = "admin", password: str = "admin123") -> dict:
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _make_user(db_session, username: str, email: str, role_name: str, password: str = "Passw0rd!"):
    from src.models import Role
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    user = User(
        username=username,
        display_name=username,
        email=email,
        hashed_password=pwd_context.hash(password),
        role_id=role.id,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    """每个用例前后清空进程内限频状态，避免用例间串扰。"""
    settings_module._notification_test_last.clear()
    yield
    settings_module._notification_test_last.clear()


# ==================== notification_store 单元 ====================

class TestNotificationStore:
    def test_validate_webhook_rejects_http(self):
        """非 https 一律拒绝。"""
        with pytest.raises(ValueError, match="https"):
            validate_webhook_url("http://oapi.dingtalk.com/robot/send?access_token=x", "钉钉")

    def test_validate_webhook_rejects_non_whitelist_host(self):
        """非白名单域名拒绝（SSRF 防护）。"""
        with pytest.raises(ValueError, match="白名单"):
            validate_webhook_url("https://192.168.1.10/robot/send", "钉钉")
        with pytest.raises(ValueError, match="白名单"):
            validate_webhook_url("https://evil.example.com/hook", "飞书")

    def test_validate_webhook_accepts_whitelist(self):
        url = "https://oapi.dingtalk.com/robot/send?access_token=abc"
        assert validate_webhook_url(url, "钉钉") == url

    def test_validate_webhook_empty_ok(self):
        """空串合法（表示未配置/留空不修改）。"""
        assert validate_webhook_url("", "钉钉") == ""

    def test_allowed_hosts_env_extension(self, monkeypatch):
        monkeypatch.setenv("NOTIFICATION_WEBHOOK_ALLOWED_HOSTS", "hook.corp.example.com")
        assert "hook.corp.example.com" in get_allowed_webhook_hosts()
        assert "oapi.dingtalk.com" in get_allowed_webhook_hosts()

    def test_encrypt_config_idempotent(self):
        cfg = {"dingtalk_webhook_url": "https://oapi.dingtalk.com/a", "smtp_password": "pwd123"}
        once = encrypt_config(cfg)
        assert once["smtp_password"].startswith(SECRET_ENC_PREFIX)
        twice = encrypt_config(once)
        assert twice == once

    def test_decrypt_roundtrip(self):
        cfg = {"smtp_password": "pwd123", "dingtalk_webhook_url": "https://oapi.dingtalk.com/a"}
        assert decrypt_config(encrypt_config(cfg))["smtp_password"] == "pwd123"

    def test_mask_only_has_and_tail(self):
        plain = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcdefgh12345678"
        masked = mask_config_for_display({"wechat_webhook_url": SECRET_ENC_PREFIX + encrypt_password(plain)})
        assert masked["has_wechat_webhook_url"] is True
        assert masked["wechat_webhook_url_tail"] == plain[-8:]
        assert plain not in json.dumps(masked)
        assert "enc:" not in json.dumps(masked)

    def test_is_channel_enabled_default_true(self):
        assert is_channel_enabled({}, "dingtalk") is True
        assert is_channel_enabled({"channel_enabled": {"feishu": False}}, "feishu") is False


# ==================== GET 脱敏 ====================

@pytest.mark.asyncio
async def test_get_notification_masks_secrets(client, db_session):
    """GET 只回 has_xxx + 尾 8 字符，响应中无密钥原文。"""
    headers = await _login(client)
    secret = "https://oapi.dingtalk.com/robot/send?access_token=tok12345678"
    await save_stored_config(db_session, {
        "dingtalk_webhook_url": secret,
        "wechat_webhook_url": "",
        "feishu_webhook_url": "",
        "smtp_password": "SuperSecret99",
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_username": "ops@example.com",
        "smtp_from_email": "ops@example.com",
        "smtp_security": "starttls",
    })

    resp = await client.get("/api/v1/settings/notification", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["has_dingtalk_webhook_url"] is True
    assert data["dingtalk_webhook_url_tail"] == secret[-8:]
    assert data["has_smtp_password"] is True
    assert data["smtp_password_tail"] == "Secret99"
    assert secret not in resp.text
    assert "SuperSecret99" not in resp.text
    assert "dingtalk_webhook_url" not in data  # 不再回原文键名
    assert data["smtp_host"] == "smtp.example.com"


@pytest.mark.asyncio
async def test_get_notification_no_config_falls_back_env(client, monkeypatch):
    """无库配置时回落环境变量，仍只回 has_xxx 形态。"""
    headers = await _login(client)
    monkeypatch.setattr(
        type(settings_module.app_config.notification), "dingtalk_webhook_url",
        "https://oapi.dingtalk.com/x?access_token=envtail99", raising=False,
    )
    resp = await client.get("/api/v1/settings/notification", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    # 环境变量可能有值（来自 backend/.env），但绝不能回原文
    assert "https://" not in json.dumps(data)


# ==================== PUT：加密 + 留空不修改 ====================

@pytest.mark.asyncio
async def test_put_encrypts_and_keeps_old_when_blank(client, db_session):
    """PUT 后密钥字段 enc: 前缀加密落库；再 PUT 空串不覆盖旧值。"""
    headers = await _login(client)
    payload = {
        "dingtalk_webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=aaa",
        "smtp_host": "smtp.example.com",
        "smtp_port": 465,
        "smtp_username": "ops@example.com",
        "smtp_password": "MailPwd#2024",
        "smtp_from_email": "ops@example.com",
        "smtp_security": "ssl",
    }
    resp = await client.put("/api/v1/settings/notification", json=payload, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["smtp_security"] == "ssl"

    stored = await load_stored_config(db_session)
    assert stored["smtp_password"].startswith(SECRET_ENC_PREFIX)
    assert stored["dingtalk_webhook_url"].startswith(SECRET_ENC_PREFIX)
    assert decrypt_password(stored["smtp_password"][len(SECRET_ENC_PREFIX):]) == "MailPwd#2024"
    assert "MailPwd#2024" not in stored["smtp_password"]
    assert stored["smtp_security"] == "ssl"

    # 留空不修改：只改明文 host，密钥留空
    resp2 = await client.put("/api/v1/settings/notification", json={
        "smtp_host": "smtp2.example.com",
        "dingtalk_webhook_url": "",
        "wechat_webhook_url": "",
        "feishu_webhook_url": "",
        "smtp_password": "",
    }, headers=headers)
    assert resp2.status_code == 200
    stored2 = await load_stored_config(db_session)
    assert stored2["smtp_host"] == "smtp2.example.com"
    assert stored2["smtp_password"] == stored["smtp_password"]  # 密文原样保留
    assert stored2["dingtalk_webhook_url"] == stored["dingtalk_webhook_url"]


@pytest.mark.asyncio
async def test_put_rejects_http_webhook(client):
    """http webhook 拒绝 422。"""
    headers = await _login(client)
    resp = await client.put("/api/v1/settings/notification", json={
        "dingtalk_webhook_url": "http://oapi.dingtalk.com/robot/send?access_token=x",
    }, headers=headers)
    assert resp.status_code == 422
    assert "https" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_put_rejects_non_whitelist_host(client):
    """内网/陌生域名 webhook 拒绝 422（SSRF 防护）。"""
    headers = await _login(client)
    resp = await client.put("/api/v1/settings/notification", json={
        "feishu_webhook_url": "https://10.0.0.5/hook",
    }, headers=headers)
    assert resp.status_code == 422
    assert "白名单" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_put_rejects_bad_smtp_security(client):
    """smtp_security 非法值拒绝 422。"""
    headers = await _login(client)
    resp = await client.put("/api/v1/settings/notification", json={
        "smtp_security": "tls-wtf",
    }, headers=headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_writes_audit_log(client, db_session):
    """PUT 写 notification_update 审计且 detail 不含密钥内容。"""
    headers = await _login(client)
    await client.put("/api/v1/settings/notification", json={
        "wechat_webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=k12345678",
        "smtp_password": "AuditPwd123",
    }, headers=headers)

    rows = (await db_session.execute(
        select(Setting).where(Setting.key == "notification_settings")
    )).scalars().all()
    assert rows
    from src.models import AuditLog
    audits = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "notification_update")
        .order_by(AuditLog.id.desc()).limit(1)
    )).scalars().first()
    assert audits is not None
    assert "AuditPwd123" not in (audits.detail or "")
    assert "qyapi.weixin.qq.com" not in (audits.detail or "")


# ==================== test 接口：mock 发送 ====================

@pytest.fixture
def mock_dingtalk_send(monkeypatch):
    """mock 钉钉发送（不向真实地址发消息），记录调用。"""
    calls = []

    async def fake_send(webhook_url: str, message: str):
        calls.append((webhook_url, message))

    monkeypatch.setattr(
        settings_module.AlertService, "_send_dingtalk_notification",
        staticmethod(fake_send),
    )
    return calls


@pytest.mark.asyncio
async def test_test_notification_success_and_persist(client, db_session, mock_dingtalk_send):
    """测试发送成功：mock 调用 + 结果落 alert_notifications + 审计。"""
    headers = await _login(client)
    url = "https://oapi.dingtalk.com/robot/send?access_token=mocktok12345"
    await save_stored_config(db_session, {
        "dingtalk_webhook_url": url, "smtp_host": "", "smtp_port": 25,
    })

    resp = await client.post("/api/v1/settings/notification/test",
                             json={"channel": "dingtalk"}, headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["success"] is True
    assert data["status"] == "sent"
    assert mock_dingtalk_send and mock_dingtalk_send[0][0] == url

    # mock 不会真的收到原文外发 —— 发送结果落库验证
    notif = (await db_session.execute(
        select(AlertNotification).where(AlertNotification.channel == "dingtalk(test)")
        .order_by(AlertNotification.id.desc()).limit(1)
    )).scalars().first()
    assert notif is not None and notif.status == "sent"

    from src.models import AuditLog
    audit = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "notification_test")
        .order_by(AuditLog.id.desc()).limit(1)
    )).scalars().first()
    assert audit is not None and "成功" in audit.detail


@pytest.mark.asyncio
async def test_test_notification_rate_limited(client, db_session, mock_dingtalk_send):
    """同渠道限频窗口内第二次请求 429。"""
    headers = await _login(client)
    await save_stored_config(db_session, {"dingtalk_webhook_url": "https://oapi.dingtalk.com/x?access_token=t"})
    assert (await client.post("/api/v1/settings/notification/test",
                              json={"channel": "dingtalk"}, headers=headers)).status_code == 200
    resp2 = await client.post("/api/v1/settings/notification/test",
                              json={"channel": "dingtalk"}, headers=headers)
    assert resp2.status_code == 429


@pytest.mark.asyncio
async def test_test_notification_stored_dirty_webhook_rejected(client, db_session):
    """存量脏数据（非白名单域名）发送前被第二重校验拦截 422。"""
    headers = await _login(client)
    await save_stored_config(db_session, {"dingtalk_webhook_url": "https://10.0.0.9/hook"})
    resp = await client.post("/api/v1/settings/notification/test",
                             json={"channel": "dingtalk"}, headers=headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_test_notification_not_configured_400(client, db_session):
    """未配置渠道测试发送 400。"""
    headers = await _login(client)
    resp = await client.post("/api/v1/settings/notification/test",
                             json={"channel": "wechat"}, headers=headers)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_test_notification_send_failure_persisted(client, db_session, monkeypatch):
    """发送抛异常：status=failed 落库 + error_message 记录。"""
    async def boom(webhook_url, message):
        raise RuntimeError("connection refused")
    monkeypatch.setattr(
        settings_module.AlertService, "_send_dingtalk_notification",
        staticmethod(boom),
    )
    headers = await _login(client)
    await save_stored_config(db_session, {"dingtalk_webhook_url": "https://oapi.dingtalk.com/x?access_token=t2"})
    resp = await client.post("/api/v1/settings/notification/test",
                             json={"channel": "dingtalk"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["success"] is False
    notif = (await db_session.execute(
        select(AlertNotification).where(AlertNotification.channel == "dingtalk(test)")
        .order_by(AlertNotification.id.desc()).limit(1)
    )).scalars().first()
    assert notif.status == "failed"
    assert "connection refused" in notif.error_message


# ==================== 渠道开关过滤 ====================

@pytest.mark.asyncio
async def test_send_notifications_respects_channel_switch(client, db_session, monkeypatch):
    """告警发送按 channel_enabled 过滤：关闭的渠道不发送。"""
    from src.services.alert_service import AlertService

    await save_stored_config(db_session, {
        "dingtalk_webhook_url": "https://oapi.dingtalk.com/x?access_token=switch",
        "channel_enabled": {"dingtalk": False},
    })

    sent = []

    async def fake_dingtalk(webhook_url, message):
        sent.append(webhook_url)

    monkeypatch.setattr(AlertService, "_send_dingtalk_notification", staticmethod(fake_dingtalk))

    config = await get_notification_config(db_session)
    from src.utils.notification_store import is_channel_enabled as ice
    # 开关关闭：即使 webhook 已配置也不应发送
    assert ice(config, "dingtalk") is False
    assert sent == []

    # 开启后正常
    await save_stored_config(db_session, {
        "dingtalk_webhook_url": "https://oapi.dingtalk.com/x?access_token=switch",
        "channel_enabled": {"dingtalk": True},
    })
    config2 = await get_notification_config(db_session)
    assert ice(config2, "dingtalk") is True


@pytest.mark.asyncio
async def test_backup_failure_notification_persists(client, db_session, monkeypatch):
    """备份失败通知：mock 发送 + 按开关过滤 + 结果落库 channel=backup:<id>:<channel>。"""
    from src.services.alert_service import AlertService

    calls = []

    async def fake_wechat(webhook_url, message):
        calls.append(("wechat", webhook_url))

    async def fake_dingtalk(webhook_url, message):
        calls.append(("dingtalk", webhook_url))

    async def fake_feishu(webhook_url, message):
        calls.append(("feishu", webhook_url))

    monkeypatch.setattr(AlertService, "_send_wechat_notification", staticmethod(fake_wechat))
    monkeypatch.setattr(AlertService, "_send_dingtalk_notification", staticmethod(fake_dingtalk))
    monkeypatch.setattr(AlertService, "_send_feishu_notification", staticmethod(fake_feishu))

    await save_stored_config(db_session, {
        "wechat_webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=bk12345678",
        "dingtalk_webhook_url": "https://oapi.dingtalk.com/x?access_token=bk",
        "channel_enabled": {"dingtalk": False},  # 关闭钉钉，应只有企微发送
    })

    await AlertService.send_backup_failure_notification(db_session, 999, "临时验证任务", "mock 失败")

    assert ("wechat", "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=bk12345678") in calls
    assert all(ch != "dingtalk" for ch, _ in calls)  # 被开关过滤

    rows = (await db_session.execute(
        select(AlertNotification).where(AlertNotification.channel == "backup:999:wechat")
    )).scalars().all()
    assert rows and rows[0].status == "sent"
    ding_rows = (await db_session.execute(
        select(AlertNotification).where(AlertNotification.channel == "backup:999:dingtalk")
    )).scalars().all()
    assert not ding_rows  # 关闭渠道不产生通知记录


@pytest.mark.asyncio
async def test_smtp_security_none_skips_starttls(monkeypatch):
    """smtp_security=none 时不执行 starttls；ssl 时用 SMTP_SSL。"""
    import src.services.alert_service as svc
    from src.services.alert_service import AlertService

    recorded = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            recorded["host"], recorded["port"] = host, port
        def starttls(self):
            recorded["starttls"] = True
        def login(self, u, p):
            recorded["login"] = True
        def sendmail(self, *a, **k):
            recorded["sent"] = True
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    class FakeSMTPSSL(FakeSMTP):
        pass

    import smtplib
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTPSSL)

    cfg = {"smtp_host": "smtp.example.com", "smtp_port": 25,
           "smtp_username": "u", "smtp_password": "p",
           "smtp_from_email": "f@example.com", "smtp_security": "none"}
    server = AlertService._smtp_connect(cfg)
    assert isinstance(server, FakeSMTP)

    cfg_ssl = {**cfg, "smtp_security": "ssl", "smtp_port": 465}
    server_ssl = AlertService._smtp_connect(cfg_ssl)
    assert isinstance(server_ssl, FakeSMTPSSL)

    cfg_tls = {**cfg, "smtp_security": "starttls", "smtp_port": 587}
    server_tls = AlertService._smtp_connect(cfg_tls)
    server_tls.starttls()
    assert recorded.get("starttls") is True


# ==================== 非超管权限 ====================

@pytest.mark.asyncio
async def test_non_super_admin_forbidden(client, db_session):
    """engineer 访问通知配置读写均 403。"""
    await _make_user(db_session, "eng_ntf", "eng_ntf@example.com", "engineer")
    headers = await _login(client, "eng_ntf", "Passw0rd!")
    assert (await client.get("/api/v1/settings/notification", headers=headers)).status_code == 403
    assert (await client.put("/api/v1/settings/notification", json={}, headers=headers)).status_code == 403
    assert (await client.post("/api/v1/settings/notification/test",
                              json={"channel": "email"}, headers=headers)).status_code == 403
