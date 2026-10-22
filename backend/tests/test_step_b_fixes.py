"""步骤 B 功能缺陷修复回归测试。

覆盖:
1. login_methods 白名单校验（非法值 400、缺 local 400、合法值规范化保存）
2. redirect_url 强制 https（http 400）；可选域名白名单（未配置不拦截、配置后拦截/放行）
3. 单会话吊销 DELETE /users/{uid}/sessions/{sid}（吊销后 token 失效）
4. PATCH toggle 真实生效（含最后超管保护）
5. SSO 建用户默认 viewer 角色（不创建孤立 "user" 角色、email 兜底不炸）
"""
import json
import uuid

import pytest
from sqlalchemy import select

from src.models import User, Role, UserSession, SystemConfig  # noqa: F401
from src.services.sso_service import sso_service

pytestmark = pytest.mark.asyncio


async def login(client, username="admin", password="admin123") -> dict:
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def create_normal_user(client, admin_auth, username="bobby", password="Passw0rd123"):
    resp = await client.post(
        "/api/v1/users",
        json={"username": username, "email": f"{username}@test.com", "password": password},
        headers=admin_auth,
    )
    assert resp.status_code == 201, resp.text
    user = resp.json()
    user_auth = await login(client, username, password)
    return user["id"], user_auth


