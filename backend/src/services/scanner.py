"""IP地址扫描服务"""
import asyncio
import socket
from datetime import datetime
from typing import AsyncGenerator, Optional, List, Dict
from ipaddress import IPv4Network
import logging

logger = logging.getLogger(__name__)

# 默认 TCP 探测端口组（服务器/网络设备/办公设备全覆盖）
DEFAULT_TCP_PORTS = [22, 80, 443, 8080, 445, 139, 161, 3389, 5060]


def parse_custom_ports(raw: Optional[str]) -> Optional[List[int]]:
    """把字符串 "22,80,443" 解析为 [22, 80, 443]，无效值跳过；None/空串返回 None（用默认）"""
    if not raw:
        return None
    ports: List[int] = []
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            p = int(piece)
            if 1 <= p <= 65535:
                ports.append(p)
        except ValueError:
            continue
    return ports or None

# 尝试导入scapy用于ARP探测，失败时静默降级
try:
    from scapy.all import ARP, Ether, srp
    HAS_SCapy = True
except ImportError as e:
    HAS_SCapy = False
    logger.warning(f"scapy not installed: {e}")

# 尝试导入ping3用于ICMP探测
try:
    import ping3
    HAS_PING3 = True
except ImportError as e:
    HAS_PING3 = False
    logger.warning(f"ping3 not installed: {e}")


class ScanResult:
    """扫描结果"""
    def __init__(self, ip: str):
        self.ip = ip
        self.is_online = False
        self.method: str = "none"
        self.open_ports: List[int] = []
        self.mac_address: Optional[str] = None
        self.duration_ms: int = 0


async def _ping_icmp(ip: str, timeout: float) -> bool:
    """ICMP Ping探测"""
    if not HAS_PING3:
        logger.debug(f"ping3 not available, skipping ICMP ping for {ip}")
        return False
    
    try:
        delay = await asyncio.to_thread(ping3.ping, ip, timeout=timeout)
        result = delay is not None and delay > 0
        if result:
            logger.debug(f"ICMP ping successful for {ip}, delay: {delay}ms")
        return result
    except Exception as e:
        logger.debug(f"ICMP ping failed for {ip}: {e}")
        return False


async def _probe_tcp(ip: str, ports: List[int], timeout: float) -> List[int]:
    """TCP端口探测"""
    open_ports = []
    semaphore = asyncio.Semaphore(10)  # 限制并发
    
    async def probe_port(port: int) -> Optional[int]:
        async with semaphore:
            try:
                conn = asyncio.open_connection(ip, port)
                _, writer = await asyncio.wait_for(conn, timeout=timeout)
                writer.close()
                await writer.wait_closed()
                logger.debug(f"TCP port {port} open on {ip}")
                return port
            except asyncio.TimeoutError:
                return None
            except ConnectionRefusedError:
                return None
            except OSError as e:
                logger.debug(f"TCP probe error for {ip}:{port}: {e}")
                return None
    
    tasks = [probe_port(port) for port in ports]
    results = await asyncio.gather(*tasks)
    open_ports = [p for p in results if p is not None]
    return open_ports


async def _probe_arp(ip: str, timeout: float) -> tuple[bool, Optional[str]]:
    """ARP探测（需要root权限）"""
    if not HAS_SCapy:
        logger.debug(f"scapy not available, skipping ARP probe for {ip}")
        return False, None
    
    try:
        # 创建ARP请求包
        arp_request = ARP(pdst=ip)
        broadcast = Ether(dst="ff:ff:ff:ff:ff:ff")
        arp_broadcast = broadcast / arp_request
        
        # 发送并接收响应
        result = await asyncio.to_thread(
            srp, arp_broadcast, timeout=timeout, verbose=0
        )
        
        if result and result[0]:
            for sent, received in result[0]:
                logger.debug(f"ARP response from {ip}, MAC: {received.hwsrc}")
                return True, received.hwsrc
        return False, None
    except PermissionError:
        logger.warning(f"Permission denied for ARP probe on {ip} - need root privileges")
        return False, None
    except Exception as e:
        logger.debug(f"ARP probe failed for {ip}: {e}")
        return False, None


async def _probe_hostname(ip: str, timeout: float) -> Optional[str]:
    """尝试获取主机名"""
    try:
        hostname = await asyncio.to_thread(
            socket.gethostbyaddr, ip
        )
        return hostname[0] if hostname else None
    except Exception:
        return None


