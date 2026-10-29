"""单设备在线探测接口 /devices/{id}/probe 回归。

背景：
- 设备页"在线"列取管理 IP 的 is_online，但定时扫描此前只写在线不写离线，
  未被扫描过的 IP 永远停留在"未探测"；
- 新增单机探测接口：对管理 IP 做一次 probe_single_ip 并回写 is_online；
- 定时扫描口径修正：在线/离线都更新已登记记录（离线不再假在线），
  但不为离线且从未登记的 IP 建记录。

探测依赖真实网络（ICMP/TCP/ARP），单测统一 monkeypatch probe_single_ip，
只验证状态回写与错误分支。
"""
import pytest
from sqlalchemy import insert, select

from src.models import Role, User
from src.models.device import Device
from src.models.ip_address import IPAddress
from src.services.permission_service import pwd_context

pytestmark = pytest.mark.asyncio


async def _make_engineer(db, username: str = "qa_probe"):
    role = (await db.execute(select(Role).where(Role.name == "engineer"))).scalar_one()
    db.add(User(
        username=username, display_name=username, email=f"{username}@example.com",
        hashed_password=pwd_context.hash("Passw0rd!"), role_id=role.id, is_active=True,
    ))
    await db.commit()


async def _login(client, username: str = "qa_probe") -> dict:
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": username, "password": "Passw0rd!"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _patch_probe(monkeypatch, is_online: bool, method: str = "tcp"):
    """把接口内延迟导入的 probe_single_ip 换成假探测"""
    from src.services import scanner as scanner_mod

    async def fake_probe(ip, tcp_ports=None, timeout=3.0):
        return {
            "ip": ip, "is_online": is_online, "method": method,
            "open_ports": [22] if is_online else [], "mac_address": None,
            "duration_ms": 5,
        }

    # probe 在接口函数内延迟导入 src.services.scanner，patch 源模块即可
    monkeypatch.setattr(scanner_mod, "probe_single_ip", fake_probe)


async def _seed_device_with_ip(db, address: str = "10.92.0.10", with_ip: bool = True) -> int:
    ip_id = None
    if with_ip:
        await db.execute(insert(IPAddress).values(
            address=address, status="已分配", usage="管理IP", is_online=None,
        ))
        await db.commit()
        ip_id = (await db.execute(
            select(IPAddress.id).where(IPAddress.address == address)
        )).scalar_one()
    device_id = (await db.execute(insert(Device).values(
        name="探测设备", type="switch", mgmt_ip_id=ip_id,
    ).returning(Device.id))).scalar_one()
    await db.commit()
    return device_id


async def _mgmt_ip_is_online(db) -> bool:
    """读回"管理IP"用途那条记录的 is_online（先清缓存拿接口会话写入的最新值）"""
    db.expire_all()
    ip = (await db.execute(select(IPAddress).where(IPAddress.usage == "管理IP"))).scalar_one()
    return ip.is_online


async def test_probe_device_online_writes_back(client, db_session, monkeypatch):
    """在线探测：接口返回在线，且管理 IP 的 is_online 落库为 True"""
    await _make_engineer(db_session)
    headers = await _login(client)
    device_id = await _seed_device_with_ip(db_session)
    _patch_probe(monkeypatch, is_online=True, method="tcp")

    resp = await client.post(f"/api/v1/devices/{device_id}/probe", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_online"] is True
    assert body["method"] == "tcp"

    assert await _mgmt_ip_is_online(db_session) is True


async def test_probe_device_offline_writes_false(client, db_session, monkeypatch):
    """离线探测：曾在线的 IP 探测离线后 is_online 落库为 False（消除假在线）"""
    await _make_engineer(db_session)
    headers = await _login(client)
    device_id = await _seed_device_with_ip(db_session)
    # 预置该 IP 曾在线
    ip = (await db_session.execute(select(IPAddress).where(IPAddress.usage == "管理IP"))).scalar_one()
    ip.is_online = True
    await db_session.commit()
    _patch_probe(monkeypatch, is_online=False)

    resp = await client.post(f"/api/v1/devices/{device_id}/probe", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_online"] is False

    assert await _mgmt_ip_is_online(db_session) is False


async def test_probe_device_requires_mgmt_ip(client, db_session):
    """未配置管理 IP：400；设备不存在：404；未带 token：401"""
    await _make_engineer(db_session)
    headers = await _login(client)
    no_ip_device = await _seed_device_with_ip(db_session, with_ip=False)

    resp = await client.post(f"/api/v1/devices/{no_ip_device}/probe", headers=headers)
    assert resp.status_code == 400
    assert "管理IP" in resp.json()["detail"]

    resp = await client.post("/api/v1/devices/999999/probe", headers=headers)
    assert resp.status_code == 404

    resp = await client.post(f"/api/v1/devices/{no_ip_device}/probe")
    assert resp.status_code == 401
