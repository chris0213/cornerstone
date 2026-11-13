"""权限补齐与审计日志安全回归测试。

覆盖：
- 14 个模块的读/写权限（403 而不是 500）、超管放行、viewer/engineer 差异
- 审计日志禁止客户端写入
- 审计清理：保留期下限 180 天、先归档后删除、归档失败不删除
"""
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from src.config import settings
from src.models import AuditLog
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


async def _role_id(client, admin_auth, name: str) -> int:
    resp = await client.get("/api/v1/users/roles/", headers=admin_auth)
    assert resp.status_code == 200, resp.text
    for role in resp.json():
        if role["name"] == name:
            return role["id"]
    raise AssertionError(f"role {name} not found")


async def _create_user(client, admin_auth, username: str, role_name: str) -> dict:
    role_id = await _role_id(client, admin_auth, role_name)
    resp = await client.post(
        "/api/v1/users",
        json={
            "username": username,
            "email": f"{username}@test.com",
            "password": "Passw0rd123",
            "role_id": role_id,
        },
        headers=admin_auth,
    )
    assert resp.status_code == 201, resp.text
    return await login(client, username, "Passw0rd123")


# ---------------------------------------------------------------------------
# A. 权限矩阵：viewer / engineer / super_admin
# ---------------------------------------------------------------------------

async def test_permission_matrix(client):
    admin = await login(client)
    engineer = await _create_user(client, admin, "eng1", "engineer")
    viewer = await _create_user(client, admin, "view1", "viewer")

    # 未登录：401
    assert (await client.get("/api/v1/sites/")).status_code == 401

    # viewer：只读业务 + 新增的 monitor/timeline/ai；管理类全部 403
    assert (await client.get("/api/v1/circuits/", headers=viewer)).status_code == 200
    assert (await client.get("/api/v1/monitor/devices", headers=viewer)).status_code == 200
    assert (await client.get("/api/v1/timeline/events", headers=viewer)).status_code == 200
    assert (await client.get("/api/v1/ai/chat-logs", headers=viewer)).status_code == 200
    assert (await client.get("/api/v1/logs/", headers=viewer)).status_code == 200
    assert (await client.get("/api/v1/incidents/", headers=viewer)).status_code == 200
    for path in (
        "/api/v1/sites/",
        "/api/v1/devices/",
        "/api/v1/ipam/prefixes/",
        "/api/v1/ipam/vlans/",
        "/api/v1/topology/site-graph",
        "/api/v1/users/",
        "/api/v1/import-export/devices/export",
    ):
        resp = await client.get(path, headers=viewer)
        assert resp.status_code == 403, f"{path} -> {resp.status_code} {resp.text}"

    # engineer：业务模块可读；用户管理 403
    for path in (
        "/api/v1/sites/",
        "/api/v1/devices/",
        "/api/v1/ipam/prefixes/",
        "/api/v1/ipam/vlans/",
        "/api/v1/topology/site-graph",
        "/api/v1/monitor/devices",
        "/api/v1/timeline/events",
        "/api/v1/ai/chat-logs",
        "/api/v1/logs/",
        "/api/v1/import-export/devices/export",
    ):
        resp = await client.get(path, headers=engineer)
        assert resp.status_code == 200, f"{path} -> {resp.status_code} {resp.text}"
    assert (await client.get("/api/v1/users/", headers=engineer)).status_code == 403

    # 写权限：engineer 可建站点，viewer 被拒
    site_payload = {"name": "权限测试站点", "code": "PERM-TEST"}
    assert (await client.post("/api/v1/sites/", json=site_payload, headers=viewer)).status_code == 403
    resp = await client.post("/api/v1/sites/", json=site_payload, headers=engineer)
    assert resp.status_code == 201, resp.text
    site_id = resp.json()["id"]
    # engineer 可删，viewer 被拒
    assert (await client.delete(f"/api/v1/sites/{site_id}", headers=viewer)).status_code == 403
    assert (await client.delete(f"/api/v1/sites/{site_id}", headers=engineer)).status_code == 204

    # 超管放行
    assert (await client.get("/api/v1/users/", headers=admin)).status_code == 200

    # auth：公开/自助接口不锁死；跨用户会话查看被拒
    assert (await client.get("/api/v1/auth/me", headers=viewer)).status_code == 200
    users = (await client.get("/api/v1/users/", headers=admin)).json()
    admin_id = next(u["id"] for u in users if u["username"] == "admin")
    assert (await client.get(f"/api/v1/users/{admin_id}/sessions", headers=viewer)).status_code == 403


async def test_create_user_accepts_trailing_slash_and_checks_permission(client):
    """前端使用 POST /users/（带尾斜杠），后端必须同时支持两种路径；
    且 engineer/viewer 不能创建用户（403 而非 405/500）。"""
    admin = await login(client)
    engineer = await _create_user(client, admin, "eng_create", "engineer")
    viewer = await _create_user(client, admin, "view_create", "viewer")
    role_id = await _role_id(client, admin, "engineer")
    payload = {
        "username": "slash_user",
        "email": "slash@test.com",
        "password": "Passw0rd123",
        "role_id": role_id,
    }

    # 带尾斜杠（前端实际调用形态）
    resp = await client.post("/api/v1/users/", json=payload, headers=admin)
    assert resp.status_code == 201, resp.text
    assert resp.json()["username"] == "slash_user"

    # 不带尾斜杠
    payload2 = dict(payload, username="slash_user2", email="slash2@test.com")
    resp = await client.post("/api/v1/users", json=payload2, headers=admin)
    assert resp.status_code == 201, resp.text

    # 非超管：403，不能创建
    payload3 = dict(payload, username="slash_user3", email="slash3@test.com")
    assert (await client.post("/api/v1/users/", json=payload3, headers=engineer)).status_code == 403
    assert (await client.post("/api/v1/users/", json=payload3, headers=viewer)).status_code == 403