def _sso_payload(**overrides):
    base = {
        "enabled": False,
        "client_id": "cid",
        "client_secret": "",
        "authorize_url": "https://sso.example.com/auth",
        "token_url": "https://sso.example.com/token",
        "userinfo_url": "https://sso.example.com/ui",
        "redirect_url": "https://app.example.com/cb",
        "login_methods": "local,oauth2",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. login_methods 白名单
# ---------------------------------------------------------------------------

async def test_login_methods_rejects_invalid_value(client):
    auth = await login(client)
    resp = await client.post(
        "/api/v1/system/sso-config", json=_sso_payload(login_methods="local,windows1998"),
        headers=auth,
    )
    assert resp.status_code == 400
    assert "windows1998" in resp.json()["detail"]


async def test_login_methods_requires_local(client):
    auth = await login(client)
    resp = await client.post(
        "/api/v1/system/sso-config", json=_sso_payload(login_methods="oauth2,saml"),
        headers=auth,
    )
    assert resp.status_code == 400
    assert "local" in resp.json()["detail"]


async def test_login_methods_valid_value_normalized(client, db_session):
    auth = await login(client)
    resp = await client.post(
        "/api/v1/system/sso-config",
        json=_sso_payload(login_methods=" local , OAUTH2 , oauth2 "),
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    # 库中应规范化为 local,oauth2（value 列为 JSON 字符串）
    row = await db_session.execute(
        select(SystemConfig).where(SystemConfig.key == "sso_config")
    )
    cfg = row.scalar_one()
    stored = json.loads(cfg.value) if isinstance(cfg.value, str) else cfg.value
    assert stored["login_methods"] == "local,oauth2"
    await client.delete("/api/v1/system/sso-config", headers=auth)


# ---------------------------------------------------------------------------
# 2. redirect_url https + 可选白名单
# ---------------------------------------------------------------------------

async def test_redirect_url_rejects_http(client):
    auth = await login(client)
    resp = await client.post(
        "/api/v1/system/sso-config",
        json=_sso_payload(redirect_url="http://app.example.com/cb"),
        headers=auth,
    )
    assert resp.status_code == 400
    assert "https" in resp.json()["detail"]


async def test_redirect_url_without_whitelist_passes_https(client):
    """未配置白名单 → 只要求 https，不拦截（避免打挂现有配置）。"""
    auth = await login(client)
    resp = await client.post(
        "/api/v1/system/sso-config",
        json=_sso_payload(redirect_url="https://anything-else.example.org/cb"),
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    await client.delete("/api/v1/system/sso-config", headers=auth)


async def test_redirect_url_with_whitelist_enforced(client):
    auth = await login(client)
    # 域名不在白名单 → 400
    resp = await client.post(
        "/api/v1/system/sso-config",
        json=_sso_payload(
            redirect_url="https://evil.example.net/cb",
            allowed_redirect_hosts="app.example.com, sso.corp.com",
        ),
        headers=auth,
    )
    assert resp.status_code == 400
    assert "白名单" in resp.json()["detail"]
    # 域名在白名单 → 200
    resp = await client.post(
        "/api/v1/system/sso-config",
        json=_sso_payload(
            redirect_url="https://sso.corp.com/cb",
            allowed_redirect_hosts="app.example.com, sso.corp.com",
        ),
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    await client.delete("/api/v1/system/sso-config", headers=auth)


# ---------------------------------------------------------------------------
# 3. 单会话吊销
# ---------------------------------------------------------------------------

async def test_revoke_single_session(client, db_session):
    admin_auth = await login(client)
    uid, user_auth = await create_normal_user(client, admin_auth)

    # 拿普通用户的会话列表 → 找到其 session id
    resp = await client.get(f"/api/v1/users/{uid}/sessions", headers=admin_auth)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"] if isinstance(resp.json(), dict) else resp.json()
    target = next(s for s in items if not s.get("is_current"))
    assert target["is_revoked"] is False

    # 吊销
    resp = await client.delete(
        f"/api/v1/users/{uid}/sessions/{target['id']}", headers=admin_auth
    )
    assert resp.status_code == 200, resp.text

    # 该 token 立即失效
    resp = await client.get("/api/v1/users/me", headers=user_auth)
    assert resp.status_code == 401

    # 重复吊销 → 400
    resp = await client.delete(
        f"/api/v1/users/{uid}/sessions/{target['id']}", headers=admin_auth
    )
    assert resp.status_code == 400

    # 不存在 → 404
    resp = await client.delete(f"/api/v1/users/{uid}/sessions/999999", headers=admin_auth)
    assert resp.status_code == 404

    # 普通用户不能吊销他人会话
    resp = await client.delete(f"/api/v1/users/{uid}/sessions/1", headers=user_auth)
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# 4. PATCH toggle 真实生效
# ---------------------------------------------------------------------------

async def test_patch_toggle_works_and_protects_last_superuser(client):
    admin_auth = await login(client)
    uid, _ = await create_normal_user(client, admin_auth)

    resp = await client.patch(f"/api/v1/users/{uid}/toggle", headers=admin_auth)
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_active"] is False

    resp = await client.patch(f"/api/v1/users/{uid}/toggle", headers=admin_auth)
    assert resp.json()["is_active"] is True

    # 对最后一个启用超管 toggle → 400（/users 列表返回 list）
    resp = await client.get("/api/v1/users/", headers=admin_auth)
    users = resp.json() if isinstance(resp.json(), list) else resp.json().get("items", [])
    admin_id = next(u["id"] for u in users if u.get("username") == "admin")
    resp = await client.patch(f"/api/v1/users/{admin_id}/toggle", headers=admin_auth)
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 5. SSO 建用户：默认 viewer、email 兜底
# ---------------------------------------------------------------------------

async def test_sso_create_user_defaults_viewer_and_email(client, db_session):
    suffix = uuid.uuid4().hex[:8]
    userinfo = {"preferred_username": f"ssouser_{suffix}"}  # 无 email、无 name
    user = await sso_service.create_or_update_user(db_session, userinfo)

    assert user.id is not None
    assert user.email  # 非 None（占位域兜底）
    assert user.email.endswith("@sso.placeholder")
    # 角色必须是内置 viewer，且未创建孤立 "user" 角色
    role = (await db_session.execute(
        select(Role).where(Role.id == user.role_id)
    )).scalar_one()
    assert role.name == "viewer"
    assert role.is_builtin is True
    orphan = (await db_session.execute(
        select(Role).where(Role.name == "user")
    )).scalar_one_or_none()
    assert orphan is None

    # 清理临时用户
    await db_session.delete(user)
    await db_session.commit()
