import asyncio
import logging
from typing import Optional, List, Tuple, Callable, Awaitable
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.device import Device
from src.models.device_link import DeviceLink
from src.models.credential import Credential
from src.models.ip_address import IPAddress
from src.utils.device_connection import connect_device, get_lldp_neighbors
from src.utils.crypto import decrypt_password

logger = logging.getLogger("cornerstone")

# 并发采集上限（SSH 为同步阻塞操作，统一放入线程池）
DISCOVERY_CONCURRENCY = 5
# 单设备最多尝试的凭证数（主凭证 + 兜底凭证），避免不可达设备拖垮整体耗时
MAX_CREDENTIAL_ATTEMPTS = 3


def get_netmiko_device_type(vendor: str) -> str:
    """
    根据厂商获取Netmiko设备类型
    """
    vendor = vendor.lower() if vendor else ""
    if "huawei" in vendor:
        return "huawei"
    elif "h3c" in vendor or "hp" in vendor:
        return "hp_comware"
    elif "cisco" in vendor:
        return "cisco_ios"
    elif "juniper" in vendor:
        return "juniper_junos"
    elif "arista" in vendor:
        return "arista_eos"
    else:
        return "cisco_ios"


def build_device_info(device: Device, ip_address: str, cred: Credential) -> dict:
    """
    构建 netmiko 连接参数（密码需解密）
    """
    return {
        "ip": ip_address,
        "username": cred.username,
        "password": decrypt_password(cred.password) if cred.password else None,
        "device_type": get_netmiko_device_type(device.vendor),
        "port": cred.port or 22,
        "secret": decrypt_password(cred.enable_password) if cred.enable_password else None,
    }


def collect_lldp_neighbors_sync(device_infos: List[dict]) -> Tuple[Optional[list], Optional[str]]:
    """
    在线程中执行同步 SSH 采集（不阻塞事件循环）
    依次尝试候选凭证，返回 (邻居列表, None) 或 (None, 失败原因)
    """
    last_error = None
    for device_info in device_infos:
        conn = connect_device(device_info)
        if conn is None:
            last_error = f"SSH 连接失败（{device_info['ip']}，认证失败或不可达）"
            continue
        try:
            neighbors = get_lldp_neighbors(conn)
            if neighbors:
                return neighbors, None
            last_error = "未发现 LLDP/CDP 邻居（设备可能未启用 LLDP）"
        finally:
            try:
                conn.disconnect()
            except Exception:
                pass
    return None, last_error or "无可用凭证"


async def get_all_credentials(db: AsyncSession) -> list:
    """
    获取所有可用凭证
    """
    query = select(Credential)
    result = await db.execute(query)
    return result.scalars().all()


async def get_device_credential(db: AsyncSession, device: Device) -> Optional[Credential]:
    """
    获取设备的凭证（优先设备专用凭证，其次全局凭证）
    """
    # 先尝试获取设备专用凭证
    query = select(Credential).where(Credential.device_id == device.id).limit(1)
    result = await db.execute(query)
    credential = result.scalar_one_or_none()

    if credential:
        return credential

    # 再尝试获取全局凭证（device_id为空的凭证）
    query = select(Credential).where(Credential.device_id.is_(None)).limit(1)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def find_device_by_name_or_ip(db: AsyncSession, name_or_ip: str) -> Optional[Device]:
    """
    根据设备名或IP查找设备
    匹配顺序（从严到宽，避免误建链）：
    1. 精确名称
    2. 管理IP
    3. 唯一后缀匹配：LLDP 邻居名常带接口后缀（如 PEK-SW-401-4-4.13 -> PEK-SW-401-4）
    """
    if not name_or_ip:
        return None

    name_or_ip = name_or_ip.strip()

    # 1. 精确名称匹配
    result = await db.execute(
        select(Device).where(Device.name == name_or_ip).limit(1)
    )
    device = result.scalar_one_or_none()
    if device:
        return device

    # 2. 管理 IP 匹配（部分设备 LLDP 上报 Chassis ID 为管理地址）
    result = await db.execute(
        select(Device)
        .join(IPAddress, Device.mgmt_ip_id == IPAddress.id)
        .where(IPAddress.address == name_or_ip)
        .limit(1)
    )
    device = result.scalar_one_or_none()
    if device:
        return device

    # 3. 后缀匹配：邻居名以设备名开头（名称过短的设备名容易误命中，要求>=3字符）
    result = await db.execute(select(Device))
    all_devices = result.scalars().all()
    all_devices.sort(key=lambda d: len(d.name), reverse=True)
    for dev in all_devices:
        if len(dev.name or "") >= 3 and name_or_ip.startswith(dev.name):
            logger.info(f"设备名称匹配（后缀匹配）: {name_or_ip} -> {dev.name}")
            return dev

    return None