async def test_vlan_group_routes_accept_both_slash_styles(client):
    """前端调用 /ipam/vlans/groups/{id}（无尾斜杠），后端需同时注册带/不带斜杠。"""
    admin = await login(client)
    payload = {"name": "x", "site_id": None, "description": ""}
    resp = await client.put("/api/v1/ipam/vlans/groups/999999", json=payload, headers=admin)
    assert resp.status_code == 404
    assert resp.json()["detail"] != "Not Found", "无尾斜杠 PUT 未命中业务路由"

    resp = await client.delete("/api/v1/ipam/vlans/groups/999999", headers=admin)
    assert resp.status_code == 404
    assert resp.json()["detail"] != "Not Found", "无尾斜杠 DELETE 未命中业务路由"


# ---------------------------------------------------------------------------
# B1. 审计日志禁止客户端写入
# ---------------------------------------------------------------------------
async def test_audit_log_post_removed(client, db_session):
    admin = await login(client)
    before = (await db_session.execute(select(func.count(AuditLog.id)))).scalar_one()

    resp = await client.post(
        "/api/v1/logs/",
        json={"user": "admin", "action": "伪造", "resource": "系统", "detail": "fake"},
        headers=admin,
    )
    assert resp.status_code in (404, 405)

    after = (await db_session.execute(select(func.count(AuditLog.id)))).scalar_one()
    assert after == before


# ---------------------------------------------------------------------------
# B2. 保留期下限 + 先归档后删除
# ---------------------------------------------------------------------------

async def test_log_retention_minimum_180_days(client):
    admin = await login(client)
    resp = await client.get("/api/v1/settings/logs", headers=admin)
    assert resp.status_code == 200
    assert resp.json()["log_retention_days"] == 180

    resp = await client.put(
        "/api/v1/settings/logs",
        json={"log_retention_days": 30, "login_log_retention_days": 30},
        headers=admin,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["log_retention_days"] == 180
    assert body["login_log_retention_days"] == 180


async def test_cleanup_archives_then_deletes(client, db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "audit_archive_dir", str(tmp_path / "archive"))
    admin = await login(client)

    old = AuditLog(
        user="admin", action="创建用户", resource="用户", detail="old",
        created_at=utc_now() - timedelta(days=200),
    )
    recent = AuditLog(
        user="admin", action="查看", resource="系统", detail="recent",
        created_at=utc_now() - timedelta(days=1),
    )
    db_session.add_all([old, recent])
    await db_session.commit()
    old_id, recent_id = old.id, recent.id

    resp = await client.post("/api/v1/settings/logs/cleanup", headers=admin)
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted_count"] >= 1

    remaining = (await db_session.execute(
        select(AuditLog.id).where(AuditLog.id.in_([old_id, recent_id]))
    )).scalars().all()
    assert old_id not in remaining
    assert recent_id in remaining

    files = list((tmp_path / "archive").glob("*.csv"))
    assert files, "归档文件未生成"
    content = "".join(f.read_text(encoding="utf-8-sig") for f in files)
    assert "old" in content


async def test_archive_failure_blocks_delete(client, db_session, tmp_path, monkeypatch):
    # 用“文件/子目录”制造不可创建目录，模拟归档失败
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x")
    monkeypatch.setattr(settings, "audit_archive_dir", str(blocker / "sub"))

    old = AuditLog(
        user="admin", action="创建用户", resource="用户", detail="must-keep",
        created_at=utc_now() - timedelta(days=200),
    )
    db_session.add(old)
    await db_session.commit()
    old_id = old.id

    admin = await login(client)
    resp = await client.post("/api/v1/settings/logs/cleanup", headers=admin)
    assert resp.status_code == 500, resp.text

    exists = (await db_session.execute(
        select(AuditLog.id).where(AuditLog.id == old_id)
    )).scalar_one_or_none()
    assert exists == old_id, "归档失败时不得删除审计日志"


async def test_scheduled_cleanup_uses_archive(tmp_path, monkeypatch, test_engine, db_session):
    """定时清理任务同样先归档后删除（注入测试库会话工厂）。"""
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker

    from src.tasks.log_cleanup import cleanup_expired_logs

    monkeypatch.setattr(settings, "audit_archive_dir", str(tmp_path / "sched-archive"))
    TestSession = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    old = AuditLog(
        user="admin", action="登录", resource="系统", detail="sched-old",
        created_at=utc_now() - timedelta(days=200),
    )
    db_session.add(old)
    await db_session.commit()
    old_id = old.id

    await cleanup_expired_logs(TestSession)

    exists = (await db_session.execute(
        select(AuditLog.id).where(AuditLog.id == old_id)
    )).scalar_one_or_none()
    assert exists is None
    assert list((tmp_path / "sched-archive").glob("*.csv"))
