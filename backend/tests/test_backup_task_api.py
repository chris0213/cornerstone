"""备份任务接口安全加固测试（阶段 A）：权限 / scope 校验 / run-now 防重 / 列表新字段。"""
import json

import pytest
from sqlalchemy import select

from src.models import BackupTask, Credential, Device, User
from src.services.permission_service import pwd_context
from src.utils.crypto import encrypt_password


async def _login(client, username: str, password: str) -> dict:
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _make_user(db_session, username: str, role_name: str, password: str = "Passw0rd!"):
    from src.models import Role
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


async def _make_credential(db_session, name: str, protocol: str = "ssh") -> Credential:
    cred = Credential(
        name=name,
        username="operator",
        password=encrypt_password("Secret123!"),
        port=22,
        protocol=protocol,
    )
    db_session.add(cred)
    await db_session.commit()
    return cred


async def _make_device(db_session, name: str) -> Device:
    device = Device(name=name, type="switch", vendor="huawei_vrp")
    db_session.add(device)
    await db_session.commit()
    return device


async def _make_task(db_session, name: str, **overrides) -> BackupTask:
    data = {
        "name": name,
        "cron_expr": "0 2 * * *",
        "credential_id": 1,
        "device_ids": json.dumps([1]),
        "is_enabled": True,
    }
    data.update(overrides)
    task = BackupTask(**data)
    db_session.add(task)
    await db_session.commit()
    return task


# ==================== 权限 ====================

