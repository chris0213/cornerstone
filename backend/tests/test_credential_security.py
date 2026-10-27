"""凭证管理安全加固测试（阶段 2）：R1 权限 / R2 旧接口删除 / R4 409 / R5 限流与 IP 校验 / R7 审计 / 响应脱敏。"""
import pytest
from sqlalchemy import select

from src.models import Credential, IPAddress, User, BackupTask
from src.services.permission_service import pwd_context
from src.utils.crypto import encrypt_password
import src.api.backups as backups_module


async def _login(client, username: str, password: str) -> dict:
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _make_user(db_session, username: str, email: str, role_name: str, password: str = "Passw0rd!"):
    from src.models import Role
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    user = User(
        username=username,
        display_name=username,
        email=email,
        hashed_password=pwd_context.hash(password),
        role_id=role.id,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    return user


async def _make_credential(db_session, name: str, **overrides) -> Credential:
    data = {
        "name": name,
        "username": "operator",
        "password": encrypt_password("Secret123!"),
        "port": 22,
    }
    data.update(overrides)
    cred = Credential(**data)
    db_session.add(cred)
    await db_session.commit()
    return cred


# ==================== R1 权限 ====================

@pytest.mark.asyncio
async def test_viewer_forbidden_on_credentials(client, db_session):
    """viewer 无 backups:* 权限：列表/创建/删除均 403。"""
    await _make_user(db_session, "viewer_sec", "viewer_sec@example.com", "viewer")
    headers = await _login(client, "viewer_sec", "Passw0rd!")

    assert (await client.get("/api/v1/backups/credentials", headers=headers)).status_code == 403
    assert (await client.post(
        "/api/v1/backups/credentials",
        json={"name": "x", "username": "u"},
        headers=headers,
    )).status_code == 403
    assert (await client.delete("/api/v1/backups/credentials/1", headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_engineer_allowed_on_credentials(client, db_session):
    """engineer 拥有 backups:* 权限：列表/创建 200/201，证明未误伤运维。"""
    await _make_user(db_session, "engineer_sec", "engineer_sec@example.com", "engineer")
    headers = await _login(client, "engineer_sec", "Passw0rd!")

    resp = await client.get("/api/v1/backups/credentials", headers=headers)
    assert resp.status_code == 200, resp.text

    resp = await client.post(
        "/api/v1/backups/credentials",
        json={"name": "eng-cred", "username": "u", "password": "Secret123!"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_admin_allowed_on_credentials(client):
    """超级管理员不受影响。"""
    headers = await _login(client, "admin", "admin123")
    resp = await client.get("/api/v1/backups/credentials", headers=headers)
    assert resp.status_code == 200, resp.text


# ==================== R2 旧接口已删除 ====================

@pytest.mark.asyncio
async def test_legacy_device_credential_endpoints_removed(client):
    """devices.py 原 4 个凭证接口应返回 404/405。"""
    headers = await _login(client, "admin", "admin123")
    assert (await client.get("/api/v1/devices/1/credentials", headers=headers)).status_code in (404, 405)
    assert (await client.post(
        "/api/v1/devices/1/credentials", json={}, headers=headers
    )).status_code in (404, 405)
    assert (await client.put(
        "/api/v1/devices/credentials/1", json={}, headers=headers
    )).status_code in (404, 405)
    assert (await client.delete(
        "/api/v1/devices/credentials/1", headers=headers
    )).status_code in (404, 405)


# ==================== R4 被引用删除 409 ====================

@pytest.mark.asyncio
async def test_delete_referenced_credential_conflict(client, db_session):
    """被备份任务引用的凭证删除返回 409，错误信息含任务名。"""
    headers = await _login(client, "admin", "admin123")
    cred = await _make_credential(db_session, "ref-cred")
    task = BackupTask(name="每日核心备份", credential_id=cred.id)
    db_session.add(task)
    await db_session.commit()

    resp = await client.delete(f"/api/v1/backups/credentials/{cred.id}", headers=headers)
    assert resp.status_code == 409
    body = resp.json()
    assert body["detail"]["code"] == "credential.in_use"
    assert "每日核心备份" in body["detail"]["message"]
    assert body["detail"]["params"]["tasks"][0]["name"] == "每日核心备份"

    # 清理
    await db_session.delete(task)
    await db_session.commit()


@pytest.mark.asyncio
async def test_delete_unreferenced_credential_ok(client, db_session):
    """无引用的凭证删除返回 204，且记录不可再查。"""
    headers = await _login(client, "admin", "admin123")
    cred = await _make_credential(db_session, "lonely-cred")

    resp = await client.delete(f"/api/v1/backups/credentials/{cred.id}", headers=headers)
    assert resp.status_code == 204
    # 用 count 查询绕过 identity map，直接确认库中已删除
    from sqlalchemy import func
    count = (await db_session.execute(
        select(func.count()).select_from(Credential).where(Credential.id == cred.id)
    )).scalar_one()
    assert count == 0


# ==================== R5 限流与 IP 校验 ====================

@pytest.fixture
def mock_connect(monkeypatch):
    """跳过真实 netmiko 连接，返回成功结果。"""
    from src.services.backup_collector import CollectResult

    async def fake_test(device_dict, credential_dict):
        return CollectResult(success=True, config_content="连接测试成功", duration_ms=1)

    monkeypatch.setattr(backups_module, "test_device_connection", fake_test)


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """隔离进程内限流字典。"""
    backups_module._credential_test_last.clear()
    yield
    backups_module._credential_test_last.clear()


@pytest.fixture(autouse=True)
def allow_private_test_ips(monkeypatch):
    """本模块测试统一使用私网 IP（192.168.x / 10.0.0.9）作为测试目标，
    显式开启私网放行；生产默认 credential_test_allow_private=False（防 SSRF）不受影响。"""
    from src.config import settings
    monkeypatch.setattr(settings, "credential_test_allow_private", True)


@pytest.mark.asyncio
async def test_rate_limit_second_call_rejected(client, db_session, mock_connect):
    """同一凭证 10 秒内第二次测试连接返回 400 credential.test_rate_limited。"""
    headers = await _login(client, "admin", "admin123")
    cred = await _make_credential(db_session, "rate-cred")

    first = await client.post(
        f"/api/v1/backups/credentials/{cred.id}/test",
        json={"test_ip": "192.168.1.50"},
        headers=headers,
    )
    assert first.status_code == 200, first.text

    second = await client.post(
        f"/api/v1/backups/credentials/{cred.id}/test",
        json={"test_ip": "192.168.1.50"},
        headers=headers,
    )
    assert second.status_code == 400
    assert second.json()["detail"]["code"] == "credential.test_rate_limited"
    assert second.json()["detail"]["params"]["retry_after_seconds"] > 0


@pytest.mark.asyncio
async def test_rate_limit_marks_time_on_allow(client, db_session, mock_connect):
    """放行后立即记录限流时间戳：连接失败也计数（用例中连接被 mock 成失败同样触发限流）。"""
    from src.services.backup_collector import CollectResult

    headers = await _login(client, "admin", "admin123")
    cred = await _make_credential(db_session, "fail-cred")

    async def fake_fail(device_dict, credential_dict):
        return CollectResult(success=False, error_message="设备不可达", duration_ms=1)

    import src.api.backups as bm
    bm.test_device_connection = fake_fail
    try:
        first = await client.post(
            f"/api/v1/backups/credentials/{cred.id}/test",
            json={"test_ip": "192.168.1.51"},
            headers=headers,
        )
        assert first.status_code == 200 and first.json()["success"] is False

        second = await client.post(
            f"/api/v1/backups/credentials/{cred.id}/test",
            json={"test_ip": "192.168.1.51"},
            headers=headers,
        )
        assert second.status_code == 400
        assert second.json()["detail"]["code"] == "credential.test_rate_limited"
    finally:
        # 恢复模块引用，避免影响同进程其他用例
        from src.services.backup_collector import test_device_connection as real
        bm.test_device_connection = real


@pytest.mark.asyncio
async def test_public_ip_rejected(client, db_session, mock_connect):
    """公网 IP 且未登记 → 400 credential.test_ip_not_allowed。"""
    headers = await _login(client, "admin", "admin123")
    cred = await _make_credential(db_session, "ip-cred")

    resp = await client.post(
        f"/api/v1/backups/credentials/{cred.id}/test",
        json={"test_ip": "8.8.8.8"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "credential.test_ip_not_allowed"


@pytest.mark.asyncio
async def test_private_ip_allowed_and_registered_ip_allowed(client, db_session, mock_connect):
    """私网 IP 放行（默认配置）；设备表已登记的公网 IP 也放行。"""
    headers = await _login(client, "admin", "admin123")
    # 限流按凭证计数，两个目标各用一个凭证避免互相干扰
    cred_private = await _make_credential(db_session, "allow-cred-private")
    cred_registered = await _make_credential(db_session, "allow-cred-registered")

    ok_private = await client.post(
        f"/api/v1/backups/credentials/{cred_private.id}/test",
        json={"test_ip": "10.0.0.9"},
        headers=headers,
    )
    assert ok_private.status_code == 200, ok_private.text

    # 登记一个公网 IP 到设备表
    registered = IPAddress(address="1.2.3.4", status="已分配")
    db_session.add(registered)
    await db_session.commit()

    ok_registered = await client.post(
        f"/api/v1/backups/credentials/{cred_registered.id}/test",
        json={"test_ip": "1.2.3.4"},
        headers=headers,
    )
    assert ok_registered.status_code == 200, ok_registered.text

    await db_session.delete(registered)
    await db_session.commit()


@pytest.mark.asyncio
async def test_invalid_ip_rejected(client, db_session, mock_connect):
    """非法 IP 格式 → 400 credential.test_ip_invalid。"""
    headers = await _login(client, "admin", "admin123")
    cred = await _make_credential(db_session, "badip-cred")

    resp = await client.post(
        f"/api/v1/backups/credentials/{cred.id}/test",
        json={"test_ip": "not-an-ip"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "credential.test_ip_invalid"


@pytest.mark.asyncio
async def test_denied_and_test_audit_written(client, db_session, monkeypatch):
    """R7：拒绝路径写 test_denied 审计；放行路径写 test 审计（连接异常也不漏）。"""
    from src.models import AuditLog

    # 模拟连接层异常：collector 内部 ping 抛异常 → collector 捕获后返回失败（真实路径）
    import src.services.backup_collector as collector

    async def fake_ping_raise(host, timeout=1.0):
        raise TimeoutError("simulated timeout")

    monkeypatch.setattr(collector, "ping_host", fake_ping_raise)

    headers = await _login(client, "admin", "admin123")
    cred = await _make_credential(db_session, "audit-cred")

    # 1) 拒绝路径（公网 IP）
    denied = await client.post(
        f"/api/v1/backups/credentials/{cred.id}/test",
        json={"test_ip": "8.8.8.8"},
        headers=headers,
    )
    assert denied.status_code == 400
    rows = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "test_denied", AuditLog.resource == f"credential:{cred.id}")
    )).scalars().all()
    assert len(rows) == 1
    import json
    details = json.loads(rows[0].detail)
    assert details["test_ip"] == "8.8.8.8"
    assert details["reason"] == "credential.test_ip_not_allowed"

    # 2) 放行路径（连接抛异常 → collector 返回失败，仍写 test 审计）
    released = await client.post(
        f"/api/v1/backups/credentials/{cred.id}/test",
        json={"test_ip": "192.168.1.60"},
        headers=headers,
    )
    assert released.status_code == 200
    assert released.json()["success"] is False  # 异常被 collector 捕获为失败
    test_rows = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "test", AuditLog.resource == f"credential:{cred.id}")
    )).scalars().all()
    assert len(test_rows) == 1
    test_details = json.loads(test_rows[0].detail)
    assert test_details["test_ip"] == "192.168.1.60"
    assert test_details["success"] is False


# ==================== 响应脱敏 ====================

@pytest.mark.asyncio
async def test_no_plaintext_or_ciphertext_in_responses(client, db_session):
    """所有凭证响应中密码均为 ********，全文不出现密文前缀 gAAAA。"""
    headers = await _login(client, "admin", "admin123")
    created = await client.post(
        "/api/v1/backups/credentials",
        json={"name": "mask-cred", "username": "u", "password": "Secret123!",
              "enable_password": "En@ble123", "private_key": "KEYDATA"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    cred_id = created.json()["id"]

    # 创建响应即脱敏
    assert created.json()["password"] == "********"
    for resp in [
        created,
        await client.get("/api/v1/backups/credentials", headers=headers),
        await client.get(f"/api/v1/backups/credentials/{cred_id}", headers=headers),
        await client.put(
            f"/api/v1/backups/credentials/{cred_id}",
            json={"password": "NewSecret456!"},
            headers=headers,
        ),
    ]:
        assert resp.status_code == 200 or resp.status_code == 201, resp.text
        assert "gAAAA" not in resp.text
        assert "Secret123!" not in resp.text
        assert "NewSecret456!" not in resp.text

    # 数据库中确为密文（Fernet gAAAA 开头），非明文
    stored = await db_session.get(Credential, cred_id)
    assert stored.password.startswith("gAAAA")
    assert stored.enable_password.startswith("gAAAA")
    assert stored.private_key.startswith("gAAAA")

    # 清理
    await client.delete(f"/api/v1/backups/credentials/{cred_id}", headers=headers)


# ==================== 使用情况 / 上次测试 ====================

@pytest.mark.asyncio
async def test_list_returns_usage_fields(client, db_session):
    """列表返回 used_by_count / used_by_tasks：被引用凭证计数与任务名正确，无引用凭证为 0/[]。"""
    headers = await _login(client, "admin", "admin123")
    cred_used = await _make_credential(db_session, "usage-used")
    cred_free = await _make_credential(db_session, "usage-free")
    task_a = BackupTask(name="usage-任务A", credential_id=cred_used.id)
    task_b = BackupTask(name="usage-任务B", credential_id=cred_used.id)
    db_session.add_all([task_a, task_b])
    await db_session.commit()

    resp = await client.get("/api/v1/backups/credentials", headers=headers)
    assert resp.status_code == 200, resp.text
    items = {c["id"]: c for c in resp.json()}

    assert items[cred_used.id]["used_by_count"] == 2
    assert {t["name"] for t in items[cred_used.id]["used_by_tasks"]} == {"usage-任务A", "usage-任务B"}
    assert items[cred_free.id]["used_by_count"] == 0
    assert items[cred_free.id]["used_by_tasks"] == []

    # 清理造数
    await db_session.delete(task_a)
    await db_session.delete(task_b)
    await db_session.commit()
    await client.delete(f"/api/v1/backups/credentials/{cred_used.id}", headers=headers)
    await client.delete(f"/api/v1/backups/credentials/{cred_free.id}", headers=headers)


@pytest.mark.asyncio
async def test_persists_last_test_result(client, db_session, mock_connect):
    """测试连接后 last_tested_at / last_test_status 写回：成功→success，失败→failed。"""
    from src.services.backup_collector import CollectResult

    headers = await _login(client, "admin", "admin123")
    cred_ok = await _make_credential(db_session, "lasttest-ok")
    cred_fail = await _make_credential(db_session, "lasttest-fail")

    assert cred_ok.last_tested_at is None  # 初始从未测试

    resp_ok = await client.post(
        f"/api/v1/backups/credentials/{cred_ok.id}/test",
        json={"test_ip": "192.168.1.70"},
        headers=headers,
    )
    assert resp_ok.status_code == 200 and resp_ok.json()["success"] is True

    async def fake_fail(device_dict, credential_dict):
        return CollectResult(success=False, error_message="设备不可达", duration_ms=1)

    import src.api.backups as bm
    bm.test_device_connection = fake_fail
    try:
        resp_fail = await client.post(
            f"/api/v1/backups/credentials/{cred_fail.id}/test",
            json={"test_ip": "192.168.1.71"},
            headers=headers,
        )
        assert resp_fail.status_code == 200 and resp_fail.json()["success"] is False
    finally:
        from src.services.backup_collector import test_device_connection as real
        bm.test_device_connection = real

    # 绕过 identity map 直接查库验证持久化
    from sqlalchemy import func
    ok_row = (await db_session.execute(
        select(Credential).where(Credential.id == cred_ok.id)
    )).scalar_one()
    fail_row = (await db_session.execute(
        select(func.count()).select_from(Credential).where(
            Credential.id == cred_fail.id,
            Credential.last_test_status == "failed",
            Credential.last_tested_at.isnot(None),
        )
    )).scalar_one()
    assert ok_row.last_test_status == "success"
    assert ok_row.last_tested_at is not None
    assert fail_row == 1

    # 列表返回字段
    listed = {c["id"]: c for c in (await client.get("/api/v1/backups/credentials", headers=headers)).json()}
    assert listed[cred_ok.id]["last_test_status"] == "success"
    assert listed[cred_ok.id]["last_tested_at"]

    # 清理
    await client.delete(f"/api/v1/backups/credentials/{cred_ok.id}", headers=headers)
    await client.delete(f"/api/v1/backups/credentials/{cred_fail.id}", headers=headers)


# ==================== quick-add R3 ====================

@pytest.mark.asyncio
async def test_quick_add_encrypts_password(client, db_session):
    """quick-add 修复后：凭证密码加密入库，无明文。"""
    from src.models import Device
    from src.utils.crypto import decrypt_password

    headers = await _login(client, "admin", "admin123")
    resp = await client.post(
        "/api/v1/devices/quick-add",
        json={
            "name": "qa-switch",
            "ip_address": "172.16.99.1",
            "vendor": "huawei_vrp",
            "username": "admin",
            "password": "Quick@Add123",
            "port": 22,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True, resp.text
    device_id = resp.json()["device_id"]

    stored = (await db_session.execute(
        select(Credential).where(Credential.device_id == device_id)
    )).scalar_one()
    assert stored.password.startswith("gAAAA")
    assert decrypt_password(stored.password) == "Quick@Add123"

    # 清理造数
    dev = await db_session.get(Device, device_id)
    await db_session.delete(stored)
    await db_session.delete(dev)
    await db_session.commit()
