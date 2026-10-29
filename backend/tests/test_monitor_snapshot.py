# -*- coding: utf-8 -*-
"""监控数据口径回归测试。

背景：仪表盘在线设备数/健康度此前按全表累计口径统计（30 天内曾 normal 即算在线，
最近宕机被历史好数据稀释），/monitor/devices、/topology/device-graph 全表拉取后
内存去重。本轮统一为「每设备最新一条快照」口径，并补齐 /monitor/* 全部端点鉴权。
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from src.models import Device, LinkMonitor
from src.services.permission_service import pwd_context

pytestmark = pytest.mark.asyncio


async def _login(client, username: str = "admin", password: str = "admin123") -> dict:
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _make_device(db_session, name: str) -> Device:
    dev = Device(name=name, status="active")
    db_session.add(dev)
    await db_session.commit()
    return dev


async def _seed(db_session, device_id, status, minutes_ago):
    """插一条监控快照：created_at 用相对时间，status 为三档之一。"""
    db_session.add(LinkMonitor(
        device_id=device_id, target_ip="10.0.0.1",
        status=status, latency=10.0, packet_loss=0.0,
        created_at=datetime.now() - timedelta(minutes=minutes_ago),
    ))


# ==================== /monitor/* 鉴权 ====================

@pytest.mark.asyncio
async def test_monitor_endpoints_require_auth(client):
    """/monitor/* 此前全部无鉴权（含 ping 任意 IP、启停调度器），修复后未登录一律 401。"""
    endpoints = [
        ("GET", "/api/v1/monitor/devices"),
        ("GET", "/api/v1/monitor/history/1"),
        ("GET", "/api/v1/monitor/summary"),
        ("GET", "/api/v1/monitor/scheduler/status"),
        ("POST", "/api/v1/monitor/run"),
        ("POST", "/api/v1/monitor/ping/127.0.0.1"),
        ("POST", "/api/v1/monitor/scheduler/start"),
        ("POST", "/api/v1/monitor/scheduler/stop"),
        ("POST", "/api/v1/monitor/scheduler/interval?interval_minutes=5"),
    ]
    for method, ep in endpoints:
        resp = await client.request(method, ep)
        assert resp.status_code == 401, f"{method} {ep} 未登录应为 401，实际 {resp.status_code}"


@pytest.mark.asyncio
async def test_monitor_endpoints_authorized_ok(client):
    """已登录访问核心读接口 → 200。"""
    headers = await _login(client)
    for ep in ["/api/v1/monitor/devices", "/api/v1/monitor/summary",
               "/api/v1/monitor/scheduler/status"]:
        resp = await client.get(ep, headers=headers)
        assert resp.status_code == 200, f"{ep} 应为 200，实际 {resp.status_code}: {resp.text}"


# ==================== 在线设备快照口径 ====================

@pytest.mark.asyncio
async def test_dashboard_online_uses_latest_snapshot(client, db_session):
    """设备最新一轮探测 critical → 仪表盘不在线（修复前：历史 normal 记录使其永远在线）。"""
    dev = await _make_device(db_session, "快照设备甲")
    # 50 分钟前 normal（历史好数据），10 分钟前 critical（当前宕机）
    await _seed(db_session, dev.id, "normal", minutes_ago=50)
    await _seed(db_session, dev.id, "critical", minutes_ago=10)
    await db_session.commit()

    headers = await _login(client)
    resp = await client.get("/api/v1/dashboard/stats", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["devices"]["online"] == 0


@pytest.mark.asyncio
async def test_dashboard_online_normal_latest(client, db_session):
    """最新一轮 normal → 在线数 +1；健康度按快照计满。"""
    dev = await _make_device(db_session, "快照设备乙")
    await _seed(db_session, dev.id, "critical", minutes_ago=50)  # 历史坏数据
    await _seed(db_session, dev.id, "normal", minutes_ago=10)    # 当前恢复
    await db_session.commit()

    headers = await _login(client)
    resp = await client.get("/api/v1/dashboard/stats", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["devices"]["online"] == 1
    assert data["health"]["score"] == 100


# ==================== /monitor/devices 快照去重 ====================

@pytest.mark.asyncio
async def test_monitor_devices_returns_one_row_per_device(client, db_session):
    """/monitor/devices 每设备只返回最新一条（修复前全表拉取内存去重，语义不变）。"""
    dev = await _make_device(db_session, "快照设备丙")
    await _seed(db_session, dev.id, "warning", minutes_ago=30)
    await _seed(db_session, dev.id, "critical", minutes_ago=5)  # 最新
    await db_session.commit()

    headers = await _login(client)
    resp = await client.get(f"/api/v1/monitor/devices?device_id={dev.id}", headers=headers)
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "critical"
    assert rows[0]["device_name"] == "快照设备丙"
