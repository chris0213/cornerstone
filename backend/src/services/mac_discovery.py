"""
MAC/ARP 表发现：通过交换机 MAC 地址表 + ARP 表发现下挂终端
解决「交换机下挂服务器不开 LLDP 无法发现」的问题：
LLDP/CDP 负责发现网络设备骨架，MAC/ARP 负责把接入端口下的终端（服务器等）
关联到 IPAM/资产库，自动建立「交换机-服务器」链路；未匹配的记录为未知接入。
"""
import asyncio
import logging
import re
from datetime import datetime
from typing import Optional, Tuple, Callable, Awaitable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.device import Device
from src.models.device_link import DeviceLink
from src.models.ip_address import IPAddress
from src.models.discovery import DiscoveryUnknownEndpoint
from src.services.lldp_discovery import (
    DISCOVERY_CONCURRENCY,
    get_all_credentials,
    get_device_credential,
    build_device_info,
    get_netmiko_device_type,
    update_or_create_device_links,
)
from src.utils.device_connection import connect_device

logger = logging.getLogger("cornerstone")

# 单端口学习 MAC 数超过该值视为 trunk/上联口，跳过（接入端口通常只有少量终端 MAC）
MAX_MACS_PER_ACCESS_PORT = 8


# ---------- 归一化 ----------

def normalize_mac(mac: str) -> Optional[str]:
    """MAC 归一化为 12 位小写十六进制
    兼容 aaaa-bbbb-cccc / aabb.cc00.0100 / aa:bb:cc:dd:ee:ff
    """
    hexed = re.sub(r'[^0-9a-fA-F]', '', mac or '')
    return hexed.lower() if len(hexed) == 12 else None


def mac_variants(mac_norm: str) -> list:
    """生成常见 MAC 书写格式，用于与 IPAM 记录比对"""
    h = mac_norm
    return [
        h,
        h.upper(),
        f"{h[0:4]}-{h[4:8]}-{h[8:12]}",
        f"{h[0:4]}.{h[4:8]}.{h[8:12]}",
        ":".join(h[i:i + 2] for i in range(0, 12, 2)),
        "-".join(h[i:i + 2] for i in range(0, 12, 2)),
    ]


def intf_tail(name: str) -> str:
    """接口名尾段归一化（GigabitEthernet0/0/1 / GE0/0/1 / Gi0/0/1 -> 0/0/1；Eth-Trunk1 -> 1）"""
    m = re.search(r'(\d+(?:/\d+)*)$', (name or '').strip())
    return m.group(1) if m else (name or '').strip().lower()


# ---------- 命令输出解析 ----------

def _parse_mac_line(line: str) -> Optional[dict]:
    """解析单行 MAC 表项，兼容华为/H3C（MAC 在首列）与思科（VLAN 在首列）"""
    tokens = line.split()
    if len(tokens) < 4:
        return None

    mac_idx = None
    for i, token in enumerate(tokens[:2]):  # MAC 只会出现在前两列
        if normalize_mac(token):
            mac_idx = i
            break
    if mac_idx is None:
        return None

    mac = normalize_mac(tokens[mac_idx])
    # 华为: [mac, vlan, port, type] -> 端口在倒数第2列；H3C: [mac, vlan, state, port, aging] 同理
    # 思科: [vlan, mac, type, port] -> 端口在最后1列
    port = tokens[-2] if mac_idx == 0 else tokens[-1]
    if not port or 'cpu' in port.lower():
        return None
    if 'static' in line.lower():  # 静态表项（系统MAC/网关）不作为终端依据
        return None
    return {'mac': mac, 'port': port}


def parse_mac_table(output: str) -> list:
    """解析 MAC 地址表输出，返回 [{mac, port}]"""
    entries = []
    seen = set()
    for line in (output or '').splitlines():
        entry = _parse_mac_line(line)
        if entry:
            key = (entry['mac'], entry['port'])
            if key not in seen:
                seen.add(key)
                entries.append(entry)
    return entries


def parse_arp_table(output: str) -> dict:
    """解析 ARP 表输出，返回 {mac_norm: ip}"""
    mapping = {}
    pattern = re.compile(
        r'^\s*(?:Internet\s+)?'
        r'(\d{1,3}(?:\.\d{1,3}){3})\s+'
        r'(?:\d+\s+|-\s+)?'  # 思科在 IP 与 MAC 之间有 Age(min) 列
        r'([0-9a-fA-F]{4}[-.][0-9a-fA-F]{4}[-.][0-9a-fA-F]{4})'
    )
    for line in (output or '').splitlines():
        m = pattern.match(line)
        if m:
            mac = normalize_mac(m.group(2))
            if mac and mac not in mapping:
                mapping[mac] = m.group(1)
    return mapping


def _is_cli_error(output: str) -> bool:
    low = (output or '').lower()
    return (
        'unrecognized' in low
        or 'invalid input' in low
        or 'incomplete command' in low
        or 'unknown command' in low
        or low.strip().startswith('error%')
    )