async def probe_single_ip(ip: str, tcp_ports: List[int] = None, timeout: float = 3.0) -> Dict:
    """
    多维度探测单个IP
    
    返回:
    {
        "ip": "192.0.2.1",
        "is_online": True/False,
        "method": "tcp/icmp/arp/none",
        "open_ports": [22, 445],
        "mac_address": "aa:bb:cc:dd:ee:ff" or None,
        "duration_ms": 120
    }
    """
    if tcp_ports is None:
        tcp_ports = DEFAULT_TCP_PORTS
    
    start_time = datetime.now()
    result = {
        "ip": ip,
        "is_online": False,
        "method": "none",
        "open_ports": [],
        "mac_address": None,
        "hostname": None,
        "duration_ms": 0
    }
    
    # 按优先级探测：ARP -> TCP -> ICMP
    # 1. ARP探测（局域网最准）
    arp_online, mac = await _probe_arp(ip, timeout / 3)
    if arp_online:
        result["is_online"] = True
        result["method"] = "arp"
        result["mac_address"] = mac
    else:
        # 2. TCP端口探测
        open_ports = await _probe_tcp(ip, tcp_ports, timeout / 3)
        if open_ports:
            result["is_online"] = True
            result["method"] = "tcp"
            result["open_ports"] = open_ports
        else:
            # 3. ICMP Ping
            if await _ping_icmp(ip, timeout / 3):
                result["is_online"] = True
                result["method"] = "icmp"
    
    # 如果设备在线，尝试获取主机名
    if result["is_online"]:
        result["hostname"] = await _probe_hostname(ip, 0.5)
    
    duration = (datetime.now() - start_time).total_seconds() * 1000
    result["duration_ms"] = int(duration)
    
    return result


async def scan_prefix(
    prefix_network: str,
    ip_records: List[Dict],
    max_concurrent: int = 30,
    tcp_ports: Optional[List[int]] = None,
) -> AsyncGenerator[Dict, None]:
    """
    扫描整个子网（全量展开，包括未登记 IP）

    Args:
        prefix_network: CIDR格式的子网，如 "192.0.2.0/24"
        ip_records: 已有的IP记录列表（用于关联 record_id，不是扫描范围）
        max_concurrent: 最大并发数
        tcp_ports: 自定义 TCP 探测端口；None 则用 DEFAULT_TCP_PORTS
    """
    try:
        network = IPv4Network(prefix_network)
    except ValueError:
        raise ValueError(f"Invalid network: {prefix_network}")

    # 安全阈值：/16（65534 主机）以上拒绝，避免打爆网络
    if network.prefixlen < 16:
        raise ValueError(f"Network too large for scan: /{network.prefixlen} (max /16 allowed)")

    ports = tcp_ports or DEFAULT_TCP_PORTS
    logger.info(f"Starting scan for network: {prefix_network} ports={ports}")
    
    # 创建IP到记录的映射
    ip_to_record = {record["address"]: record for record in ip_records}
    
    # 获取所有可扫描的IP（排除网络地址和广播地址）
    all_ips = [str(ip) for ip in network.hosts()]
    
    total = len(all_ips)
    scanned = 0
    online_count = 0
    
    semaphore = asyncio.Semaphore(max_concurrent)
    start_time = datetime.now()
    
    # 创建扫描任务
    async def scan_ip(ip: str):
            nonlocal scanned, online_count

            async with semaphore:
                result = await probe_single_ip(ip, tcp_ports=ports)
                scanned += 1
            
            if result["is_online"]:
                online_count += 1
                logger.debug(f"Online: {ip} via {result['method']}")
            
            # 关联数据库记录ID
            if ip in ip_to_record:
                result["record_id"] = ip_to_record[ip]["id"]
            
            # 计算进度
            percent = (scanned / total) * 100
            
            # 返回进度信息
            progress_info = {
                "type": "progress",
                "total": total,
                "scanned": scanned,
                "online": online_count,
                "percent": round(percent, 1),
                "current_ip": ip
            }
            
            # 返回单IP结果
            result_info = {
                "type": "result",
                **result
            }
            
            return progress_info, result_info
    
    # 并发扫描所有IP
    tasks = [scan_ip(ip) for ip in all_ips]
    
    # 收集并yield结果
    for task in asyncio.as_completed(tasks):
        progress_info, result_info = await task
        yield progress_info
        yield result_info
    
    # 扫描完成
    duration = (datetime.now() - start_time).total_seconds()
    logger.info(f"Scan completed for {prefix_network}: {online_count}/{total} online, duration: {duration:.1f}s")
    
    yield {
        "type": "done",
        "total": total,
        "online": online_count,
        "offline": total - online_count,
        "duration_seconds": round(duration, 1)
    }


# 扫描任务存储（内存中）
scan_tasks: Dict[str, dict] = {}


def get_scan_task(task_id: str):
    """获取扫描任务"""
    return scan_tasks.get(task_id)


def set_scan_task(task_id: str, task):
    """设置扫描任务"""
    scan_tasks[task_id] = task


def remove_scan_task(task_id: str):
    """移除扫描任务"""
    if task_id in scan_tasks:
        del scan_tasks[task_id]
