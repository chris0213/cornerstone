# -*- coding: utf-8 -*-
"""时间线状态变化改造 + 时区口径 + 设备品牌映射 回归。

约定：
- 巡检结果时间全部相对当前时间构造，不写死日期；
- 走 conftest 临时 SQLite；时区用例仅在 SQLite 验证（PG 下 timestamptz 与 naive
  参数的比较依赖 session timezone，需在 PG 环境另行验证）。
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from src.models import Device, InspectionDeviceResult, Role, User
from src.services.permission_service import pwd_context


async def _login(client, username: str, password: str = "Passw0rd!") -> dict:
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _make_device(db_session, name: str, vendor: str = None) -> Device:
    dev = Device(name=name, vendor=vendor, status="active")
    db_session.add(dev)
    await db_session.commit()
    return dev


async def _make_scan(db_session, device: Device, is_online: bool, scanned_at: datetime,
                     ip: str = "10.0.0.1") -> InspectionDeviceResult:
    row = InspectionDeviceResult(
        ip_address=ip,
        device_id=device.id,
        is_online=is_online,
        sys_name=device.name,
        error_message=None if is_online else "device unreachable",
        scanned_at=scanned_at,
    )
    db_session.add(row)
    await db_session.commit()
    return row


async def _get_events(client, headers, **params) -> list:
    resp = await client.get("/api/v1/timeline/events", headers=headers, params=params or {})
    assert resp.status_code == 200, resp.text
    return resp.json()["events"]


# ==================== 状态变化（LAG 改造） ====================

@pytest.mark.asyncio
async def test_state_change_only_on_transition(client, db_session):
    """T→F→F 三轮：只产生 1 条离线事件（变化点），F→F 快照不刷屏。"""
    dev = await _make_device(db_session, "状态变化设备")
    now = datetime.now()
    await _make_scan(db_session, dev, True, now - timedelta(hours=3))
    await _make_scan(db_session, dev, False, now - timedelta(hours=2))
    await _make_scan(db_session, dev, False, now - timedelta(hours=1))

    headers = await _login(client, "admin", "admin123")
    events = await _get_events(client, headers, start_time=(now - timedelta(days=2)).isoformat())
    offline = [e for e in events if e["event_type"] == "device_offline"]
    online = [e for e in events if e["event_type"] == "device_online"]
    assert len(offline) == 1
    assert len(online) == 0
    assert offline[0]["resource_name"] == "状态变化设备"
    assert offline[0]["description"] == "device unreachable"


@pytest.mark.asyncio
async def test_recovery_event_once(client, db_session):
    """F→T：恰 1 条恢复事件。"""
    dev = await _make_device(db_session, "恢复设备")
    now = datetime.now()
    await _make_scan(db_session, dev, False, now - timedelta(hours=2))
    await _make_scan(db_session, dev, True, now - timedelta(hours=1))

    headers = await _login(client, "admin", "admin123")
    events = await _get_events(client, headers, start_time=(now - timedelta(days=2)).isoformat())
    online = [e for e in events if e["event_type"] == "device_online"]
    assert len(online) == 1
    assert "恢复" in online[0]["title"]


@pytest.mark.asyncio
async def test_first_scan_no_event(client, db_session):
    """该设备首轮巡检（无上一轮可比）不产生离线/恢复事件。"""
    dev = await _make_device(db_session, "首轮设备")
    now = datetime.now()
    await _make_scan(db_session, dev, False, now - timedelta(hours=1))

    headers = await _login(client, "admin", "admin123")
    events = await _get_events(client, headers, start_time=(now - timedelta(days=2)).isoformat())
    assert [e for e in events if e["event_type"] in ("device_offline", "device_online")] == []


@pytest.mark.asyncio
async def test_multi_device_independent_transitions(client, db_session):
    """多设备各自独立判定状态变化，互不串扰。"""
    dev_a = await _make_device(db_session, "设备A")
    dev_b = await _make_device(db_session, "设备B")
    now = datetime.now()
    # A：T→F（1 条离线）；B：持续 F→F（0 条）
    await _make_scan(db_session, dev_a, True, now - timedelta(hours=2), ip="10.0.0.1")
    await _make_scan(db_session, dev_a, False, now - timedelta(hours=1), ip="10.0.0.1")
    await _make_scan(db_session, dev_b, False, now - timedelta(hours=2), ip="10.0.0.2")
    await _make_scan(db_session, dev_b, False, now - timedelta(hours=1), ip="10.0.0.2")

    headers = await _login(client, "admin", "admin123")
    events = await _get_events(client, headers, start_time=(now - timedelta(days=2)).isoformat())
    offline = [e for e in events if e["event_type"] == "device_offline"]
    assert len(offline) == 1
    assert offline[0]["resource_name"] == "设备A"


# ==================== 时区口径（SQLite 验证；PG 需另行验证） ====================

@pytest.mark.asyncio
async def test_time_range_naive_and_aware_boundary(client, db_session):
    """时间口径：naive 本地字符串与 aware 北京时间两种入参均正确命中当天记录。"""
    dev = await _make_device(db_session, "时区设备")
    now = datetime.now()
    # 两条记录构成 T→F 状态变化（首轮不产生事件，需有前轮）
    await _make_scan(db_session, dev, True, now - timedelta(hours=2))
    # 以 now-1h 为事件锚点（必在"当天0点 ~ now"窗内；0点整时 start==scan 仍命中）
    scan_at = now - timedelta(hours=1)
    await _make_scan(db_session, dev, False, scan_at)

    headers = await _login(client, "admin", "admin123")
    day_start = scan_at.replace(hour=0, minute=0, second=0, microsecond=0)

    # naive 本地挂钟（步骤 B 后前端的新传参格式）
    events = await _get_events(
        client, headers,
        start_time=day_start.isoformat(),     # "YYYY-MM-DDT00:00:00" 无时区
        end_time=now.isoformat(),
    )
    assert any(e["event_type"] == "device_offline" for e in events)

    # aware 带北京时区（兼容旧调用方）——后端 to_naive_bjt 归一后同样命中
    events = await _get_events(
        client, headers,
        start_time=day_start.isoformat() + "+08:00",
        end_time=now.isoformat() + "+08:00",
    )
    assert any(e["event_type"] == "device_offline" for e in events)

    # 时间窗之外（3 天前起 2 天止）不命中
    events = await _get_events(
        client, headers,
        start_time=(now - timedelta(days=3)).isoformat(),
        end_time=(now - timedelta(days=1)).isoformat(),
    )
    assert not any(e["event_type"] == "device_offline" for e in events)


# ==================== 设备品牌映射 ====================

@pytest.mark.asyncio
async def test_brand_mapping_driver_names(client, db_session):
    """netmiko 驱动名 → 品牌映射：linux/paloalto_panos 独立成品牌，不再落入"其他"。"""
    await _make_device(db_session, "服务器1", vendor="linux")
    await _make_device(db_session, "防火墙1", vendor="paloalto_panos")
    await _make_device(db_session, "交换机1", vendor="huawei_vrp")
    await _make_device(db_session, "小主机", vendor="supermicro_x")  # 未知名 → other
    await _make_device(db_session, "无厂商", vendor=None)            # 无 vendor 无 type → unknown

    headers = await _login(client, "admin", "admin123")
    resp = await client.get("/api/v1/dashboard/device-types", headers=headers)
    assert resp.status_code == 200, resp.text
    data = {item["name"]: item["value"] for item in resp.json()}
    assert data.get("Linux 系统") == 1
    assert data.get("Palo Alto") == 1
    assert data.get("华为") == 1
    assert data.get("其他") == 1
    assert data.get("未知") == 1
