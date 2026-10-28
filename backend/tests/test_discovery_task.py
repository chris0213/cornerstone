"""拓扑发现后台任务回归：跨事件循环修复 + 任务状态机。

背景：discover-lldp / discover-mac 此前用 run_in_executor + asyncio.run 新开
事件循环执行发现，但传入的全局 async_session 连接池绑定 uvicorn 主 loop，
触发 "Task got Future attached to a different loop"，LLDP 发现必失败。
修复后改为 asyncio.create_task 在主 loop 直接运行（SSH 同步采集已由 to_thread 下放）。
"""
import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from src.models import Role, User
from src.models.credential import Credential
from src.models.device import Device
from src.models.ip_address import IPAddress
from src.services.discovery_task_manager import run_discovery_task
from src.services.permission_service import pwd_context
from src.utils.crypto import encrypt_password

pytestmark = pytest.mark.asyncio


class _FakeDB:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


async def test_run_discovery_task_success():
    """runner 正常返回 → 任务 completed、结果与进度落任务对象"""
    task = type("T", (), {"id": "t1", "status": "running", "result": None,
                          "error": None, "finished_at": None})()

    async def fake_runner(db, progress):
        await progress("采集中", 1, 1, "x")
        return {"ok": True}

    await run_discovery_task(task, fake_runner, _FakeDB)
    assert task.status == "completed"
    assert task.result == {"ok": True}
    assert task.phase == "完成"


async def test_run_discovery_task_failure():
    """runner 抛异常 → 任务 failed、错误信息落任务对象，不向外抛"""
    task = type("T", (), {"id": "t2", "status": "running", "result": None,
                          "error": None, "finished_at": None})()

    async def fake_runner(db, progress):
        raise RuntimeError("boom")

    await run_discovery_task(task, fake_runner, _FakeDB)
    assert task.status == "failed"
    assert "boom" in task.error


async def test_discover_lldp_runs_on_main_loop(client, db_session, monkeypatch):
    """e2e：发现任务在主 loop 运行并正常完成（旧实现必触发 cross-loop 错误）"""
    # 造设备 + 管理 IP + 凭证
    ip = IPAddress(address="10.95.0.1", status="已分配", usage="管理IP")
    db_session.add(ip)
    await db_session.flush()
    dev = Device(name="qa-lldp-sw", type="switch", vendor="huawei", mgmt_ip_id=ip.id, status="active")
    db_session.add(dev)
    await db_session.flush()
    db_session.add(Credential(
        name="qa-lldp-cred", device_id=dev.id, username="admin",
        password=encrypt_password("Secret123!"), port=22, enable_password="",
    ))
    await db_session.commit()

    # 采集函数打桩：立即返回（不真连 SSH），覆盖「任务调度与状态机」本身
    import src.services.lldp_discovery as lldp_mod

    async def fake_sync(device_infos):
        return [], "未发现 LLDP/CDP 邻居（设备可能未启用 LLDP）"

    monkeypatch.setattr(lldp_mod, "collect_lldp_neighbors_sync", fake_sync)

    # 接口把 topology 模块导入的全局 async_session 作为 db_factory 传入任务，
    # 测试中替换为测试库会话工厂（避免触碰真实开发库）
    import src.api.topology as topo_mod

    engine = db_session.bind
    TestSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # 与 async_sessionmaker 同构：同步调用返回 AsyncSession（支持 async with）
    def test_session_factory():
        return TestSessionLocal()

    monkeypatch.setattr(topo_mod, "async_session", test_session_factory)

    resp = await client.post("/api/v1/topology/discover-lldp")
    assert resp.status_code == 200, resp.text
    task_id = resp.json()["task_id"]

    # 轮询任务直至结束（create_task 在主 loop；若回归跨 loop bug 会 failed）
    from src.services.discovery_task_manager import manager
    info = None
    for _ in range(200):
        info = (await client.get(f"/api/v1/topology/discovery-tasks/{task_id}")).json()
        if info["status"] in ("completed", "failed"):
            break
        await asyncio.sleep(0.02)

    assert info["status"] == "completed", info
    assert info["error"] is None
    assert info["done"] == info["total"] == 1
    # 设备级采集失败（打桩返回无邻居）不影响任务级成功
    assert info["result"]["devices_failed"] == 1