@pytest.mark.asyncio
async def test_viewer_forbidden_on_backup_tasks(client, db_session):
    """viewer 无 backups:* 权限：任务列表/创建/删除/启停/立即执行均 403。"""
    await _make_user(db_session, "viewer_bt", "viewer")
    headers = await _login(client, "viewer_bt", "Passw0rd!")

    assert (await client.get("/api/v1/backup-tasks/", headers=headers)).status_code == 403
    assert (await client.post(
        "/api/v1/backup-tasks/",
        json={"name": "x", "cron_expr": "0 2 * * *", "credential_id": 1, "device_ids": [1]},
        headers=headers,
    )).status_code == 403
    assert (await client.delete("/api/v1/backup-tasks/1", headers=headers)).status_code == 403
    assert (await client.patch("/api/v1/backup-tasks/1/toggle", headers=headers)).status_code == 403
    assert (await client.post("/api/v1/backup-tasks/1/run-now", headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_engineer_allowed_on_backup_tasks(client, db_session, monkeypatch):
    """engineer 拥有 backups:* 权限：列表 200、create 201、run-now 非 403。"""
    from src.api import backup_tasks as bt_module

    # 拦截真正执行，避免测试内连真实设备产生噪音警告
    async def _noop(task_id, trigger):
        return

    monkeypatch.setattr(bt_module, "run_backup_task", _noop)
    await _make_user(db_session, "engineer_bt", "engineer")
    cred = await _make_credential(db_session, "eng-cred")
    dev = await _make_device(db_session, "eng-dev")
    headers = await _login(client, "engineer_bt", "Passw0rd!")

    resp = await client.get("/api/v1/backup-tasks/", headers=headers)
    assert resp.status_code == 200, resp.text

    resp = await client.post(
        "/api/v1/backup-tasks/",
        json={
            "name": "eng-task", "cron_expr": "0 2 * * *",
            "credential_id": cred.id, "device_ids": [dev.id],
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    task_id = resp.json()["id"]

    # run-now：不 403（测试库无真实设备连接，任务启动即返回 200）
    resp = await client.post(f"/api/v1/backup-tasks/{task_id}/run-now", headers=headers)
    assert resp.status_code == 200, resp.text

    # 清理造数
    await client.delete(f"/api/v1/backup-tasks/{task_id}", headers=headers)
    await client.delete(f"/api/v1/backups/credentials/{cred.id}", headers={"Authorization": headers["Authorization"]})


# ==================== scope 校验 ====================

@pytest.mark.asyncio
async def test_create_requires_scope(client, db_session):
    """create 未指定 device_ids 且未指定 site_id：400 + backup_task.scope_required。"""
    cred = await _make_credential(db_session, "scope-cred")
    admin = await _login(client, "admin", "admin123")

    resp = await client.post(
        "/api/v1/backup-tasks/",
        json={"name": "no-scope", "cron_expr": "0 2 * * *", "credential_id": cred.id},
        headers=admin,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "backup_task.scope_required"

    # 指定 device_ids 后通过
    dev = await _make_device(db_session, "scope-dev")
    resp = await client.post(
        "/api/v1/backup-tasks/",
        json={"name": "with-scope", "cron_expr": "0 2 * * *", "credential_id": cred.id, "device_ids": [dev.id]},
        headers=admin,
    )
    assert resp.status_code == 201, resp.text

    # 清理
    await client.delete(f"/api/v1/backup-tasks/{resp.json()['id']}", headers=admin)


@pytest.mark.asyncio
async def test_update_scope_uses_final_effective_value(client, db_session):
    """update 的 scope 校验按「最终生效值」判断：库里有 scope、请求只改 cron 时不应误伤。"""
    cred = await _make_credential(db_session, "upd-cred")
    dev = await _make_device(db_session, "upd-dev")
    admin = await _login(client, "admin", "admin123")

    resp = await client.post(
        "/api/v1/backup-tasks/",
        json={"name": "upd-task", "cron_expr": "0 2 * * *", "credential_id": cred.id, "device_ids": [dev.id]},
        headers=admin,
    )
    task_id = resp.json()["id"]

    # 只改 cron：设备范围沿用库中值，应通过
    resp = await client.put(
        f"/api/v1/backup-tasks/{task_id}",
        json={"cron_expr": "0 3 * * *"},
        headers=admin,
    )
    assert resp.status_code == 200, resp.text

    # 显式清空 scope：拒绝
    resp = await client.put(
        f"/api/v1/backup-tasks/{task_id}",
        json={"device_ids": [], "site_id": None},
        headers=admin,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "backup_task.scope_required"

    # 清理
    await client.delete(f"/api/v1/backup-tasks/{task_id}", headers=admin)


# ==================== run-now 防重复 ====================

@pytest.mark.asyncio
async def test_run_now_conflict_when_already_running(client, db_session, monkeypatch):
    """任务执行中（running_tasks 置位）再触发 run-now：409 + backup_task.already_running。"""
    from src.api import backup_tasks as bt_module

    cred = await _make_credential(db_session, "run-cred")
    dev = await _make_device(db_session, "run-dev")
    admin = await _login(client, "admin", "admin123")

    resp = await client.post(
        "/api/v1/backup-tasks/",
        json={"name": "run-task", "cron_expr": "0 2 * * *", "credential_id": cred.id, "device_ids": [dev.id]},
        headers=admin,
    )
    task_id = resp.json()["id"]

    # 模拟任务正在执行（不真正启动备份）
    monkeypatch.setitem(bt_module.running_tasks, task_id, True)
    resp = await client.post(f"/api/v1/backup-tasks/{task_id}/run-now", headers=admin)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "backup_task.already_running"

    # 列表 is_running 同步为 True
    listed = {t["id"]: t for t in (await client.get("/api/v1/backup-tasks/", headers=admin)).json()}
    assert listed[task_id]["is_running"] is True

    # 清理
    monkeypatch.undo()
    await client.delete(f"/api/v1/backup-tasks/{task_id}", headers=admin)


@pytest.mark.asyncio
async def test_run_now_not_conflicting_when_idle(client, db_session, monkeypatch):
    """空闲任务 run-now 正常启动（200），is_running 由 run_backup_task 置位，接口不误报。"""
    from src.api import backup_tasks as bt_module

    # 拦截真正执行，避免测试内连真实设备
    async def _noop(task_id, trigger):
        return

    monkeypatch.setattr(bt_module, "run_backup_task", _noop)
    cred = await _make_credential(db_session, "idle-cred")
    dev = await _make_device(db_session, "idle-dev")
    admin = await _login(client, "admin", "admin123")

    resp = await client.post(
        "/api/v1/backup-tasks/",
        json={"name": "idle-task", "cron_expr": "0 2 * * *", "credential_id": cred.id, "device_ids": [dev.id]},
        headers=admin,
    )
    task_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/backup-tasks/{task_id}/run-now", headers=admin)
    assert resp.status_code == 200, resp.text

    # 清理
    await client.delete(f"/api/v1/backup-tasks/{task_id}", headers=admin)


# ==================== 列表新字段 ====================

@pytest.mark.asyncio
async def test_list_returns_scope_and_missing_fields(client, db_session):
    """列表返回 scope_type / credential_protocol / credential_missing / device_missing_ids / next_run_at / is_running。"""
    from src.api import backup_tasks as bt_module

    cred_ok = await _make_credential(db_session, "list-cred", protocol="telnet")
    dev_a = await _make_device(db_session, "list-dev-a")
    dev_b = await _make_device(db_session, "list-dev-b")
    admin = await _login(client, "admin", "admin123")

    # 任务引用 dev_a + 不存在的 dev 99999（设备缺失）；凭证存在（telnet 协议）
    resp = await client.post(
        "/api/v1/backup-tasks/",
        json={"name": "list-task", "cron_expr": "0 2 * * *", "credential_id": cred_ok.id,
              "device_ids": [dev_a.id, 99999]},
        headers=admin,
    )
    task_id = resp.json()["id"]

    # 凭证缺失任务：credential_id 指向不存在的凭证
    missing_task = await _make_task(db_session, "list-missing-task", credential_id=99999,
                                    device_ids=json.dumps([dev_b.id]))

    # 存量空范围任务（不经 API，直插 DB 模拟存量数据）
    legacy_task = await _make_task(db_session, "list-legacy-task", device_ids=None)

    listed = {t["id"]: t for t in (await client.get("/api/v1/backup-tasks/", headers=admin)).json()}

    normal = listed[task_id]
    assert normal["scope_type"] == "devices"
    assert normal["device_count"] == 2
    assert normal["credential_protocol"] == "telnet"
    assert normal["credential_missing"] is False
    assert normal["device_missing_ids"] == [99999]
    assert normal["is_running"] is False
    # 测试环境调度器未注册（无 lifespan），启用任务的 next_run_at 为 null
    assert normal["next_run_at"] is None

    missing = listed[missing_task.id]
    assert missing["credential_missing"] is True
    assert missing["credential_protocol"] is None
    assert missing["scope_type"] == "devices"
    assert missing["device_missing_ids"] == []

    legacy = listed[legacy_task.id]
    assert legacy["scope_type"] == "all"
    assert legacy["device_count"] >= 2  # 全部设备数（至少含本用例造的 2 台）
    assert legacy["device_missing_ids"] == []

    # 停用任务的 next_run_at 也为 null（未注册）
    assert legacy["next_run_at"] is None

    # 清理造数
    await client.delete(f"/api/v1/backup-tasks/{task_id}", headers=admin)
    await client.delete(f"/api/v1/backup-tasks/{missing_task.id}", headers=admin)
    await client.delete(f"/api/v1/backup-tasks/{legacy_task.id}", headers=admin)
