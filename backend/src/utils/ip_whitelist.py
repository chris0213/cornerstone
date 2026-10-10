"""
IP 白名单访问控制
支持配置允许访问的 IP/CIDR，限制非白名单 IP 访问系统
"""
import ipaddress
import logging
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


def parse_cidr_or_ip(entry: str) -> Optional[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """解析单个 IP 或 CIDR 网段"""
    entry = entry.strip()
    if not entry:
        return None

    # 如果是单个 IP（没有 /），转换为 /32 或 /128
    if '/' not in entry:
        try:
            ip = ipaddress.ip_address(entry)
            if isinstance(ip, ipaddress.IPv4Address):
                return ipaddress.IPv4Network(f"{entry}/32", strict=False)
            else:
                return ipaddress.IPv6Network(f"{entry}/128", strict=False)
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
    import time

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


def get_client_ip_from_request(request) -> str:
    """从请求中提取客户端真实 IP
    支持 X-Forwarded-For 和 X-Real-IP 代理头
    """
    # 优先从 X-Forwarded-For 获取
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        # X-Forwarded-For 可能包含多个 IP，逗号分隔，第一个是客户端真实 IP
        client_ip = x_forwarded_for.split(",")[0].strip()
        if client_ip:
            return client_ip

    # 其次从 X-Real-IP 获取
    x_real_ip = request.headers.get("X-Real-IP")
    if x_real_ip:
        return x_real_ip.strip()

    # 回退到直接连接 IP
    return request.client.host if request.client else "127.0.0.1"


async def check_ip_allowed(request, db: AsyncSession) -> bool:
    """检查当前请求 IP 是否允许访问"""
    client_ip = get_client_ip_from_request(request)

    # 本地回环地址默认允许（避免配置错误锁死系统）
    if client_ip in ("127.0.0.1", "::1", "localhost"):
        return True

    networks = await get_cached_whitelist(db)

    # 白名单为空 → 允许所有访问（向后兼容）
    if not networks:
        return True

    return is_ip_in_networks(client_ip, networks)
