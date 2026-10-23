"""IP 白名单安全加固测试。

覆盖：行级校验（非法行返回行号）、防自锁（拒绝保存不含操作者 IP 的名单，
force 二次确认）、超管权限 403、审计落库、my-ip/preview 接口、
XFF 可信代理机制、应急开关、放行路径不被白名单拦截。

注意：httpx ASGITransport 默认 client host 为 testclient（非回环字面量），
get_direct_ip 在 request.client 缺失时回落 127.0.0.1，且回环默认放行，
因此白名单中间件不会在测试中拦截请求本身。
"""
import json
import os
from unittest.mock import patch

import pytest

from src.models.audit_log import AuditLog
from src.models.setting import Setting
from src.utils import ip_whitelist


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def login(client) -> str:
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": "admin", "password": "admin123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture
def clean_whitelist_cache():
    """每个用例前后清空白名单缓存，避免跨用例污染。"""
    ip_whitelist.invalidate_cache()
    yield
    ip_whitelist.invalidate_cache()


@pytest.fixture(autouse=True)
def clear_trusted_proxies_env(monkeypatch):
    """默认无可信代理，避免本机环境变量泄漏影响用例。"""
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)
    monkeypatch.delenv(ip_whitelist.IP_WHITELIST_DISABLED_ENV, raising=False)


# ============ 纯函数单测 ============


def test_get_client_ip_untrusted_xff_ignored():
    """直连 IP 非可信代理时，伪造 XFF/X-Real-IP 不被采信。"""

    class FakeClient:
        host = "203.0.113.10"

    class FakeRequest:
        client = FakeClient()
        headers = {
            "X-Forwarded-For": "127.0.0.1",
            "X-Real-IP": "10.0.0.1",
        }

    ip, source = ip_whitelist.get_client_ip_with_source(FakeRequest())
    assert ip == "203.0.113.10"
    assert source == "direct"


def test_get_client_ip_trusted_proxy_honors_xff(monkeypatch):
    """直连 IP 命中可信代理时，采信 XFF 第一个值。"""
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.0/8,172.16.0.0/12")

    class FakeClient:
        host = "10.0.0.2"

    class FakeRequest:
        client = FakeClient()
        headers = {"X-Forwarded-For": "198.51.100.7, 10.0.0.2"}

    ip, source = ip_whitelist.get_client_ip_with_source(FakeRequest())
    assert ip == "198.51.100.7"
    assert source == "x-forwarded-for"


def test_get_client_ip_no_proxy_configured():
    """未配置 TRUSTED_PROXIES 时一律用直连 IP（即使带 XFF）。"""

    class FakeClient:
        host = "172.16.0.5"

    class FakeRequest:
        client = FakeClient()
        headers = {"X-Forwarded-For": "1.2.3.4"}

    ip, source = ip_whitelist.get_client_ip_with_source(FakeRequest())
    assert ip == "172.16.0.5"
    assert source == "direct"


def test_parse_whitelist_lines_reports_line_numbers():
    """行级解析：非法行返回行号，注释/空行跳过，IPv6 支持。"""
    text = "\n".join([
        "192.168.1.0/24",   # 1 合法
        "",                 # 2 空行跳过
        "# comment",        # 3 注释跳过
        "10.0.0.1/33",      # 4 非法（前缀越界）
        "fd00::/8",         # 5 合法 IPv6
        "not-an-ip",        # 6 非法
        " 10.0.0.1 /8 ",    # 7 非法（行内空格）
    ])
    networks, invalid = ip_whitelist.parse_whitelist_lines(text)
    assert invalid == [4, 6, 7]
    assert len(networks) == 2


def test_is_whitelist_disabled_env(monkeypatch):
    """应急开关：环境变量 true/1/yes 时禁用。"""
    monkeypatch.setenv(ip_whitelist.IP_WHITELIST_DISABLED_ENV, "true")
    assert ip_whitelist.is_whitelist_disabled() is True
    monkeypatch.setenv(ip_whitelist.IP_WHITELIST_DISABLED_ENV, "0")
    assert ip_whitelist.is_whitelist_disabled() is False
    monkeypatch.delenv(ip_whitelist.IP_WHITELIST_DISABLED_ENV)
    assert ip_whitelist.is_whitelist_disabled() is False


# ============ 接口测试 ============


