"""租户管理与登录拦截回归测试。

覆盖：
- 租户列表/新建/编码唯一校验
- 默认租户不可停用
- 停用租户：现有会话被撤销、后续登录被明确拒绝、启用后恢复
- 新建用户指定租户（仅超管生效，普通调用者强制自身租户）
- 用户租户变更与审计日志
"""
import pytest
from sqlalchemy import select

from src.models import AuditLog, Permission, Role, RolePermission, User
from src.tenant.bootstrap import DEFAULT_TENANT_ID
from src.tenant.context import system_scope
from src.utils.security import get_password_hash

pytestmark = pytest.mark.asyncio

PASSWORD = "DemoPass123"


async def login(client, username="admin", password="admin123") -> dict:
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return resp


async def _auth(client, username="admin", password="admin123") -> dict:
    resp = await login(client, username, password)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _create_tenant(client, auth, code="acme", name="Acme 租户") -> dict:
    resp = await client.post("/api/v1/tenants/", json={"code": code, "name": name}, headers=auth)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_tenant_user(db_session, username: str, tenant_id: int, role_name: str = "engineer") -> User:
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalars().first()
    assert role is not None
    user = User(
        username=username,
        email=f"{username}@example.com",
        hashed_password=get_password_hash(PASSWORD),
        role_id=role.id,
        is_active=True,
        is_superuser=False,
        tenant_id=tenant_id,
    )
    db_session.add(user)
    await db_session.commit()
    return user


async def test_tenant_list_and_create_validation(client, db_session):
    auth = await _auth(client)

    listed = await client.get("/api/v1/tenants/", headers=auth)
    assert listed.status_code == 200, listed.text
    default_tenant = next(t for t in listed.json() if t["id"] == DEFAULT_TENANT_ID)
    assert default_tenant["is_default"] is True
    assert default_tenant["code"] == "default"

    created = await _create_tenant(client, auth)
    assert created["status"] == "active"
    assert created["user_count"] == 0
    assert created["is_default"] is False

    # 编码唯一
    duplicated = await client.post(
        "/api/v1/tenants/", json={"code": "acme", "name": "重复编码"}, headers=auth
    )
    assert duplicated.status_code == 400
    assert "已存在" in duplicated.json()["detail"]

    # 编码必填
    missing = await client.post("/api/v1/tenants/", json={"code": "", "name": "空编码"}, headers=auth)
    assert missing.status_code == 422


async def test_default_tenant_cannot_be_suspended(client):
    auth = await _auth(client)
    resp = await client.put(
        f"/api/v1/tenants/{DEFAULT_TENANT_ID}/status",
        json={"status": "suspended"},
        headers=auth,
    )
    assert resp.status_code == 400
    assert "默认租户不允许停用" in resp.json()["detail"]


async def test_suspend_blocks_login_and_revokes_sessions(client, db_session):
    auth = await _auth(client)
    tenant = await _create_tenant(client, auth, code="acme", name="Acme 租户")
    await _create_tenant_user(db_session, "acme_user", tenant["id"])

    # 启用状态下可正常登录
    first_login = await login(client, "acme_user", PASSWORD)
    assert first_login.status_code == 200, first_login.text
    token = {"Authorization": f"Bearer {first_login.json()['access_token']}"}

    # 停用租户
    suspended = await client.put(
        f"/api/v1/tenants/{tenant['id']}/status",
        json={"status": "suspended", "reason": "演示停用"},
        headers=auth,
    )
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["status"] == "suspended"
    assert suspended.json()["user_count"] == 1

    # 已签发 token 因会话撤销而失效
    me = await client.get("/api/v1/auth/me", headers=token)
    assert me.status_code == 401

    # 再次登录：明确提示租户已停用
    blocked = await login(client, "acme_user", PASSWORD)
    assert blocked.status_code == 403
    assert "已停用" in blocked.json()["detail"]

    # 重新启用后可登录
    enabled = await client.put(
        f"/api/v1/tenants/{tenant['id']}/status",
        json={"status": "active"},
        headers=auth,
    )
    assert enabled.status_code == 200
    assert (await login(client, "acme_user", PASSWORD)).status_code == 200

    # 审计：新建与停用都有记录
    with system_scope():
        actions = (await db_session.execute(
            select(AuditLog.action).where(AuditLog.action.in_(["创建租户", "停用租户", "启用租户"]))
        )).scalars().all()
    assert "创建租户" in actions and "停用租户" in actions and "启用租户" in actions


async def test_user_creation_tenant_assignment(client, db_session):
    auth = await _auth(client)
    tenant = await _create_tenant(client, auth, code="beta", name="Beta 租户")

    # 超管可指定租户
    created = await client.post(
        "/api/v1/users/",
        json={
            "username": "beta_user",
            "email": "beta_user@example.com",
            "password": PASSWORD,
            "tenant_id": tenant["id"],
        },
        headers=auth,
    )
    assert created.status_code == 201, created.text
    assert created.json()["tenant_id"] == tenant["id"]

    stored = (await db_session.execute(select(User).where(User.username == "beta_user"))).scalar_one()
    assert stored.tenant_id == tenant["id"]

    # 普通用户（有 users:write 的自定义角色）指定租户会被强制为自身租户
    role = Role(name="tenant_admin", display_name="租户管理员", is_builtin=False)
    db_session.add(role)
    await db_session.flush()
    permission_ids = (await db_session.execute(
        select(Permission.id).where(Permission.module == "users")
    )).scalars().all()
    for pid in permission_ids:
        db_session.add(RolePermission(role_id=role.id, permission_id=pid))
    await db_session.commit()

    await _create_tenant_user(db_session, "tenant_admin_user", DEFAULT_TENANT_ID, role_name="tenant_admin")
    admin_auth = await _auth(client, "tenant_admin_user", PASSWORD)

    forced = await client.post(
        "/api/v1/users/",
        json={
            "username": "forced_user",
            "email": "forced_user@example.com",
            "password": PASSWORD,
            "tenant_id": tenant["id"],
        },
        headers=admin_auth,
    )
    assert forced.status_code == 201, forced.text
    assert forced.json()["tenant_id"] == DEFAULT_TENANT_ID


async def test_user_tenant_change_audited(client, db_session):
    auth = await _auth(client)
    tenant = await _create_tenant(client, auth, code="gamma", name="Gamma 租户")
    user = await _create_tenant_user(db_session, "gamma_user", DEFAULT_TENANT_ID)
    user_id = user.id

    updated = await client.put(
        f"/api/v1/users/{user_id}",
        json={"tenant_id": tenant["id"]},
        headers=auth,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["tenant_id"] == tenant["id"]

    db_session.expire_all()
    stored = (await db_session.execute(select(User).where(User.id == user_id))).scalar_one()
    assert stored.tenant_id == tenant["id"]

    with system_scope():
        details = (await db_session.execute(
            select(AuditLog.detail).where(AuditLog.action == "编辑用户")
        )).scalars().all()
    assert any("租户归属" in d for d in details)


async def test_tenant_api_forbidden_for_non_superuser(client, db_session):
    await _create_tenant_user(db_session, "plain_engineer", DEFAULT_TENANT_ID)
    auth = await _auth(client, "plain_engineer", PASSWORD)

    listed = await client.get("/api/v1/tenants/", headers=auth)
    assert listed.status_code == 403
