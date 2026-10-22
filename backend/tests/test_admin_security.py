"""步骤 A 安全加固回归测试。

覆盖:
1. SSO/LDAP 配置 GET 提权（普通用户 403）
2. 配置响应不回显 secret + 留空不修改 + enc: 前缀
3. 内置角色禁删禁改（409 system.roleBuiltin）
4. 使用中角色禁删（409 system.roleInUse）
5. 最后超管保护（reset_password / update_user）
6. update_user 普通用户静默忽略 is_active/role_id
7. 迁移脚本幂等 + 可回滚
"""
import json

import pytest
from sqlalchemy import select

from src.models import SystemConfig, User, Role  # noqa: F401
from src.utils.crypto import encrypt_password
from src.api.system import SECRET_ENC_PREFIX

pytestmark = pytest.mark.asyncio

ADMIN_AUTH = None  # 由 helper 填充


async def login(client, username="admin", password="admin123") -> dict:
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def create_normal_user(client, admin_auth, username="alice", password="Passw0rd123"):
    """创建普通用户并返回 (user_id, 普通用户 auth header)。"""
    resp = await client.post(
        "/api/v1/users",
        json={"username": username, "email": f"{username}@test.com", "password": password},
        headers=admin_auth,
    )
    assert resp.status_code == 201, resp.text
    user = resp.json()
    # 普通用户登录（engineer 角色，非超管）
    user_auth = await login(client, username, password)
    return user["id"], user_auth


# ---------------------------------------------------------------------------
# 1. SSO/LDAP 配置提权与 secret 回显
# ---------------------------------------------------------------------------

async def test_sso_config_forbidden_for_normal_user(client, admin_auth=None):
    """普通用户读 SSO 配置应 403。"""
    admin = await login(client)
    user_id, user_auth = await create_normal_user(client, admin)

    resp = await client.get("/api/v1/system/sso-config", headers=user_auth)
    assert resp.status_code == 403


async def test_sso_config_no_secret_in_response_and_save_encrypted(client, db_session):
    """GET 不回显 client_secret；POST 后库中为 enc: 前缀密文；留空再保存保留原值。"""
    admin = await login(client)

    # 首次保存（带 secret）
    resp = await client.post("/api/v1/system/sso-config", json={
        "enabled": True,
        "client_id": "cid",
        "client_secret": "my-plain-secret",
        "authorize_url": "https://sso.example.com/authorize",
        "token_url": "https://sso.example.com/token",
        "userinfo_url": "https://sso.example.com/userinfo",
        "redirect_url": "https://app.example.com/callback",
        "login_methods": "local,oauth2",
    }, headers=admin)
    assert resp.status_code == 200, resp.text

    # 库中应为 enc: 前缀，且不含明文
    result = await db_session.execute(
        select(SystemConfig).where(SystemConfig.key == "sso_config")
    )
    stored = json.loads(result.scalar_one().value)
    assert stored["client_secret"].startswith(SECRET_ENC_PREFIX)
    assert "my-plain-secret" not in stored["client_secret"]

    # GET 响应不含 secret，只含 has_client_secret
    resp = await client.get("/api/v1/system/sso-config", headers=admin)
    assert resp.status_code == 200
    body = resp.json()
    assert "client_secret" not in body
    assert body["has_client_secret"] is True
    assert body["client_id"] == "cid"

    # 留空再保存 → 原值保留（仍是同一密文）
    resp = await client.post("/api/v1/system/sso-config", json={
        "enabled": True,
        "client_id": "cid-2",
        "client_secret": "",
        "authorize_url": "https://sso.example.com/authorize",
        "token_url": "https://sso.example.com/token",
        "userinfo_url": "https://sso.example.com/userinfo",
        "redirect_url": "https://app.example.com/callback",
        "login_methods": "local,oauth2",
    }, headers=admin)
    assert resp.status_code == 200

    result = await db_session.execute(
        select(SystemConfig).where(SystemConfig.key == "sso_config")
    )
    stored2 = json.loads(result.scalar_one().value)
    assert stored2["client_secret"] == stored["client_secret"]  # 未变
    assert stored2["client_id"] == "cid-2"  # 其他字段已更新


