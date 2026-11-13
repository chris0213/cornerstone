"""多租户地基回归测试。

覆盖：
- 默认租户与历史数据回填（tenant_id=1）
- 单租户下行为不变（原有 203 个测试之外的最小验证）
- 跨租户数据不可见（列表/详情）
- ORM 层 tenant_scope 过滤
- 写入兜底：按上下文补齐 tenant_id、跨租户写入被拒绝
- 平台超管跨租户（系统作用域）与普通用户严格隔离
- 后台任务按租户遍历、WebSocket 按租户推送、Core DML/insert 租户条件
"""
from datetime import timedelta

import pytest
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from src.models import AIChatLog, AlertRecord, AuditLog, LinkMonitor, Role, Site, Tenant, User, UserSession
from src.services.alert_ws import AlertWSManager
from src.tasks.log_cleanup import cleanup_expired_logs
from src.tenant.bootstrap import DEFAULT_TENANT_ID
from src.tenant.context import system_scope, tenant_scope
from src.tenant.session import CrossTenantWriteError
from src.utils.security import get_password_hash
from src.utils.timeutil import utc_now

pytestmark = pytest.mark.asyncio


async def login(client, username="admin", password="admin123") -> dict:
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _create_normal_user(
    db_session,
    username: str,
    tenant_id: int = DEFAULT_TENANT_ID,
    password: str = "user123",
) -> None:
    """创建普通用户（engineer 角色，非超管），用于验证严格租户隔离。"""
    role = (await db_session.execute(select(Role).where(Role.name == "engineer"))).scalars().first()
    assert role is not None
    db_session.add(User(
        username=username,
        email=f"{username}@test.local",
        hashed_password=get_password_hash(password),
        role_id=role.id,
        is_active=True,
        is_superuser=False,
        tenant_id=tenant_id,
    ))
    await db_session.commit()


async def _seed_tenant_b(db_session) -> int:
    """直接在 ORM 层造租户 B 及其站点（无上下文时显式 tenant_id 生效）。"""
    if await db_session.get(Tenant, 2) is None:
        db_session.add(Tenant(id=2, code="tenant-b", name="租户B"))
        await db_session.flush()
    site = Site(name="B-租户专属站点", tenant_id=2)
    db_session.add(site)
    await db_session.commit()
    return site.id


async def test_default_tenant_backfill(client, db_session):
    auth = await login(client)
    assert auth

    default_tenant = await db_session.get(Tenant, DEFAULT_TENANT_ID)
    assert default_tenant is not None
    assert default_tenant.code == "default"

    result = await db_session.execute(select(User).where(User.username == "admin"))
    admin = result.scalar_one()
    assert admin.tenant_id == DEFAULT_TENANT_ID


async def test_single_tenant_behaviour_unchanged(client):
    auth = await login(client)

    created = await client.post(
        "/api/v1/sites/", json={"name": "A-租户正常站点"}, headers=auth
    )
    assert created.status_code == 201, created.text
    site_id = created.json()["id"]

    detail = await client.get(f"/api/v1/sites/{site_id}", headers=auth)
    assert detail.status_code == 200
    assert detail.json()["name"] == "A-租户正常站点"

    listed = await client.get("/api/v1/sites/", headers=auth)
    assert listed.status_code == 200
    assert any(item["id"] == site_id for item in listed.json())


async def test_cross_tenant_data_invisible(client, db_session):
    # 用普通用户（非超管）验证严格隔离：超管本就可跨租户，不能作为对照
    await _create_normal_user(db_session, "tenant_a_user")
    auth = await login(client, "tenant_a_user", "user123")
    other_site_id = await _seed_tenant_b(db_session)

    # 详情：跨租户返回 404（不暴露存在性）
    detail = await client.get(f"/api/v1/sites/{other_site_id}", headers=auth)
    assert detail.status_code == 404

    # 列表：看不到租户 B 的站点
    listed = await client.get("/api/v1/sites/", headers=auth)
    assert listed.status_code == 200
    names = [item["name"] for item in listed.json()]
    assert "B-租户专属站点" not in names

    # 跨租户修改同样 404
    updated = await client.put(
        f"/api/v1/sites/{other_site_id}", json={"name": "越权改名"}, headers=auth
    )
    assert updated.status_code == 404


async def test_orm_scope_filters_rows(client, db_session):
    await _seed_tenant_b(db_session)

    with tenant_scope(2):
        rows = (await db_session.execute(select(Site))).scalars().all()
        assert rows and all(row.tenant_id == 2 for row in rows)
        assert any(row.name == "B-租户专属站点" for row in rows)

    with tenant_scope(DEFAULT_TENANT_ID):
        rows = (await db_session.execute(select(Site))).scalars().all()
        assert all(row.tenant_id == DEFAULT_TENANT_ID for row in rows)
        assert all(row.name != "B-租户专属站点" for row in rows)


