"""
拓扑发现后台任务管理器（进程内内存实现）

发现是长时间 SSH 采集操作，同步执行会占用 HTTP 请求直至超时。
改为后台任务：启动接口立即返回 task_id，前端轮询进度接口获取状态与统计。
单进程部署场景下使用内存表即可（重启后任务丢失，前端轮询会得到 not_found 并复位）。
"""
import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional, Callable, Awaitable

logger = logging.getLogger("cornerstone")

# 进度回调类型：phase(阶段名), done(已完成设备数), total(总设备数), message(明细)
ProgressCallback = Callable[[str, int, int, str], Awaitable[None]]


class DiscoveryTask:
    def __init__(self, task_id: str, task_type: str, total: int):
        self.id = task_id
        self.type = task_type              # lldp / mac
        self.status = "running"            # running / completed / failed
        self.phase = "准备中"
        self.done = 0
        self.total = total
        self.message = ""
        self.result: Optional[dict] = None
        self.error: Optional[str] = None
        self.created_at = datetime.now()
        self.finished_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        percent = int(self.done * 100 / self.total) if self.total else 0
        if self.status == "completed":
            percent = 100
        return {
            "task_id": self.id,
            "type": self.type,
            "status": self.status,
            "phase": self.phase,
            "done": self.done,
            "total": self.total,
            "percent": percent,
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat(timespec="seconds"),
            "finished_at": self.finished_at.isoformat(timespec="seconds") if self.finished_at else None,
        }


class DiscoveryTaskManager:
    """内存任务表：每个类型同时只允许一个运行中的任务"""

    MAX_HISTORY = 20

    def __init__(self):
        self._tasks: dict[str, DiscoveryTask] = {}
        self._order: list[str] = []

    def _register(self, task: DiscoveryTask) -> None:
        self._tasks[task.id] = task
        self._order.append(task.id)
        # 清理历史任务
        while len(self._order) > self.MAX_HISTORY:
            old_id = self._order.pop(0)
            self._tasks.pop(old_id, None)

    def has_running(self, task_type: str) -> bool:
        return any(
            t.type == task_type and t.status == "running"
            for t in self._tasks.values()
        )

    def create(self, task_type: str, total: int) -> DiscoveryTask:
        task = DiscoveryTask(str(uuid.uuid4())[:8], task_type, total)
        self._register(task)
        return task

    def get(self, task_id: str) -> Optional[DiscoveryTask]:
        return self._tasks.get(task_id)

    def latest(self, task_type: str) -> Optional[DiscoveryTask]:
        for tid in reversed(self._order):
            t = self._tasks.get(tid)
            if t and t.type == task_type:
                return t
        return None


manager = DiscoveryTaskManager()


def make_progress_callback(task: DiscoveryTask) -> ProgressCallback:
    """构建发现服务可用的进度回调（async，事件循环内直接 await）"""

    async def on_progress(phase: str, done: int, total: int, message: str = "") -> None:
        task.phase = phase
        task.done = done
        task.total = total
        task.message = message or ""

    return on_progress


async def run_discovery_task(task: DiscoveryTask, runner: Callable[..., Awaitable[dict]], db_factory) -> None:
    """在后台执行发现任务：独立 DB 会话，异常落任务状态"""
    from src.database import async_session

    async def progress(phase, done, total, message=""):
        task.phase = phase
        task.done = done
        task.total = total
        task.message = message or ""

    try:
        async with db_factory() as db:
            task.result = await runner(db, progress)
        task.status = "completed"
        task.phase = "完成"
        task.done = task.total
    except Exception as e:
        logger.error(f"发现任务 {task.id} 失败: {e}")
        task.status = "failed"
        task.phase = "失败"
        task.error = str(e)
        task.finished_at = datetime.now()