async def test_ldap_config_forbidden_and_no_password_echo(client, db_session):
    """普通用户读/写 LDAP 配置应 403；GET 不回显 bind_password；保存后库中为密文。"""
    admin = await login(client)
    _, user_auth = await create_normal_user(client, admin)

    base_config = {
        "enabled": True,
        "server": "ldap.example.com",
        "port": 389,
        "use_ssl": False,
        "use_starttls": False,
        "verify_cert": True,
        "bind_dn": "cn=admin,dc=x",
        "bind_password": "ldap-secret",
        "base_dn": "dc=x",
        "user_filter": "(objectClass=person)",
        "username_attr": "sAMAccountName",
        "display_attr": "displayName",
        "email_attr": "mail",
        "phone_attr": "mobile",
        "department_attr": "department",
        "group_attr": "memberOf",
        "default_role": "viewer",
    }

    resp = await client.get("/api/v1/auth/ldap/config", headers=user_auth)
    assert resp.status_code == 403

    resp = await client.put("/api/v1/auth/ldap/config", json=base_config, headers=user_auth)
    assert resp.status_code == 403

    resp = await client.post("/api/v1/auth/ldap/test", json=base_config, headers=user_auth)
    assert resp.status_code == 403

    # 超管保存
    resp = await client.put("/api/v1/auth/ldap/config", json=base_config, headers=admin)
    assert resp.status_code == 200, resp.text

    result = await db_session.execute(
        select(SystemConfig).where(SystemConfig.key == "ldap_config")
    )
    stored = json.loads(result.scalar_one().value)
    assert stored["bind_password"].startswith(SECRET_ENC_PREFIX)
    assert "ldap-secret" not in stored["bind_password"]

    # GET 不回显明文
    resp = await client.get("/api/v1/auth/ldap/config", headers=admin)
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("bind_password") in (None, "")
    assert body.get("has_bind_password") is True


# ---------------------------------------------------------------------------
# 2. 内置角色保护 + 使用中角色保护
# ---------------------------------------------------------------------------

async def _get_role_by_name(client, admin_auth, name):
    resp = await client.get("/api/v1/users/roles/", headers=admin_auth)
    assert resp.status_code == 200
    for role in resp.json():
        if role["name"] == name:
            return role
    raise AssertionError(f"role {name} not found")


async def test_builtin_role_delete_and_update_409(client):
    """内置角色删除/修改应 409，code=system.roleBuiltin。"""
    admin = await login(client)
    viewer = await _get_role_by_name(client, admin, "viewer")
    assert viewer["is_builtin"] is True

    resp = await client.delete(f"/api/v1/users/roles/{viewer['id']}", headers=admin)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "system.roleBuiltin"

    # permissions 路由同步保护
    resp = await client.delete(f"/api/v1/permissions/roles/{viewer['id']}", headers=admin)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "system.roleBuiltin"

    # 修改内置角色 display_name 也应 409
    resp = await client.put(f"/api/v1/users/roles/{viewer['id']}",
                            json={"display_name": "改名"}, headers=admin)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "system.roleBuiltin"


async def test_role_in_use_delete_409(client, db_session):
    """有用户使用的角色删除应 409，code=system.roleInUse 且含 count。"""
    admin = await login(client)

    # 新建临时角色并分配给用户（用完即删）
    resp = await client.post("/api/v1/users/roles/", json={
        "name": "temp_in_use", "display_name": "临时角色", "permissions": [],
    }, headers=admin)
    assert resp.status_code == 200, resp.text
    role = resp.json()

    resp = await client.post(
        "/api/v1/users",
        json={"username": "bob", "email": "bob@test.com",
              "password": "Passw0rd123", "role_id": role["id"]},
        headers=admin,
    )
    assert resp.status_code == 201, resp.text
    bob_id = resp.json()["id"]

    resp = await client.delete(f"/api/v1/users/roles/{role['id']}", headers=admin)
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "system.roleInUse"
    assert detail["params"]["count"] >= 1

    # 删除用户后可正常删除角色（204）
    resp = await client.delete(f"/api/v1/users/{bob_id}", headers=admin)
    assert resp.status_code == 204

    resp = await client.delete(f"/api/v1/users/roles/{role['id']}", headers=admin)
    assert resp.status_code == 204


