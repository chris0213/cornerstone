"""设备资产编号字段 + IPAM addresses ids 精确查询回归。

背景：
- 设备新增选填字段 asset_tag（资产编号）；
- /ipam/addresses/ 是分页接口（默认 100 条），网段扫描入库几千条后，
  设备页靠 ids 参数按 id 精确补拉被引用的管理 IP，需不受分页截断。
"""
import pytest
from sqlalchemy import insert, select, func

from src.models import Role, User
from src.models.ip_address import IPAddress
from src.services.permission_service import pwd_context

pytestmark = pytest.mark.asyncio


async def _make_engineer(db, username: str = "qa_dev"):
    role = (await db.execute(select(Role).where(Role.name == "engineer"))).scalar_one()
    db.add(User(
        username=username, display_name=username, email=f"{username}@example.com",
        hashed_password=pwd_context.hash("Passw0rd!"), role_id=role.id, is_active=True,
    ))
    await db.commit()


async def _login(client, username: str = "qa_dev") -> dict:
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": username, "password": "Passw0rd!"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed_ips(db, count: int = 3):
    """造 count 条 IP，返回 id 列表"""
    for i in range(count):
        await db.execute(insert(IPAddress).values(
            address=f"10.91.0.{i + 1}", status="已分配", usage="管理IP",
        ))
    await db.commit()
    rows = (await db.execute(select(IPAddress).order_by(IPAddress.id))).scalars().all()
    return [r.id for r in rows]


async def test_device_asset_tag_create_and_update(client, db_session):
    """资产编号：创建带 asset_tag，更新可改、可清空"""
    await _make_engineer(db_session)
    headers = await _login(client)

    resp = await client.post("/api/v1/devices/", headers=headers, json={
        "name": "资产设备", "type": "switch", "vendor": "huawei_vrp",
        "asset_tag": "IT-2026-0001",
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["asset_tag"] == "IT-2026-0001"
    device_id = body["id"]

    resp = await client.put(f"/api/v1/devices/{device_id}", headers=headers, json={
        "asset_tag": "IT-2026-0002",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["asset_tag"] == "IT-2026-0002"

    resp = await client.put(f"/api/v1/devices/{device_id}", headers=headers, json={
        "asset_tag": None,
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["asset_tag"] is None


async def test_device_asset_tag_optional(client, db_session):
    """资产编号不传时不阻塞创建（选填）"""
    await _make_engineer(db_session)
    headers = await _login(client)

    resp = await client.post("/api/v1/devices/", headers=headers, json={
        "name": "无资产编号设备", "type": "switch",
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()["asset_tag"] is None


async def test_ipam_addresses_ids_exact_lookup(client, db_session):
    """ids 参数按 id 精确取回且不受分页截断；无效 ids 返回空列表"""
    await _make_engineer(db_session)
    headers = await _login(client)
    ip_ids = await _seed_ips(db_session, count=3)

    resp = await client.get(
        "/api/v1/ipam/addresses/",
        headers=headers,
        params={"ids": ",".join(str(i) for i in ip_ids), "limit": 1},  # limit=1 若生效会截断
    )
    assert resp.status_code == 200, resp.text
    got_ids = {row["id"] for row in resp.json()}
    assert got_ids == set(ip_ids)

    resp = await client.get("/api/v1/ipam/addresses/", headers=headers, params={"ids": " "})
    assert resp.status_code == 200 and resp.json() == []

    resp = await client.get("/api/v1/ipam/addresses/", headers=headers, params={"ids": "999999"})
    assert resp.status_code == 200 and resp.json() == []
