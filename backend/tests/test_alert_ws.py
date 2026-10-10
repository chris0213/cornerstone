"""告警 WebSocket 推送：连接池管理与广播的单元测试（纯 mock，不启动 lifespan）"""
import asyncio
from types import SimpleNamespace

import pytest

from src.services.alert_ws import AlertWSManager, broadcast_new_alert


class FakeWebSocket:
    """记录发送内容的 WebSocket 替身"""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.sent: list[dict] = []
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def send_json(self, message: dict):
        if self.fail:
            raise RuntimeError("connection closed")
        self.sent.append(message)


def test_connect_and_disconnect():
    async def run():
        manager = AlertWSManager()
        ws = FakeWebSocket()
        await manager.connect(ws)
        assert ws.accepted is True
        assert manager.count == 1

        manager.disconnect(ws)
        assert manager.count == 0
        # 重复断开幂等
        manager.disconnect(ws)
        assert manager.count == 0

    asyncio.run(run())


def test_broadcast_delivers_to_all_and_cleans_stale():
    async def run():
        manager = AlertWSManager()
        healthy, broken = FakeWebSocket(), FakeWebSocket(fail=True)
        await manager.connect(healthy)
        await manager.connect(broken)

        await manager.broadcast({"type": "new_alert", "id": 1})

        assert healthy.sent == [{"type": "new_alert", "id": 1}]
        # 发送失败的连接被静默清理
        assert manager.count == 1
        assert broken not in manager._connections

    asyncio.run(run())


def test_broadcast_new_alert_never_raises(monkeypatch):
    """广播失败不得影响告警落库路径（吞掉所有异常）"""

    async def boom(_):
        raise RuntimeError("池炸了")

    monkeypatch.setattr(
        "src.services.alert_ws.alert_ws_manager.broadcast", boom
    )
    record = SimpleNamespace(
        id=7, severity="critical", alert_type="latency",
        message="延迟过高", device_id=3,
    )
    asyncio.run(broadcast_new_alert(record))  # 不抛异常即通过
