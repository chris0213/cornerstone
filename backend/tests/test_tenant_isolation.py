"""多租户地基回归测试。

覆盖：
- 默认租户与历史数据回填（tenant_id=1）
- 单租户下行为不变（原有 203 个测试之外的最小验证）
- 跨租户数据不可见（列表/详情）
- ORM 层 tenant_scope 过滤
- 写入兜底：按上下文补齐 tenant_id、跨租户写入被拒绝
"""
import pytest
from sqlalchemy import select

from src.models import Site, Tenant, User
from src.tenant.bootstrap import DEFAULT_TENANT_ID
from src.tenant.context import tenant_scope
from src.tenant.session import CrossTenantWriteError

pytestmark = pytest.mark.asyncio


async def login(client, username="admin", password="admin123") -> dict:
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


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
    auth = await login(client)
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
