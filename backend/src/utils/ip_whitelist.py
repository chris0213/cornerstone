"""
IP 白名单访问控制
支持配置允许访问的 IP/CIDR，限制非白名单 IP 访问系统

安全模型：
- 仅当直连 IP 命中可信代理列表（TRUSTED_PROXIES 环境变量）时，
  才采信 X-Forwarded-For / X-Real-IP 头；否则一律使用直连 IP。
  防止客户端伪造 XFF 头绕过白名单（直连场景下 XFF 不可信）。
- 本地回环地址默认放行，作为配置错误的最后一道自救通道。
- 应急开关：设置环境变量 IP_WHITELIST_DISABLED=true 可临时禁用白名单。
"""
import ipaddress
import logging
import os
import time
from typing import List, Optional, Set
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import json

from ..models.setting import Setting

logger = logging.getLogger(__name__)

# 缓存白名单，避免每次查询数据库
# 格式：(cache_timestamp, allowed_ips, allowed_networks)
# 每 30 秒刷新一次缓存
_whitelist_cache: tuple[float, Set[str], List[ipaddress.IPv4Network | ipaddress.IPv6Network]] | None = None
CACHE_TTL = 30  # seconds

# 应急开关：环境变量为 "1"/"true"/"yes"（大小写不敏感）时禁用白名单检查
IP_WHITELIST_DISABLED_ENV = "IP_WHITELIST_DISABLED"

# 可信代理：从 TRUSTED_PROXIES 读取，逗号分隔的 IP/CIDR。
# 直连 IP 命中可信代理时才采信 X-Forwarded-For / X-Real-IP。
_trusted_proxies_cache: Optional[List[ipaddress.IPv4Network | ipaddress.IPv6Network]] = None


def is_whitelist_disabled() -> bool:
    """应急开关：白名单是否被环境变量临时禁用。"""
    return os.environ.get(IP_WHITELIST_DISABLED_ENV, "").strip().lower() in ("1", "true", "yes")