@pytest.mark.asyncio
async def test_save_rejects_invalid_lines_with_line_numbers(client):
    """非法行保存应 422 并返回具体行号。"""
    token = await login(client)
    resp = await client.put(
        "/api/v1/settings/security/ip-whitelist",
        json={"whitelist": "192.168.1.0/24\nbad-line\nanother-bad"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "IP_WHITELIST_INVALID_LINES"
    assert detail["invalid_lines"] == [2, 3]
    # 不应写入数据库
    assert await _db_whitelist_is_none(client)


async def _db_whitelist_is_none(client) -> bool:
    token_resp = await client.post(
        "/api/v1/auth/token",
        data={"username": "admin", "password": "admin123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = token_resp.json()["access_token"]
    resp = await client.get(
        "/api/v1/settings/security/ip-whitelist", headers=auth_headers(token)
    )
    return resp.json()["whitelist"] == ""


@pytest.mark.asyncio
async def test_save_without_operator_ip_rejected_then_force_saved(client):
    """名单不含操作者 IP：首次 409 结构化错误码，force=true 二次确认后保存成功。"""
    from httpx import ASGITransport, AsyncClient
    from src.main import app

    # 用非回环直连 IP 的客户端模拟外部管理员（回环豁免防自锁，无法走此路径）
    foreign_transport = ASGITransport(app=app, client=("10.50.0.1", 12345))
    async with AsyncClient(transport=foreign_transport, base_url="http://test") as fc:
        # 白名单保存接口在 public_paths（自救设计），外来 IP 也能到达该端点（仍有 JWT+超管鉴权）
        token = await login(fc)

        # 首次：无 force → 409 + IP_WHITELIST_LOCKOUT
        resp = await fc.put(
            "/api/v1/settings/security/ip-whitelist",
            json={"whitelist": "10.99.0.0/16"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 409, resp.text
        detail = resp.json()["detail"]
        assert detail["code"] == "IP_WHITELIST_LOCKOUT"
        assert detail["operator_ip"] == "10.50.0.1"

        # force=true → 保存成功
        resp = await fc.put(
            "/api/v1/settings/security/ip-whitelist",
            json={"whitelist": "10.99.0.0/16", "force": True},
            headers=auth_headers(token),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["enabled"] is True
        assert body["valid_lines"] == 1
        assert body["operator_ip_in_list"] is False

        # 清理：恢复为空（测试数据用完即删）
        resp = await fc.put(
            "/api/v1/settings/security/ip-whitelist",
            json={"whitelist": ""},
            headers=auth_headers(token),
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_save_with_operator_loopback_allowed(client):
    """回环操作者（测试 client 默认 127.0.0.1）保存任意名单不触发防自锁。"""
    token = await login(client)
    resp = await client.put(
        "/api/v1/settings/security/ip-whitelist",
        json={"whitelist": "10.88.0.0/16\n192.168.5.0/24"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["valid_lines"] == 2
    assert body["operator_ip_in_list"] is True  # 回环默认放行视为在内

    # 清理
    await client.put(
        "/api/v1/settings/security/ip-whitelist",
        json={"whitelist": ""},
        headers=auth_headers(token),
    )


@pytest.mark.asyncio
async def test_whitelist_requires_super_admin(client, db_session):
    """非超管用户访问白名单接口应 403。"""
    from src.models.user import User
    from src.utils.security import get_password_hash

    # 造一个非超管用户
    user = User(
        username="plainuser",
        email="plainuser@test.local",
        hashed_password=get_password_hash("Passw0rd!"),
        is_active=True,
        is_superuser=False,
    )
    db_session.add(user)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": "plainuser", "password": "Passw0rd!"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    user_token = resp.json()["access_token"]

    for method, path, kwargs in [
        ("get", "/api/v1/settings/security/ip-whitelist", {}),
        ("put", "/api/v1/settings/security/ip-whitelist", {"json": {"whitelist": "10.0.0.0/8"}}),
        ("get", "/api/v1/settings/security/my-ip", {}),
        ("post", "/api/v1/settings/security/preview", {"json": {"ip": "1.2.3.4"}}),
    ]:
        resp = await getattr(client, method)(path, headers=auth_headers(user_token), **kwargs)
        assert resp.status_code == 403, f"{path} 应拒绝非超管: {resp.status_code}"

    # 清理测试用户
    await db_session.delete(user)
    await db_session.commit()


@pytest.mark.asyncio
async def test_audit_log_written_on_save(client, db_session):
    """保存白名单应写 audit_logs（操作人 + 来源 IP + 动作）。"""
    token = await login(client)

    # 统计已有记录
    existing = (await db_session.execute(
        AuditLog.__table__.select().where(AuditLog.resource == "system_settings")
    )).fetchall()
    before = len(existing)

    resp = await client.put(
        "/api/v1/settings/security/ip-whitelist",
        json={"whitelist": "10.77.0.0/16"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200

    rows = (await db_session.execute(
        AuditLog.__table__.select()
        .where(AuditLog.resource == "system_settings")
        .order_by(AuditLog.id.desc())
    )).fetchall()
    assert len(rows) == before + 1
    latest = rows[0]
    # 首次保存为 create 动作（测试库从零开始）
    assert latest.action in ("ip_whitelist_create", "ip_whitelist_update")
    assert latest.user == "admin"
    assert latest.success == "true"
    assert "1 个网段" in (latest.detail or "")

    # 清理：删测试审计记录 + 还原白名单为空
    await db_session.execute(
        AuditLog.__table__.delete().where(AuditLog.id == latest.id)
    )
    await db_session.commit()
    await client.put(
        "/api/v1/settings/security/ip-whitelist",
        json={"whitelist": ""},
        headers=auth_headers(token),
    )


@pytest.mark.asyncio
async def test_my_ip_endpoint(client):
    """my-ip 接口返回 IP 与来源。"""
    token = await login(client)
    resp = await client.get("/api/v1/settings/security/my-ip", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ip"]
    assert body["source"] in ("direct", "x-forwarded-for", "x-real-ip")


@pytest.mark.asyncio
async def test_preview_endpoint(client):
    """预演接口：名单内允许、名单外拒绝、回环默认放行。"""
    token = await login(client)

    # 先保存名单
    resp = await client.put(
        "/api/v1/settings/security/ip-whitelist",
        json={"whitelist": "10.66.0.0/16"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    # 预演前失效缓存，让 preview 读到新名单
    ip_whitelist.invalidate_cache()

    # 名单内
    resp = await client.post(
        "/api/v1/settings/security/preview",
        json={"ip": "10.66.1.1"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["allowed"] is True
    assert "命中" in body["reason"]

    # 名单外
    resp = await client.post(
        "/api/v1/settings/security/preview",
        json={"ip": "8.8.8.8"},
        headers=auth_headers(token),
    )
    body = resp.json()
    assert body["allowed"] is False

    # 回环
    resp = await client.post(
        "/api/v1/settings/security/preview",
        json={"ip": "127.0.0.1"},
        headers=auth_headers(token),
    )
    body = resp.json()
    assert body["allowed"] is True

    # 非法 IP → 422
    resp = await client.post(
        "/api/v1/settings/security/preview",
        json={"ip": "999.1.1.1"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 422

    # 清理
    await client.put(
        "/api/v1/settings/security/ip-whitelist",
        json={"whitelist": ""},
        headers=auth_headers(token),
    )


@pytest.mark.asyncio
async def test_public_paths_not_blocked_by_whitelist(client, db_session):
    """白名单启用后，放行路径（登录链路等）仍可访问。"""
    token = await login(client)
    resp = await client.put(
        "/api/v1/settings/security/ip-whitelist",
        json={"whitelist": "10.55.0.0/16"},  # 不含测试 client 的回环，但回环默认放行
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    ip_whitelist.invalidate_cache()

    # 健康检查与公开品牌接口不受影响
    resp = await client.get("/health")
    assert resp.status_code == 200
    resp = await client.get("/api/v1/settings/public/brand")
    assert resp.status_code == 200

    # 清理
    await client.put(
        "/api/v1/settings/security/ip-whitelist",
        json={"whitelist": ""},
        headers=auth_headers(token),
    )


@pytest.mark.asyncio
async def test_get_whitelist_returns_operator_ip(client):
    """GET 返回操作者 IP 与在名单内标记。"""
    token = await login(client)
    resp = await client.get(
        "/api/v1/settings/security/ip-whitelist", headers=auth_headers(token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["operator_ip"]
    assert body["operator_ip_in_list"] is True  # 名单为空时视为在内
