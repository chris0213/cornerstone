"""告警 WebSocket 实时推送

内存连接池 + 按租户广播：告警落库后立即推送给同租户的在线前端，
使预警红点/通知不依赖页面刷新。单进程部署下足够；
若未来多 worker 部署，需改为 Redis pub/sub 分发。

平台超管连接接收全量告警（与「超管可跨租户查看」的读语义一致），
普通租户连接只收本租户告警。
"""
import logging
from dataclasses import dataclass
from typing import Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass
class _Connection:
    websocket: WebSocket
    tenant_id: Optional[int]
    is_superuser: bool


class AlertWSManager:
    """在线客户端连接池（按租户隔离）"""

    def __init__(self):
        self._connections: list[_Connection] = []

    async def connect(
        self,
        websocket: WebSocket,
        tenant_id: Optional[int] = None,
        is_superuser: bool = False,
    ) -> None:
        await websocket.accept()
        self.register(websocket, tenant_id, is_superuser)

    def register(
        self,
        websocket: WebSocket,
        tenant_id: Optional[int],
        is_superuser: bool = False,
    ) -> None:
        """登记已 accept 的连接归属（用于「先 accept 再鉴权」的握手流程）。"""
        self._connections.append(_Connection(websocket, tenant_id, is_superuser))

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections = [c for c in self._connections if c.websocket is not websocket]

    @property
    def count(self) -> int:
        return len(self._connections)

    async def broadcast(self, message: dict, tenant_id: Optional[int] = None) -> None:
        """只推送给同租户连接；超管连接收全量。

        tenant_id 为 None（系统级消息）时仅推给超管连接。
        发送失败的连接静默清理。
        """
        stale = []
        for conn in list(self._connections):
            if not (conn.is_superuser or conn.tenant_id == tenant_id):
                continue
            try:
                await conn.websocket.send_json(message)
            except Exception:
                stale.append(conn.websocket)
        for ws in stale:
            self.disconnect(ws)


# 模块级单例：服务进程内共享
alert_ws_manager = AlertWSManager()


async def broadcast_new_alert(record) -> None:
    """新告警创建后广播给同租户在线前端。

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
        }, tenant_id=getattr(record, "tenant_id", None))
    except Exception:
        logger.exception("告警 WebSocket 广播失败")
