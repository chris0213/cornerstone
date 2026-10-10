"""告警 WebSocket 实时推送

内存连接池 + 广播：告警落库后立即推送给所有在线前端，
使预警红点/通知不依赖页面刷新。单进程部署下足够；
若未来多 worker 部署，需改为 Redis pub/sub 分发。
"""
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class AlertWSManager:
    """在线客户端连接池"""

    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)

    @property
    def count(self) -> int:
        return len(self._connections)

    async def broadcast(self, message: dict) -> None:
        """向所有在线客户端推送；发送失败的连接静默清理"""
        stale = []
        for ws in self._connections:
            try:
                await ws.send_json(message)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)


# 模块级单例：服务进程内共享
alert_ws_manager = AlertWSManager()


async def broadcast_new_alert(record) -> None:
    """新告警创建后广播给在线前端。

    绝不抛出异常：推送失败不得影响告警落库与通知发送。
    """
    try:
        await alert_ws_manager.broadcast({
            "type": "new_alert",
            "id": record.id,
            "severity": record.severity,
            "alert_type": record.alert_type,
            "message": record.message,
            "device_id": record.device_id,
        })
    except Exception:
        logger.exception("告警 WebSocket 广播失败")