async def test_write_stamp_and_cross_tenant_guard(client, db_session):
    await login(client)  # 确保默认租户已初始化

    # 上下文内新建：tenant_id 自动补齐
    with tenant_scope(2):
        site = Site(name="B-上下文自动归属")
        db_session.add(site)
        await db_session.commit()
        assert site.tenant_id == 2

    # 显式写入其他租户：拒绝
    with tenant_scope(DEFAULT_TENANT_ID):
        db_session.add(Site(name="越权写入", tenant_id=2))
        with pytest.raises(CrossTenantWriteError):
            await db_session.commit()
        await db_session.rollback()

    # 已存在对象禁止改 tenant_id
    with tenant_scope(2):
        site = (await db_session.execute(
            select(Site).where(Site.name == "B-上下文自动归属")
        )).scalar_one()
        site.tenant_id = 1
        with pytest.raises(CrossTenantWriteError):
            await db_session.commit()
        await db_session.rollback()


async def test_super_admin_crosses_tenants(client, db_session):
    """平台超管走系统作用域：可跨租户查看，但新建数据仍归属自身租户。"""
    other_site_id = await _seed_tenant_b(db_session)
    auth = await login(client)  # admin = 平台超管

    listed = await client.get("/api/v1/sites/", headers=auth)
    assert listed.status_code == 200
    assert any(item["id"] == other_site_id for item in listed.json())

    detail = await client.get(f"/api/v1/sites/{other_site_id}", headers=auth)
    assert detail.status_code == 200

    # 超管 bypass 只关闭读过滤，写入仍归属其所属租户（默认租户）
    created = await client.post("/api/v1/sites/", json={"name": "超管新建站点"}, headers=auth)
    assert created.status_code == 201, created.text
    new_id = created.json()["id"]
    row = (await db_session.execute(select(Site).where(Site.id == new_id))).scalar_one()
    assert row.tenant_id == DEFAULT_TENANT_ID


async def test_log_cleanup_traverses_tenants(client, db_session, test_engine):
    """后台日志清理按租户遍历：两个租户的过期数据都被清理，未过期数据保留。"""
    await login(client)  # 初始化默认租户
    await _seed_tenant_b(db_session)

    old = utc_now() - timedelta(days=40)
    db_session.add_all([
        AIChatLog(user_id=1, question="t1-old", answer_text="", created_at=old, tenant_id=1),
        AIChatLog(user_id=1, question="t2-old", answer_text="", created_at=old, tenant_id=2),
        AIChatLog(user_id=1, question="t1-fresh", answer_text="", created_at=utc_now(), tenant_id=1),
        LinkMonitor(device_id=1, target_ip="192.0.2.1", status="normal", created_at=old, tenant_id=1),
        LinkMonitor(device_id=1, target_ip="192.0.2.2", status="normal", created_at=old, tenant_id=2),
    ])
    await db_session.commit()

    TestSession = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    await cleanup_expired_logs(session_factory=TestSession)

    with system_scope():
        remaining = (await db_session.execute(select(AIChatLog.question))).scalars().all()
        monitors = (await db_session.execute(select(LinkMonitor.target_ip))).scalars().all()
    # 租户 1 与租户 2 的过期记录都被清理，未过期的仍保留
    assert remaining == ["t1-fresh"]
    assert monitors == []


class _FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def accept(self):
        return None

    async def send_json(self, message):
        self.sent.append(message)


async def test_ws_alert_broadcast_tenant_filtered():
    """告警 WS 按租户推送：租户 1 连接收不到租户 2 告警，超管收全量。"""
    manager = AlertWSManager()
    ws_a, ws_b, ws_admin = _FakeWebSocket(), _FakeWebSocket(), _FakeWebSocket()
    await manager.connect(ws_a, tenant_id=1, is_superuser=False)
    await manager.connect(ws_b, tenant_id=2, is_superuser=False)
    await manager.connect(ws_admin, tenant_id=1, is_superuser=True)

    await manager.broadcast({"type": "new_alert", "id": 9}, tenant_id=2)

    assert ws_b.sent == [{"type": "new_alert", "id": 9}]
    assert ws_a.sent == []
    assert ws_admin.sent == [{"type": "new_alert", "id": 9}]