def _get_trusted_proxies() -> List[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """解析可信代理列表（每次调用重读环境变量，便于测试；解析失败静默忽略）。"""
    raw = os.environ.get("TRUSTED_PROXIES", "").strip()
    if not raw:
        return []
    networks: List[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for entry in raw.split(","):
        net = parse_cidr_or_ip(entry)
        if net:
            networks.append(net)
    return networks


def is_trusted_proxy(client_ip: str) -> bool:
    """判断直连 IP 是否为可信代理。"""
    if not client_ip:
        return False
    try:
        ip = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    for net in _get_trusted_proxies():
        if ip in net:
            return True
    return False


def get_direct_ip(request) -> str:
    """获取 TCP 直连 IP（不可伪造）。"""
    return request.client.host if request.client else "127.0.0.1"


def get_client_ip_with_source(request) -> tuple[str, str]:
    """从请求中提取客户端 IP 及其来源。

    安全规则：
    - 仅当直连 IP 命中可信代理（TRUSTED_PROXIES）时，才依次采信
      X-Forwarded-For（取第一个）与 X-Real-IP；
    - 否则一律返回 TCP 直连 IP，忽略代理头（防伪造）。

    返回 (client_ip, source)，source ∈ {"x-forwarded-for", "x-real-ip", "direct"}。
    """
    direct_ip = get_direct_ip(request)

    if is_trusted_proxy(direct_ip):
        x_forwarded_for = request.headers.get("X-Forwarded-For")
        if x_forwarded_for:
            # X-Forwarded-For 可能包含多个 IP，逗号分隔，第一个是客户端真实 IP
            client_ip = x_forwarded_for.split(",")[0].strip()
            if client_ip:
                return client_ip, "x-forwarded-for"

        x_real_ip = request.headers.get("X-Real-IP")
        if x_real_ip and x_real_ip.strip():
            return x_real_ip.strip(), "x-real-ip"

    return direct_ip, "direct"


def get_client_ip_from_request(request) -> str:
    """从请求中提取客户端 IP（不含来源标记，兼容既有调用方）。

    可信代理规则见 get_client_ip_with_source。
    """
    return get_client_ip_with_source(request)[0]


def parse_cidr_or_ip(entry: str) -> Optional[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """解析单个 IP 或 CIDR 网段"""
    entry = entry.strip()
    if not entry:
        return None

    # 如果是单个 IP（没有 /），转换为 /32 或 /128
    if '/' not in entry:
        try:
            ipaddress.ip_address(entry)
            return ipaddress.ip_network(f"{entry}/32", strict=False)
        except ValueError:
            logger.warning(f"Invalid IP address: {entry}")
            return None

    # CIDR 网段
    try:
        return ipaddress.ip_network(entry, strict=False)
    except ValueError:
        logger.warning(f"Invalid CIDR: {entry}")
        return None


def is_ip_in_networks(client_ip: str, networks: List[ipaddress.IPv4Network | ipaddress.IPv6Network]) -> bool:
    """检查客户端 IP 是否在允许网段中"""
    try:
        ip_obj = ipaddress.ip_address(client_ip)
        for net in networks:
            if ip_obj in net:
                return True
        return False
    except ValueError:
        logger.warning(f"Invalid client IP: {client_ip}")
        return False


def parse_whitelist_lines(raw: str) -> tuple[List[ipaddress.IPv4Network | ipaddress.IPv6Network], List[int]]:
    """逐行解析白名单文本（不兼容 JSON 格式，专供保存校验）。

    返回 (networks, invalid_line_numbers)：networks 为解析成功的网段，
    invalid_line_numbers 为非法行的行号（1 起）。
    """
    networks: List[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    invalid_lines: List[int] = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        net = parse_cidr_or_ip(entry)
        if net:
            networks.append(net)
        else:
            invalid_lines.append(lineno)
    return networks, invalid_lines


def parse_whitelist_value(raw: str) -> List[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """解析白名单存储值（JSON 数组或换行分隔文本）为网络列表"""
    raw = (raw or "").strip()
    if not raw:
        return []

    entries: List[str]
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            entries = [str(e) for e in parsed]
        elif isinstance(parsed, str):
            entries = [line.strip() for line in parsed.splitlines() if line.strip()]
        else:
            return []
    except json.JSONDecodeError:
        entries = [line.strip() for line in raw.splitlines() if line.strip()]

    networks: List[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for entry in entries:
        net = parse_cidr_or_ip(entry)
        if net:
            networks.append(net)
    return networks


async def get_whitelist_from_db(db: AsyncSession) -> List[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """从数据库读取白名单配置"""
    result = await db.execute(select(Setting).filter(Setting.key == "security.ip_whitelist"))
    setting = result.scalars().first()

    if not setting or not setting.value:
        return []

    return parse_whitelist_value(setting.value)


async def get_cached_whitelist(db: AsyncSession) -> List[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """获取缓存的白名单，过期则刷新"""
    global _whitelist_cache

    now = time.time()

    if _whitelist_cache is not None:
        cache_time, _, networks = _whitelist_cache
        if now - cache_time < CACHE_TTL:
            return networks

    # 缓存过期，重新加载
    networks = await get_whitelist_from_db(db)
    # 提取所有允许的 IP 字符串（用于快速匹配单个 IP）
    allowed_ips: Set[str] = set()
    for net in networks:
        if net.prefixlen == 32 or net.prefixlen == 128:
            # 单个 IP
            allowed_ips.add(str(net.network_address))

    _whitelist_cache = (now, allowed_ips, networks)
    logger.info(f"[IP白名单] 重新加载配置，共 {len(networks)} 个允许网段")
    return networks


def invalidate_cache():
    """强制失效缓存，下次请求重新加载"""
    global _whitelist_cache
    _whitelist_cache = None
    logger.info("[IP白名单] 缓存已失效，下次请求将重新加载")


async def check_ip_allowed(request, db: AsyncSession) -> bool:
    """检查当前请求 IP 是否允许访问"""
    # 应急开关：环境变量禁用白名单时全部放行
    if is_whitelist_disabled():
        return True

    client_ip = get_client_ip_from_request(request)

    # 本地回环地址默认允许（避免配置错误锁死系统）
    if client_ip in ("127.0.0.1", "::1", "localhost"):
        return True

    networks = await get_cached_whitelist(db)

    # 白名单为空 → 允许所有访问（向后兼容）
    if not networks:
        return True

    return is_ip_in_networks(client_ip, networks)


async def check_ws_ip_allowed(websocket) -> bool:
    """WebSocket 白名单检查（HTTP middleware 不覆盖 WS，需在 WS 端点调用）。

    与 HTTP 语义一致：仅当 TCP 直连 IP 命中可信代理（TRUSTED_PROXIES）时，
    才采信 X-Forwarded-For（取第一个）/ X-Real-IP；否则用直连 IP。
    应急开关与回环放行语义与 HTTP 一致。
    """
    if is_whitelist_disabled():
        return True

    direct_ip = websocket.client.host if websocket.client else "127.0.0.1"
    if direct_ip in ("127.0.0.1", "::1", "localhost"):
        return True

    if is_trusted_proxy(direct_ip):
        # 可信反代：采信转发头，与 HTTP 侧 get_client_ip_with_source 相同的优先级
        xff = websocket.headers.get("x-forwarded-for")
        if xff:
            client_ip = xff.split(",")[0].strip()
            if client_ip:
                return _ws_ip_in_whitelist(client_ip)
        x_real_ip = websocket.headers.get("x-real-ip")
        if x_real_ip and x_real_ip.strip():
            return _ws_ip_in_whitelist(x_real_ip.strip())

    return _ws_ip_in_whitelist(direct_ip)


def _ws_ip_in_whitelist(client_ip: str) -> bool:
    """WS 白名单匹配（复用进程内缓存；无缓存时放行，首次 HTTP 请求会建立缓存）。"""
    if client_ip in ("127.0.0.1", "::1", "localhost"):
        return True
    if _whitelist_cache is None:
        return True
    networks = _whitelist_cache[2]
    if not networks:
        return True
    return is_ip_in_networks(client_ip, networks)