def get_mac_arp_commands(device_type: str) -> dict:
    """按厂商返回 MAC 表 / ARP 表命令（按优先级排列）"""
    if device_type in ("huawei", "hp_comware"):
        return {
            "mac": ["display mac-address", "display mac-address dynamic"],
            "arp": ["display arp all", "display arp"],
        }
    return {
        "mac": ["show mac address-table", "show mac-address-table"],
        "arp": ["show ip arp", "show arp"],
    }


def collect_mac_arp_sync(device_info: dict, mac_cmds: list, arp_cmds: list) -> Tuple[Optional[dict], Optional[str]]:
    """在线程中执行同步 SSH 采集 MAC 表与 ARP 表（不阻塞事件循环）"""
    conn = connect_device(device_info)
    if conn is None:
        return None, f"SSH 连接失败（{device_info['ip']}，认证失败或不可达）"
    try:
        mac_entries = []
        for cmd in mac_cmds:
            try:
                out = conn.send_command(cmd, read_timeout=60)
            except Exception:
                out = None
            if out and not _is_cli_error(out):
                mac_entries = parse_mac_table(out)
                if mac_entries:
                    break

        arp_map = {}
        for cmd in arp_cmds:
            try:
                out = conn.send_command(cmd, read_timeout=60)
            except Exception:
                out = None
            if out and not _is_cli_error(out):
                arp_map = parse_arp_table(out)
                if arp_map:
                    break

        if not mac_entries:
            return None, "未获取到 MAC 地址表（设备不支持或无动态表项）"
        return {"mac_entries": mac_entries, "arp_map": arp_map}, None
    finally:
        try:
            conn.disconnect()
        except Exception:
            pass


# ---------- 终端关联 ----------

async def resolve_endpoint_device(db: AsyncSession, mac_norm: str, ip: Optional[str]) -> Optional[Device]:
    """终端 MAC/IP -> IPAM -> 设备
    1. IP 是某设备的管理IP
    2. IP 在 IPAM 中已关联业务设备
    3. MAC 在 IPAM 中已记录（IPAM 扫描填充的 mac_address）
    """
    if ip:
        result = await db.execute(
            select(Device)
            .join(IPAddress, Device.mgmt_ip_id == IPAddress.id)
            .where(IPAddress.address == ip)
            .limit(1)
        )
        device = result.scalar_one_or_none()
        if device:
            return device

        result = await db.execute(
            select(IPAddress)
            .where(IPAddress.address == ip, IPAddress.device_id.isnot(None))
            .limit(1)
        )
        ip_row = result.scalar_one_or_none()
        if ip_row:
            device = await db.get(Device, ip_row.device_id)
            if device:
                return device

    if mac_norm:
        result = await db.execute(
            select(IPAddress)
            .where(IPAddress.mac_address.in_(mac_variants(mac_norm)), IPAddress.device_id.isnot(None))
            .limit(1)
        )
        ip_row = result.scalar_one_or_none()
        if ip_row:
            device = await db.get(Device, ip_row.device_id)
            if device:
                return device

    return None


