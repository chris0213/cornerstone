# -*- coding: utf-8 -*-
"""首页看板修复回归：接口认证、费用口径拆分、可用性标记、已逾期风险置顶、recent-logs 字段。

约定：
- 全部测试数据用「相对当前时间」构造，不写死日期；
- 走 conftest 临时 SQLite（用例结束自动丢弃），不触碰演示数据与 admin 账号配置；
- admin 账号由 conftest 的 init_default_admin 创建（密码与 INITIAL_ADMIN_PASSWORD 一致）。
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from src.models import AuditLog, Backup, Circuit, Device, LinkMonitor, Role, User
from src.services.permission_service import pwd_context

# 六个原无认证的汇总/时间线接口（本轮已统一加 get_current_active_user）
AUTH_ENDPOINTS = [
    "/api/v1/dashboard/stats",
    "/api/v1/dashboard/prefixes-usage",
    "/api/v1/dashboard/recent-logs",
    "/api/v1/dashboard/device-types",
    "/api/v1/dashboard/circuit-types",
    "/api/v1/timeline/events",
]


async def _login(client, username: str, password: str = "Passw0rd!") -> dict:
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _make_user(db_session, username: str, role_name: str, password: str = "Passw0rd!") -> User:
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    user = User(
        username=username,
        display_name=username,
        email=f"{username}@example.com",
        hashed_password=pwd_context.hash(password),
        role_id=role.id,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    return user


async def _make_device(db_session, name: str) -> Device:
    dev = Device(name=name, status="active")
    db_session.add(dev)
    await db_session.commit()
    return dev


async def _make_circuit(db_session, name: str, monthly_cost: float,
                        contract_start=None, contract_end=None, status: str = "正常") -> Circuit:
    circuit = Circuit(
        name=name,
        monthly_cost=monthly_cost,
        contract_start=contract_start,
        contract_end=contract_end,
        status=status,
    )
    db_session.add(circuit)
    await db_session.commit()
    return circuit


# ==================== 认证 ====================

@pytest.mark.asyncio
async def test_unauthenticated_dashboard_endpoints_401(client):
    """未登录访问六个汇总/时间线接口 → 全部 401（修复前全部 200）。"""
    for ep in AUTH_ENDPOINTS:
        resp = await client.get(ep)
        assert resp.status_code == 401, f"{ep} 未登录应为 401，实际 {resp.status_code}"


@pytest.mark.asyncio
async def test_admin_dashboard_endpoints_200(client):
    """已登录（admin）访问六个接口 → 全部 200。"""
    headers = await _login(client, "admin", "admin123")
    for ep in AUTH_ENDPOINTS:
        resp = await client.get(ep, headers=headers)
        assert resp.status_code == 200, f"{ep} 已登录应为 200，实际 {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_role_rules_on_dashboard(client, db_session):
    """角色规则：viewer 可读全部（含 manager-stats）；engineer 可读 stats 但 manager-stats 403。"""
    await _make_user(db_session, "dash_viewer", "viewer")
    await _make_user(db_session, "dash_engineer", "engineer")

    viewer = await _login(client, "dash_viewer")
    engineer = await _login(client, "dash_engineer")

    # 现有规则：manager 系列接口 viewer/super_admin 放行
    resp = await client.get("/api/v1/dashboard/manager-stats", headers=viewer)
    assert resp.status_code == 200

    # stats 无角色限制：engineer 放行
    resp = await client.get("/api/v1/dashboard/stats", headers=engineer)
    assert resp.status_code == 200
    # manager-stats：engineer 403
    resp = await client.get("/api/v1/dashboard/manager-stats", headers=engineer)
    assert resp.status_code == 403


# ==================== risks：备份连败不 500 ====================

@pytest.mark.asyncio
async def test_backup_fail_risk_not_500(client, db_session):
    """回归：设备 7 天内备份连败 >3 次，risks 接口不再 500（原 fb.device_id AttributeError）。"""
    dev = await _make_device(db_session, "连败设备")
    now = datetime.now()
    for i in range(4):
        db_session.add(Backup(
            device_id=dev.id, status="failed",
            error_message="connection timeout",
            created_at=now - timedelta(hours=i),
        ))
    await db_session.commit()

    headers = await _login(client, "admin", "admin123")
    resp = await client.get("/api/v1/dashboard/risks", headers=headers)
    assert resp.status_code == 200, resp.text
    backup_risks = [r for r in resp.json()["risks"] if r["category"] == "backup"]
    assert len(backup_risks) == 1
    assert backup_risks[0]["title"] == "连败设备 配置备份连续失败"


# ==================== 费用口径拆分 ====================

@pytest.mark.asyncio
async def test_cost_split_in_contract_vs_expired_unrenewed(client, db_session):
    """卡片费用拆分：合同内/已到期未续约分别统计；已停用不计；未开通不计；trend/last_month 为 null。"""
    now = datetime.now()
    # 合同内：已开通、未到期
    await _make_circuit(db_session, "合同内专线", 1000.0,
                        contract_start=now - timedelta(days=30),
                        contract_end=now + timedelta(days=300))
    # 已到期未续约：已出合同期但 status 仍"正常"
    await _make_circuit(db_session, "到期未续约专线", 2000.0,
                        contract_start=now - timedelta(days=400),
                        contract_end=now - timedelta(days=10))
    # 已到期但已停用：不计入
    await _make_circuit(db_session, "已停用专线", 9999.0,
                        contract_start=now - timedelta(days=400),
                        contract_end=now - timedelta(days=5),
                        status="停用")
    # 未开通：contract_start 在未来，不计入
    await _make_circuit(db_session, "未开通专线", 500.0,
                        contract_start=now + timedelta(days=30),
                        contract_end=now + timedelta(days=400))

    headers = await _login(client, "admin", "admin123")
    resp = await client.get("/api/v1/dashboard/manager-stats", headers=headers)
    assert resp.status_code == 200, resp.text
    cost = resp.json()["circuit_cost"]
    assert cost["in_contract"] == 1000
    assert cost["expired_unrenewed"] == 2000
    # 兼容字段 = 两者之和（前端改造前卡片仍显示合计）
    assert cost["current"] == 3000
    # 无月租历史：不再返回假同比
    assert cost["last_month"] is None
    assert cost["trend"] is None


@pytest.mark.asyncio
async def test_cost_trend_billing_conservation(client, db_session):
    """趋势守恒：逐月 in_contract + expired_unrenewed == total_costs。"""
    now = datetime.now()
    await _make_circuit(db_session, "守恒-合同内", 1000.0,
                        contract_start=now - timedelta(days=30),
                        contract_end=now + timedelta(days=300))
    await _make_circuit(db_session, "守恒-到期未续约", 22600.0,
                        contract_start=now - timedelta(days=400),
                        contract_end=now - timedelta(days=10))

    headers = await _login(client, "admin", "admin123")
    resp = await client.get("/api/v1/dashboard/circuit-cost-trend", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["months"]) == 12
    assert len(data["by_billing"]["in_contract"]) == 12
    assert len(data["by_billing"]["expired_unrenewed"]) == 12
    for i in range(12):
        assert data["by_billing"]["in_contract"][i] + data["by_billing"]["expired_unrenewed"][i] \
            == data["total_costs"][i], f"第 {data['months'][i]} 月守恒失败"


# ==================== 可用性 ====================

@pytest.mark.asyncio
async def test_availability_all_failed_and_trend_null(client, db_session):
    """本月探测全失败 → current=0.0 且 all_failed=True；上月无探测 → trend=null、last_month_available=False。"""
    dev = await _make_device(db_session, "探测设备")
    now = datetime.now()
    # 本月：全部 critical，无 normal
    for i in range(5):
        db_session.add(LinkMonitor(
            device_id=dev.id, target_ip="10.0.0.1",
            status="critical", created_at=now - timedelta(hours=i),
        ))
    await db_session.commit()

    headers = await _login(client, "admin", "admin123")
    resp = await client.get("/api/v1/dashboard/manager-stats", headers=headers)
    assert resp.status_code == 200, resp.text
    availability = resp.json()["availability"]
    assert availability["current"] == 0.0
    assert availability["all_failed"] is True
    # 上月无探测数据：不再误判"与上月持平"
    assert availability["trend"] is None
    assert availability["last_month_available"] is False


@pytest.mark.asyncio
async def test_availability_trend_up_with_last_month_data(client, db_session):
    """上月/本月均有数据时 trend 正常计算（is not None 修复 0.0 falsy 短路）。"""
    dev = await _make_device(db_session, "趋势设备")
    now = datetime.now()
    month_start = datetime(now.year, now.month, 1)
    # 本月：一半 normal（50%）
    for i in range(2):
        db_session.add(LinkMonitor(device_id=dev.id, target_ip="10.0.0.1",
                                   status="normal", created_at=now - timedelta(hours=i)))
        db_session.add(LinkMonitor(device_id=dev.id, target_ip="10.0.0.1",
                                   status="critical", created_at=now - timedelta(hours=i)))
    # 上月：全部 critical（0%）
    last_month = month_start - timedelta(days=1)
    if last_month.month == now.month:  # 跨月 1 日安全网（1 号 0 点附近）
        last_month = month_start - timedelta(hours=2)
    for i in range(4):
        db_session.add(LinkMonitor(device_id=dev.id, target_ip="10.0.0.1",
                                   status="critical", created_at=last_month))
    await db_session.commit()

    headers = await _login(client, "admin", "admin123")
    resp = await client.get("/api/v1/dashboard/manager-stats", headers=headers)
    assert resp.status_code == 200, resp.text
    availability = resp.json()["availability"]
    assert availability["current"] == 50.0
    assert availability["last_month"] == 0.0
    # 50 > 0：trend 应为 up（修复前 0.0 falsy 短路 → null）
    assert availability["trend"] == "up"
    assert availability["last_month_available"] is True


# ==================== 已逾期专线风险置顶 ====================

@pytest.mark.asyncio
async def test_expired_circuit_risk_first(client, db_session):
    """已逾期未续约的在册专线：高风险首项置顶；已停用的不统计。"""
    now = datetime.now()
    await _make_circuit(db_session, "逾期专线甲", 22600.0,
                        contract_start=now - timedelta(days=400),
                        contract_end=now - timedelta(days=10))
    await _make_circuit(db_session, "逾期专线乙", 5200.0,
                        contract_start=now - timedelta(days=400),
                        contract_end=now - timedelta(days=3))
    # 已逾期但已改状态（停用）：不计入
    await _make_circuit(db_session, "逾期已停用", 8888.0,
                        contract_start=now - timedelta(days=400),
                        contract_end=now - timedelta(days=5),
                        status="停用")

    headers = await _login(client, "admin", "admin123")
    resp = await client.get("/api/v1/dashboard/risks", headers=headers)
    assert resp.status_code == 200, resp.text
    risks = resp.json()["risks"]
    assert len(risks) >= 1
    first = risks[0]
    assert first["severity"] == "high"
    assert "已逾期未续约" in first["title"]
    assert first["count"] == 2
    assert first["action_url"] == "/circuits"


# ==================== recent-logs 字段 ====================

@pytest.mark.asyncio
async def test_recent_logs_returns_user_and_ip(client, db_session):
    """recent-logs 返回 user 与 ip_address（DB 有数据，接口此前丢弃 IP）。"""
    now = datetime.now()
    db_session.add(AuditLog(
        user="tester", action="测试动作", resource="测试资源",
        detail="验证 ip 透传", success="true", ip_address="192.168.8.28",
        created_at=now,
    ))
    await db_session.commit()

    headers = await _login(client, "admin", "admin123")
    resp = await client.get("/api/v1/dashboard/recent-logs", headers=headers)
    assert resp.status_code == 200, resp.text
    logs = resp.json()
    target = next(l for l in logs if l["action"] == "测试动作")
    assert target["user"] == "tester"
    assert target["ip_address"] == "192.168.8.28"