async def update_or_create_device_links(db: AsyncSession, links_data: List[dict]) -> Tuple[int, int]:
    """
    更新或创建设备连接关系
    按「设备对 + 接口」去重：同一对设备间的多条链路（如链路聚合成员口）各自独立，
    避免互相覆盖；重复发现时仅更新 verified_at。
    返回 (新建数, 更新数)
    """
    created = 0
    updated = 0

    for link_data in links_data:
        source_device_id = link_data['source_device_id']
        target_device_id = link_data['target_device_id']
        source_interface = link_data.get('source_interface') or ''
        target_interface = link_data.get('target_interface') or ''

        result = await db.execute(
            select(DeviceLink).where(
                DeviceLink.source_device_id == source_device_id,
                DeviceLink.target_device_id == target_device_id,
                DeviceLink.source_interface == source_interface,
                DeviceLink.target_interface == target_interface,
            )
        )
        link = result.scalar_one_or_none()
        reverse = False
        if link is None:
            result_reverse = await db.execute(
                select(DeviceLink).where(
                    DeviceLink.source_device_id == target_device_id,
                    DeviceLink.target_device_id == source_device_id,
                    DeviceLink.source_interface == target_interface,
                    DeviceLink.target_interface == source_interface,
                )
            )
            link = result_reverse.scalar_one_or_none()
            reverse = link is not None

        if link is not None:
            if reverse:
                link.source_interface = target_interface
                link.target_interface = source_interface
            else:
                link.source_interface = source_interface
                link.target_interface = target_interface
            link.link_type = link_data['link_type']
            link.confidence = link_data['confidence']
            link.verified_at = datetime.now()
            updated += 1
        else:
            db.add(DeviceLink(
                source_device_id=source_device_id,
                source_interface=source_interface,
                target_device_id=target_device_id,
                target_interface=target_interface,
                link_type=link_data['link_type'],
                confidence=link_data['confidence'],
                discovered_at=datetime.now(),
            ))
            created += 1

    await db.commit()
    return created, updated