async def test_create_role_forces_not_builtin(client, db_session):
    """API 创建角色强制 is_builtin=False，即使请求伪造 is_builtin=True。"""
    admin = await login(client)
    resp = await client.post("/api/v1/users/roles/", json={
        "name": "evil_builtin",
        "display_name": "伪造内置",
        "is_builtin": True,
        "permissions": [],
    }, headers=admin)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_builtin"] is False

    # 清理临时角色（用完即删）
    resp = await client.delete(f"/api/v1/users/roles/{body['id']}", headers=admin)
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# 3. 最后超管保护
# ---------------------------------------------------------------------------

async def _superuser_count(db_session):
    from sqlalchemy import func
    result = await db_session.execute(
        select(func.count(User.id)).where(User.is_superuser == True, User.is_active == True)  # noqa: E712
    )
    return result.scalar_one()


async def test_reset_password_protects_last_superuser(client, db_session):
    """对最后一个启用超管 reset_password 应 400。"""
    admin = await login(client)
    result = await db_session.execute(select(User).where(User.username == "admin"))
    admin_id = result.scalar_one().id
    assert await _superuser_count(db_session) == 1

    resp = await client.post(f"/api/v1/users/{admin_id}/reset-password", headers=admin)
    assert resp.status_code == 400


async def test_update_user_cannot_demote_last_superuser(client, db_session):
    """把最后一个启用超管的 role_id 改为其他角色应 400。"""
    admin = await login(client)
    result = await db_session.execute(select(User).where(User.username == "admin"))
    admin_user = result.scalar_one()
    engineer = await _get_role_by_name(client, admin, "engineer")

    resp = await client.put(f"/api/v1/users/{admin_user.id}", json={
        "role_id": engineer["id"],
    }, headers=admin)
    assert resp.status_code == 400


async def test_update_user_normal_user_ignored_fields(client, db_session):
    """普通用户 PUT /users/{id} 时 is_active/role_id 被静默忽略且不报错。"""
    admin = await login(client)
    user_id, user_auth = await create_normal_user(client, admin)

    resp = await client.put(f"/api/v1/users/{user_id}", json={
        "display_name": "新名字",
        "is_active": False,   # 应被忽略
        "role_id": 9999,      # 应被忽略
    }, headers=user_auth)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["display_name"] == "新名字"
    assert body["is_active"] is True  # 未被改成 False

    result = await db_session.execute(select(User).where(User.id == user_id))
    db_user = result.scalar_one()
    assert db_user.role_id != 9999

    # 普通用户不能改别人
    resp = await client.put("/api/v1/users/1", json={"display_name": "x"}, headers=user_auth)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 4. 迁移脚本幂等 + 回滚
# ---------------------------------------------------------------------------

async def test_migrate_secrets_idempotent_and_rollback(client, db_session):
    """迁移脚本：明文 → 密文 → 重复执行跳过 → 回滚还原明文。"""
    from src.utils.migrate_secrets import migrate, rollback

    # 造一条含明文 secret 的 SSO 配置（临时数据，用完即删）
    db_session.add(SystemConfig(
        key="sso_config",
        value=json.dumps({"client_id": "mig", "client_secret": "plain-secret"}),
    ))
    await db_session.commit()

    async def _stored_secret():
        result = await db_session.execute(
            select(SystemConfig).where(SystemConfig.key == "sso_config")
        )
        return json.loads(result.scalar_one().value)["client_secret"]

    # 第一次迁移
    n1 = await migrate(db_session)
    assert n1 == 1
    first = await _stored_secret()
    assert first.startswith(SECRET_ENC_PREFIX)

    # 第二次迁移（幂等：跳过）
    n2 = await migrate(db_session)
    assert n2 == 0
    assert await _stored_secret() == first

    # 回滚
    n3 = await rollback(db_session)
    assert n3 == 1
    assert await _stored_secret() == "plain-secret"

    # 清理临时数据
    result = await db_session.execute(
        select(SystemConfig).where(SystemConfig.key == "sso_config")
    )
    record = result.scalar_one()
    await db_session.delete(record)
    await db_session.commit()