async def test_core_dml_and_insert_tenant_scoped(client, db_session):
    """原生 SQL：Core delete 只影响当前租户，Core insert 自动写入 tenant_id。"""
    await login(client)
    other_site_id = await _seed_tenant_b(db_session)
    db_session.add(Site(name="A-保留站点", tenant_id=DEFAULT_TENANT_ID))
    await db_session.commit()

    with tenant_scope(2):
        await db_session.execute(delete(Site))
        await db_session.execute(insert(Site).values(name="B-原生插入"))
        await db_session.commit()

    remaining = (await db_session.execute(select(Site.name))).scalars().all()
    assert "A-保留站点" in remaining
    assert "B-租户专属站点" not in remaining
    assert other_site_id not in [
        row.id for row in (await db_session.execute(select(Site))).scalars().all()
    ]

    inserted = (await db_session.execute(
        select(Site).where(Site.name == "B-原生插入")
    )).scalar_one()
    assert inserted.tenant_id == 2


async def test_count_endpoints_tenant_scoped(client, db_session):
    """计数/聚合接口带租户条件：租户 B 数据不计入普通用户口径。"""
    await _create_normal_user(db_session, "tenant_a_counter")
    auth = await login(client, "tenant_a_counter", "user123")
    await _seed_tenant_b(db_session)

    db_session.add(Site(name="A-计数站点", tenant_id=DEFAULT_TENANT_ID))
    db_session.add(AlertRecord(
        alert_type="system", severity="warning", message="B租户告警",
        status="active", tenant_id=2,
    ))
    await db_session.commit()

    stats = await client.get("/api/v1/dashboard/stats", headers=auth)
    assert stats.status_code == 200, stats.text
    assert stats.json()["sites"]["total"] == 1
    assert stats.json()["alerts"]["pending"] == 0

    records = await client.get("/api/v1/alerts/records", headers=auth)
    assert records.status_code == 200, records.text
    assert records.json()["data"]["total"] == 0


async def test_login_log_belongs_to_user_tenant(client, db_session):
    """登录日志必须归属用户所属租户：租户2 用户登录后，租户1 用户不可见。

    回归背景：登录发生在认证之前、无租户上下文，历史代码未显式传
    tenant_id，Core insert 落到列默认值 1，导致 demo_a（租户1）能看到
    demo_b（租户2）的登录日志。
    """
    # 先建租户2，否则登录守卫会因「所属租户不存在」拒绝登录
    await _seed_tenant_b(db_session)
    await _create_normal_user(db_session, "tenant_a_login", tenant_id=DEFAULT_TENANT_ID)
    await _create_normal_user(db_session, "tenant_b_login", tenant_id=2)

    # 两个租户的用户各自登录成功
    auth_a = await login(client, "tenant_a_login", "user123")
    auth_b = await login(client, "tenant_b_login", "user123")
    assert auth_a and auth_b

    with system_scope():
        a_log = (await db_session.execute(
            select(AuditLog).where(
                AuditLog.user == "tenant_a_login", AuditLog.action == "用户登录"
            )
        )).scalars().first()
        b_log = (await db_session.execute(
            select(AuditLog).where(
                AuditLog.user == "tenant_b_login", AuditLog.action == "用户登录"
            )
        )).scalars().first()
    assert a_log is not None and a_log.tenant_id == DEFAULT_TENANT_ID
    assert b_log is not None and b_log.tenant_id == 2

    # 租户1 用户查看审计日志：看不到租户2 用户的登录记录
    listed = await client.get("/api/v1/logs/", headers=auth_a)
    assert listed.status_code == 200, listed.text
    users = {item["user"] for item in listed.json()}
    assert "tenant_b_login" not in users
    assert "tenant_a_login" in users


async def test_login_session_belongs_to_user_tenant(client, db_session):
    """登录会话必须归属用户所属租户：租户2 用户登录后，租户1 用户不可见。

    回归背景：UserSession 与登录日志同根因——登录发生在认证之前、
    无租户上下文，ORM 对象 tenant_id 为空落到列默认值 1，导致
    「在线会话」等视图跨租户泄漏。
    """
    await _seed_tenant_b(db_session)
    await _create_normal_user(db_session, "tenant_a_sess", tenant_id=DEFAULT_TENANT_ID)
    await _create_normal_user(db_session, "tenant_b_sess", tenant_id=2)

    auth_a = await login(client, "tenant_a_sess", "user123")
    auth_b = await login(client, "tenant_b_sess", "user123")
    assert auth_a and auth_b

    with system_scope():
        data = (await db_session.execute(
            select(User.username, UserSession.tenant_id)
            .join(UserSession, UserSession.user_id == User.id)
            .where(User.username.in_(["tenant_a_sess", "tenant_b_sess"]))
        )).all()
    mapping = {username: tenant_id for username, tenant_id in data}
    assert mapping["tenant_a_sess"] == DEFAULT_TENANT_ID
    assert mapping["tenant_b_sess"] == 2