async def upsert_unknown_endpoints(db: AsyncSession, records: list) -> int:
    """未知接入记录落库：按（接入设备+端口+MAC）去重，重复发现仅刷新 last_seen_at"""
    now = datetime.now()
    for device_id, port, mac, ip in records:
        result = await db.execute(
            select(DiscoveryUnknownEndpoint).where(
                DiscoveryUnknownEndpoint.device_id == device_id,
                DiscoveryUnknownEndpoint.local_interface == port,
                DiscoveryUnknownEndpoint.mac_address == mac,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.ip_address = ip or row.ip_address
            row.last_seen_at = now
        else:
            db.add(DiscoveryUnknownEndpoint(
                device_id=device_id,
                local_interface=port,
                mac_address=mac,
                ip_address=ip,
                first_seen_at=now,
                last_seen_at=now,
            ))
    await db.commit()
    return len(records)


# ---------- 主流程 ----------

def _scannable(device: Device) -> bool:
    """只扫描网络设备（排除服务器/互联网节点，它们没有 MAC 地址表可采）"""
    t = (device.type or '').lower()
    return not ('server' in t or '服务器' in t or 'internet' in t or '互联网' in t)


async def run_mac_discovery(
    db: AsyncSession,
    on_progress: Optional[Callable[[str, int, int, str], Awaitable[None]]] = None,
) -> dict:
    """运行 MAC/ARP 表发现，返回统计结果
    on_progress: 可选进度回调 on_progress(阶段, 已完成数, 总数, 明细)
    """

    async def progress(phase: str, done: int, total: int, message: str = "") -> None:
        if on_progress:
            try:
                await on_progress(phase, done, total, message)
            except Exception:
                pass

    # 只对"在用"设备做 SSH 采集：停用/维修/报废设备可能已断电或改接，
    # 登录只会产生失败连接（并可能触发设备侧账号锁定）
    result = await db.execute(select(Device).where(Device.status == "active"))
    devices = result.scalars().all()

    credentials = await get_all_credentials(db)
    if not credentials:
        raise Exception("系统中没有配置任何设备凭证，请先在系统设置中添加SSH登录凭证")

    devices_with_ip = [d for d in devices if d.mgmt_ip_id and _scannable(d)]
    if not devices_with_ip:
        raise Exception("没有可扫描的网络设备（需为交换机/路由器配置管理IP）")

    # 预取管理IP映射
    ip_result = await db.execute(select(IPAddress))
    ip_map = {ip.id: ip.address for ip in ip_result.scalars().all()}

    # 已知设备间链路的接口集合：这些是上联口/互联口，其 MAC 表项不代表终端
    link_result = await db.execute(
        select(DeviceLink).where(
            DeviceLink.source_device_id.isnot(None),
            DeviceLink.target_device_id.isnot(None),
        )
    )
    known_ifaces = {}  # device_id -> set(intf_tail)
    for link in link_result.scalars().all():
        if link.source_device_id and link.source_interface:
            known_ifaces.setdefault(link.source_device_id, set()).add(intf_tail(link.source_interface))
        if link.target_device_id and link.target_interface:
            known_ifaces.setdefault(link.target_device_id, set()).add(intf_tail(link.target_interface))

    semaphore = asyncio.Semaphore(DISCOVERY_CONCURRENCY)

    async def collect(device: Device, credential) -> Tuple[Device, Optional[dict], Optional[str]]:
        ip_addr = ip_map.get(device.mgmt_ip_id)
        if not ip_addr:
            return device, None, "没有配置管理IP"
        device_info = build_device_info(device, ip_addr, credential)
        cmds = get_mac_arp_commands(get_netmiko_device_type(device.vendor))
        async with semaphore:
            try:
                data, err = await asyncio.to_thread(
                    collect_mac_arp_sync, device_info, cmds["mac"], cmds["arp"]
                )
            except Exception as e:
                return device, None, f"采集异常: {e}"
        return device, data, err

    tasks = []
    for device in devices_with_ip:
        credential = await get_device_credential(db, device)
        if not credential:
            logger.warning(f"设备 {device.name} 没有配置凭证，跳过")
            continue
        tasks.append(collect(device, credential))

    await progress("采集 MAC/ARP 表", 0, len(tasks), f"共 {len(tasks)} 台设备待采集")

    # 采集完成一台上报一次进度（并发 5，完成顺序不定）
    collected = []
    if tasks:
        for coro in asyncio.as_completed(tasks):
            item = await coro
            collected.append(item)
            dev, data, err = item
            status = "成功" if (data and not err) else f"失败（{err}）" if err else "失败"
            await progress("采集 MAC/ARP 表", len(collected), len(tasks), f"{dev.name}: {status}")

    stats = {
        "devices_total": len(tasks),
        "devices_ok": 0,
        "devices_failed": 0,
        "links_created": 0,
        "links_updated": 0,
        "unknown_endpoints_total": 0,
        "unknown_endpoints_sample": [],  # 最多保留5条明细
        "failed_devices": [],            # 最多保留5条明细
    }

    all_links = []
    pending_unknown = []
    await progress("匹配终端与资产", len(tasks), len(tasks), "")
    for device, data, err in collected:
        if err or not data:
            stats["devices_failed"] += 1
            if len(stats["failed_devices"]) < 5:
                stats["failed_devices"].append({"device": device.name, "error": err or "未知错误"})
            continue

        stats["devices_ok"] += 1

        # 端口 -> [MAC]
        port_macs = {}
        for entry in data["mac_entries"]:
            port_macs.setdefault(entry['port'], []).append(entry['mac'])

        exclude = known_ifaces.get(device.id, set())
        for port, macs in port_macs.items():
            if intf_tail(port) in exclude:
                continue  # 已知网络设备互联口
            if len(macs) > MAX_MACS_PER_ACCESS_PORT:
                continue  # MAC 过多，视为 trunk/上联口
            for mac in macs:
                ip = data["arp_map"].get(mac)
                target = await resolve_endpoint_device(db, mac, ip)
                if target and target.id != device.id:
                    all_links.append({
                        "source_device_id": device.id,
                        "source_interface": port,
                        "target_device_id": target.id,
                        "target_interface": "",
                        "link_type": "mac_arp",
                        "confidence": 80,
                    })
                elif target is None:
                    stats["unknown_endpoints_total"] += 1
                    if len(stats["unknown_endpoints_sample"]) < 5:
                        stats["unknown_endpoints_sample"].append(
                            f"{device.name} {port} MAC {mac}" + (f" IP {ip}" if ip else "")
                        )
                    pending_unknown.append((device.id, port, mac, ip))

    if all_links:
        created, updated = await update_or_create_device_links(db, all_links)
        stats["links_created"] = created
        stats["links_updated"] = updated
    if pending_unknown:
        await upsert_unknown_endpoints(db, pending_unknown)

    logger.info(
        f"MAC/ARP发现完成: 设备成功 {stats['devices_ok']}/{stats['devices_total']}, "
        f"终端链路新增 {stats['links_created']} / 更新 {stats['links_updated']}, "
        f"未知接入 {stats['unknown_endpoints_total']}"
    )
    return stats
