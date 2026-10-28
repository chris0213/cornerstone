"""登录限流/锁定（防暴力破解）

双维度限流，Redis 优先存储（多 worker 共享、重启不清零），Redis 不可用时
回退到进程内内存（与白名单中间件 fail-open 哲学一致，限流故障不阻断登录）：

- 用户名维度：15 分钟窗口内累计 5 次失败 → 锁定至窗口结束（每次失败刷新窗口）；
  登录成功即清零。只按「失败次数」计，成功登录会重置，正常用户无感。
- IP 维度：10 分钟滑窗内累计 20 次失败 → 限流（429），防换用户名密码喷洒。
  仅失败计数，成功登录会清零，避免 NAT 出口被误伤。

错误验证码只计 IP 不计用户名：攻击者无法借验证码环节锁定他人账号。
"""
import logging
import time
from typing import Optional, Tuple

import redis.asyncio as aioredis

from ..config import settings

logger = logging.getLogger(__name__)

# 阈值与窗口
USERNAME_MAX_FAILURES = 5
USERNAME_LOCK_SECONDS = 15 * 60
IP_MAX_FAILURES = 20
IP_WINDOW_SECONDS = 10 * 60

# Redis 故障熔断：失败后 30 秒内直接走内存，避免每次登录都等超时
_REDIS_RETRY_INTERVAL = 30

_redis_client: Optional[aioredis.Redis] = None
_redis_down_until: float = 0.0

# 内存回退存储：key -> (失败次数, 窗口起点时间戳)
_memory_user_failures: dict[str, Tuple[int, float]] = {}
_memory_ip_failures: dict[str, Tuple[int, float]] = {}
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
            logger.warning(f"[login-throttle] Redis 初始化失败，回退内存: {e}")
            _redis_down_until = time.monotonic() + _REDIS_RETRY_INTERVAL
            return None
    return _redis_client


def _mark_redis_down(e: Exception):
    global _redis_down_until
    logger.warning(f"[login-throttle] Redis 不可用，30 秒内回退内存: {e}")
    global _redis_client
    _redis_client = None
    _redis_down_until = time.monotonic() + _REDIS_RETRY_INTERVAL


def _prune_memory(store: dict[str, Tuple[int, float]], window: int):
    """清理已过窗口的内存条目，防止长期运行下无限增长。"""
    if len(store) < _MEMORY_PRUNE_THRESHOLD:
        return
    now = time.monotonic()
    for k in [k for k, (_, start) in store.items() if now - start > window]:
        store.pop(k, None)


def _memory_hit(store: dict[str, Tuple[int, float]], key: str, window: int, limit: int) -> bool:
    """内存版判定：窗口内失败次数达到阈值即命中。"""
    info = store.get(key)
    if not info:
        return False
    count, start = info
    if time.monotonic() - start > window:
        store.pop(key, None)
        return False
    return count >= limit


def _memory_record(store: dict[str, Tuple[int, float]], key: str, window: int, limit: int):
    """内存版计数：首次失败开窗，达到阈值后刷新窗口（延长锁定）。"""
    now = time.monotonic()
    count, start = store.get(key, (0, now))
    if now - start > window or count >= limit:
        count, start = 0, now
    store[key] = (count + 1, start)
    _prune_memory(store, window)


class LoginThrottled(Exception):
    """登录被限流/锁定，携带 HTTP 状态码与提示。"""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


async def check_login_allowed(username: str, ip: Optional[str]) -> None:
    """登录前检查：用户名锁定(423) 或 IP 限流(429) 时抛 LoginThrottled。"""
    r = _get_redis()
    if r is not None:
        try:
            ucount = await r.get(f"login_fail:user:{username}")
            if ucount and int(ucount) >= USERNAME_MAX_FAILURES:
                raise LoginThrottled(423, "账号已被锁定，请稍后重试")
            if ip:
                icount = await r.get(f"login_fail:ip:{ip}")
                if icount and int(icount) >= IP_MAX_FAILURES:
                    raise LoginThrottled(429, "登录尝试过于频繁，请稍后再试")
            return
        except LoginThrottled:
            raise
        except Exception as e:
            _mark_redis_down(e)

    # 内存回退
    if _memory_hit(_memory_user_failures, username, USERNAME_LOCK_SECONDS, USERNAME_MAX_FAILURES):
        raise LoginThrottled(423, "账号已被锁定，请稍后重试")
    if ip and _memory_hit(_memory_ip_failures, ip, IP_WINDOW_SECONDS, IP_MAX_FAILURES):
        raise LoginThrottled(429, "登录尝试过于频繁，请稍后再试")


async def record_login_failure(username: Optional[str], ip: Optional[str]) -> None:
    """记录一次认证失败（用户名 + IP 双计数）。username 可为空（如仅验证码失败）。"""
    r = _get_redis()
    if r is not None:
        try:
            pipe = r.pipeline()
            if username:
                ukey = f"login_fail:user:{username}"
                pipe.incr(ukey)
                pipe.expire(ukey, USERNAME_LOCK_SECONDS)
            if ip:
                ikey = f"login_fail:ip:{ip}"
                pipe.incr(ikey)
                pipe.expire(ikey, IP_WINDOW_SECONDS)
            await pipe.execute()
            return
        except Exception as e:
            _mark_redis_down(e)

    if username:
        _memory_record(_memory_user_failures, username, USERNAME_LOCK_SECONDS, USERNAME_MAX_FAILURES)
    if ip:
        _memory_record(_memory_ip_failures, ip, IP_WINDOW_SECONDS, IP_MAX_FAILURES)


async def reset_login_failures(username: Optional[str], ip: Optional[str] = None) -> None:
    """登录成功后清零计数（用户名 + 该 IP），避免误伤正常用户。"""
    r = _get_redis()
    if r is not None:
        try:
            keys = []
            if username:
                keys.append(f"login_fail:user:{username}")
            if ip:
                keys.append(f"login_fail:ip:{ip}")
            if keys:
                await r.delete(*keys)
            return
        except Exception as e:
            _mark_redis_down(e)

    if username:
        _memory_user_failures.pop(username, None)
    if ip:
        _memory_ip_failures.pop(ip, None)
