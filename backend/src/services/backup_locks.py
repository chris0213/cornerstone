"""设备级备份互斥锁：防止同一设备被 定时/手动/批量 并发 SSH。

老设备通常只允许单个管理会话，并发连接会踢掉在线管理员，
且「查最新版本→+1→插入」的版本号写入也依赖串行化保证不重复。
单进程部署（uvicorn + APScheduler 同进程）下本锁即为全量互斥。
"""
import asyncio
from typing import Dict

_device_locks: Dict[int, asyncio.Lock] = {}


def get_device_backup_lock(device_id: int) -> asyncio.Lock:
    """获取（或惰性创建）某设备的备份互斥锁。"""
    lock = _device_locks.get(device_id)
    if lock is None:
        lock = asyncio.Lock()
        _device_locks[device_id] = lock
    return lock