async def run_full_discovery(
    db: AsyncSession,
    on_progress: Optional[Callable[[str, int, int, str], Awaitable[None]]] = None,
) -> dict:
    """
    运行完整的 LLDP/CDP 邻居发现
    并发采集（线程池执行 SSH），主协程完成匹配与写库，返回统计结果
    on_progress: 可选进度回调 on_progress(阶段, 已完成数, 总数, 明细)
    """

    async def progress(phase: str, done: int, total: int, message: str = "") -> None:
        if on_progress:
            try:
                await on_progress(phase, done, total, message)
            except Exception:
                pass

    result = await db.execute(select(Device).where(Device.status != "offline"))
    devices = result.scalars().all()
    if not devices:
        raise Exception("没有可用设备")

    credentials = await get_all_credentials(db)
    if not credentials:
        raise Exception("系统中没有配置任何设备凭证，请先在系统设置中添加SSH登录凭证")

    devices_with_ip = [d for d in devices if d.mgmt_ip_id]
    if not devices_with_ip:
        without_ip_names = ", ".join(d.name for d in devices[:10])
        raise Exception(f"没有设备配置了管理IP，无法进行LLDP发现（如 {without_ip_names}）")

    # 预取管理IP映射
    ip_result = await db.execute(select(IPAddress))
    ip_map = {ip.id: ip.address for ip in ip_result.scalars().all()}

    # 构建采集任务（每个设备：主凭证优先，兜底凭证截断到 MAX_CREDENTIAL_ATTEMPTS）
    semaphore = asyncio.Semaphore(DISCOVERY_CONCURRENCY)

    async def collect(device: Device, primary: Credential) -> Tuple[Device, Optional[list], Optional[str]]:
        ip_addr = ip_map.get(device.mgmt_ip_id)
        if not ip_addr:
            return device, None, "没有配置管理IP"
        others = [c for c in credentials if c.id != primary.id][: MAX_CREDENTIAL_ATTEMPTS - 1]
        device_infos = [
            build_device_info(device, ip_addr, cred) for cred in [primary, *others]
        ]
        async with semaphore:
            try:
                neighbors, err = await asyncio.to_thread(collect_lldp_neighbors_sync, device_infos)
            except Exception as e:
                return device, None, f"采集异常: {e}"
        return device, neighbors, err

    tasks = []
    for device in devices_with_ip:
        credential = await get_device_credential(db, device)
        if not credential:
            logger.warning(f"设备 {device.name} 没有配置凭证，跳过")
            continue
        tasks.append(collect(device, credential))

    await progress("采集 LLDP 邻居", 0, len(tasks), f"共 {len(tasks)} 台设备待采集")

    # 采集完成一台上报一次进度（并发 5，完成顺序不定）
    collected = []
    if tasks:
        for coro in asyncio.as_completed(tasks):
            item = await coro
            collected.append(item)
            dev, nb, err = item
            status = "成功" if (nb and not err) else f"失败（{err}）" if err else "失败"
            await progress("采集 LLDP 邻居", len(collected), len(tasks), f"{dev.name}: {status}")

    stats = {
        "devices_total": len(tasks),
        "devices_ok": 0,
        "devices_failed": 0,
        "links_created": 0,
        "links_updated": 0,
        "unmatched_neighbors_total": 0,
        "unmatched_neighbors": [],  # 最多保留5条明细
        "failed_devices": [],       # 最多保留5条明细
    }

    all_links = []
    await progress("匹配邻居与链路", len(tasks), len(tasks), "")
    for device, neighbors, err in collected:
        if err or not neighbors:
            stats["devices_failed"] += 1
            if len(stats["failed_devices"]) < 5:
                stats["failed_devices"].append({"device": device.name, "error": err or "未知错误"})
            continue

        stats["devices_ok"] += 1
        for neighbor in neighbors:
            target_device = await find_device_by_name_or_ip(db, neighbor.get('remote_device'))
            if target_device and target_device.id != device.id:
                all_links.append({
                    "source_device_id": device.id,
                    "source_interface": neighbor.get('local_interface'),
                    "target_device_id": target_device.id,
                    "target_interface": neighbor.get('remote_port'),
                    "link_type": "lldp",
                    "confidence": 100,
                })
            elif target_device is None:
                stats["unmatched_neighbors_total"] += 1
                if len(stats["unmatched_neighbors"]) < 5:
                    stats["unmatched_neighbors"].append(
                        f"{device.name} <- {neighbor.get('remote_device')}"
                    )
            # 邻居匹配到自身时忽略（自环无意义）

    if all_links:
        created, updated = await update_or_create_device_links(db, all_links)
        stats["links_created"] = created
        stats["links_updated"] = updated

    logger.info(
        f"LLDP发现完成: 设备成功 {stats['devices_ok']}/{stats['devices_total']}, "
        f"链路新增 {stats['links_created']} / 更新 {stats['links_updated']}, "
        f"未匹配邻居 {stats['unmatched_neighbors_total']}"
    )
    return stats
