"""快速添加设备的 IP 接管逻辑（网段扫描占位记录不应阻断添加设备）。

背景：网段扫描会把在线 IP 自动写入 ip_addresses（status=已分配、无设备归属）。
此前 quick-add 遇到任何已存在 IP 一律报「已存在」，导致扫描过的网段无法添加设备。
"""
import pytest
from sqlalchemy import insert, select, func

from src.models.device import Device
from src.models.ip_address import IPAddress
from src.models.prefix import Prefix
from src.models import Role, User
from src.services.permission_service import pwd_context

pytestmark = pytest.mark.asyncio


async def _make_engineer(db, username: str = "qa_eng"):
    """创建带 devices:write 的 engineer 用户（quick-add 需要该权限）"""
    role = (await db.execute(select(Role).where(Role.name == "engineer"))).scalar_one()
    db.add(User(
        username=username, display_name=username, email=f"{username}@example.com",
        hashed_password=pwd_context.hash("Passw0rd!"), role_id=role.id, is_active=True,
    ))
    await db.commit()


async def _login(client, username: str, password: str = "Passw0rd!") -> dict:
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed(db, ip: str, *, status: str = "已分配", usage: str = None):
    """造子网 + IP 记录，返回 ip_id"""
    await db.execute(insert(Prefix).values(network="10.90.0.0/24", created_at=func.now()))
    pid = (await db.execute(select(Prefix).where(Prefix.network == "10.90.0.0/24"))).scalars().first().id
    await db.execute(insert(IPAddress).values(address=ip, prefix_id=pid, status=status, usage=usage, is_online=True))
    await db.commit()
    return (await db.execute(select(IPAddress).where(IPAddress.address == ip))).scalars().first().id


async def _quick_add(client, ip: str, name: str = "qa-device", headers: dict = None, prefix_id: int = None):
    return await client.post("/api/v1/devices/quick-add", headers=headers or {}, json={
        "name": name, "type": "switch", "vendor": "huawei", "ip_address": ip,
        "site_id": None, "prefix_id": prefix_id, "username": "admin",
        "password": "x", "port": 22,
    })


async def test_takeover_scanned_ip(client, db_session):
    """扫描占位（已分配、无归属）的 IP 应被设备接管，而非报「已存在」"""
    await _make_engineer(db_session)
    headers = await _login(client, "qa_eng")
    iid = await _seed(db_session, "10.90.0.36")

    resp = await _quick_add(client, "10.90.0.36", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True, body["message"]

    ip = (await db_session.execute(select(IPAddress).where(IPAddress.id == iid))).scalar_one()
    dev = (await db_session.execute(select(Device).where(Device.id == body["device_id"]))).scalar_one()
    # 接管断言：复用原记录、标记管理 IP、双向关联
    assert ip.usage == "管理IP"
    assert dev.mgmt_ip_id == iid


async def test_conflict_when_ip_used_by_other_device(client, db_session):
    """IP 已是其他设备的管理 IP 时应报冲突，且消息包含占用设备名"""
    await _make_engineer(db_session)
    headers = await _login(client, "qa_eng")
    iid = await _seed(db_session, "10.90.0.37")
    await db_session.execute(insert(Device).values(
        name="占用设备", type="switch", vendor="huawei", mgmt_ip_id=iid, status="active", created_at=func.now(),
    ))
    await db_session.commit()

    resp = await _quick_add(client, "10.90.0.37", name="另一台", headers=headers)
    body = resp.json()
    assert body["success"] is False
    assert "占用设备" in body["message"]


async def test_new_ip_still_created(client, db_session):
    """IP 不存在时维持原路径：带 prefix_id 新建 IP 记录并关联设备"""
    await _make_engineer(db_session)
    headers = await _login(client, "qa_eng")
    await _seed(db_session, "10.90.0.1")  # 仅用于建出 10.90.0.0/24 子网
    pid = (await db_session.execute(select(Prefix).where(Prefix.network == "10.90.0.0/24"))).scalar_one().id

    resp = await _quick_add(client, "10.90.0.99", name="全新设备", headers=headers, prefix_id=pid)
    body = resp.json()
    assert body["success"] is True

    ip = (await db_session.execute(select(IPAddress).where(IPAddress.address == "10.90.0.99"))).scalar_one()
    dev = (await db_session.execute(select(Device).where(Device.id == body["device_id"]))).scalar_one()
    assert ip.usage == "管理IP" and dev.mgmt_ip_id == ip.id
