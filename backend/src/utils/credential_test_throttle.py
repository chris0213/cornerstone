"""凭证测试连接限流（修复 #17：原进程内 dict 在多 worker 下限流失效）。

同一凭证每 N 秒仅允许测试连接 1 次。状态优先存 Redis（多 worker 共享、
重启不分裂），Redis 不可用时回退进程内内存（与 login_throttle / IP 白名单
的 fail-open 哲学一致：限流存储故障不阻断运维正常测试，宁可放宽不可误锁）。

语义与 backups.py 原实现保持一致：
- check 在目标 IP 校验之前调用，命中抛 CredentialTestThrottled(retry_after)；
- mark 在「校验通过、即将发起连接」时调用，不论后续连接成功或失败都占用窗口。
"""
import logging
import time
from typing import Optional

import redis.asyncio as aioredis

from ..config import settings

logger = logging.getLogger(__name__)

# Redis 故障熔断：失败后 30 秒内直接走内存，避免每次测试都等连接超时
_REDIS_RETRY_INTERVAL = 30
_KEY_PREFIX = "cred_test:"

_redis_client: Optional[aioredis.Redis] = None
_redis_down_until: float = 0.0

# 内存回退：credential_id -> 上次放行的 monotonic 时间戳
_memory_last: dict[int, float] = {}
_MEMORY_PRUNE_THRESHOLD = 500


def _get_redis():
    """懒加载 Redis 连接；处于熔断期直接返回 None。"""
    global _redis_client, _redis_down_until
    if time.monotonic() < _redis_down_until:
        return None
    if _redis_client is None:
        try:
            _redis_client = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
            )
        except Exception as e:
            logger.warning(f"[cred-test-throttle] Redis 初始化失败，回退内存: {e}")
            _redis_down_until = time.monotonic() + _REDIS_RETRY_INTERVAL
            return None
    return _redis_client


def _mark_redis_down(e: Exception):
    global _redis_client, _redis_down_until
    logger.warning(f"[cred-test-throttle] Redis 不可用，30 秒内回退内存: {e}")
    _redis_client = None
    _redis_down_until = time.monotonic() + _REDIS_RETRY_INTERVAL


def _prune_memory():
    if len(_memory_last) < _MEMORY_PRUNE_THRESHOLD:
        return
    # 仅清理远超窗口的陈旧条目，避免长期运行无限增长
    now = time.monotonic()
    horizon = max(settings.credential_test_rate_limit_seconds, 1) * 10
    for k in [k for k, ts in _memory_last.items() if now - ts > horizon]:
        _memory_last.pop(k, None)


class CredentialTestThrottled(Exception):
    """测试过于频繁，携带距下次可测试的秒数。"""

    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = max(int(retry_after_seconds), 1)
        super().__init__(f"测试过于频繁，请 {self.retry_after_seconds} 秒后重试")


async def check_credential_test_allowed(credential_id: int, limit_seconds: int) -> None:
    """间隔不足抛 CredentialTestThrottled；limit_seconds<=0 视为不限流。"""
    if limit_seconds <= 0:
        return
    r = _get_redis()
    if r is not None:
        try:
            ttl = await r.ttl(_KEY_PREFIX + str(credential_id))
            if ttl and ttl > 0:
                raise CredentialTestThrottled(ttl)
            return
        except CredentialTestThrottled:
            raise
        except Exception as e:
            _mark_redis_down(e)

    # 内存回退
    last = _memory_last.get(credential_id)
    if last is not None:
        elapsed = time.monotonic() - last
        if elapsed < limit_seconds:
            raise CredentialTestThrottled(int(limit_seconds - elapsed) + 1)


async def mark_credential_test(credential_id: int, limit_seconds: int) -> None:
    """放行后占用窗口（不论后续连接成功或失败）。"""
    if limit_seconds <= 0:
        return
    r = _get_redis()
    if r is not None:
        try:
            await r.set(_KEY_PREFIX + str(credential_id), "1", ex=limit_seconds)
            return
        except Exception as e:
            _mark_redis_down(e)

    _memory_last[credential_id] = time.monotonic()
    _prune_memory()
