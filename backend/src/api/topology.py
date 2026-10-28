import asyncio
import logging
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db, async_session
from src.api.dependencies import PageParams, pagination
from src.models.site import Site
from src.models.circuit import Circuit
from src.models.device import Device
from src.models.device_link import DeviceLink
from src.models.ip_address import IPAddress
from src.models.discovery import DiscoveryUnknownEndpoint
from src.schemas import DeviceLinkCreate, DeviceLinkUpdate, DeviceLinkResponse

router = APIRouter(tags=["topology"])
logger = logging.getLogger(__name__)


@router.get("/site-graph")
async def get_site_graph(db: AsyncSession = Depends(get_db)):
    """获取站点间拓扑数据"""
    # 获取所有站点
    sites_result = await db.execute(select(Site))
    sites = sites_result.scalars().all()
    
    # 获取所有专线
    circuits_result = await db.execute(select(Circuit))
    circuits = circuits_result.scalars().all()
    
    # 统计每个站点的设备数量
    device_counts = {}
    device_result = await db.execute(
        select(Device.site_id, func.count(Device.id))
        .group_by(Device.site_id)
    )
    for site_id, count in device_result.all():
        device_counts[site_id] = count
    
    # 构建节点
    nodes = []
    for site in sites:
        node = {
            "id": f"site_{site.id}",
            "site_id": site.id,
            "name": site.name,
            "city": site.city,
            "status": site.status,
            "device_count": device_counts.get(site.id, 0),
            "circuit_count": 0,
            "contact": site.contact,
            "phone": site.contact_phone,
            "location": site.location,
            "room": site.room,
        }
        nodes.append(node)
    
    # 统计每个站点的专线数量并构建边
    circuit_counts = {}
    edges = []
    
    for circuit in circuits:
        # 跳过未关联站点的专线
        if not circuit.site_id:
            continue
        
        # 统计站点专线数量
        if circuit.site_id in circuit_counts:
            circuit_counts[circuit.site_id] += 1
        else:
            circuit_counts[circuit.site_id] = 1
        
        # 确定专线类型
        type_map = {
            "internet": "internet",
            "mpls": "mpls",
            "sdwan": "sdwan",
            "fiber": "fiber",
        }
        circuit_type = type_map.get(circuit.type.lower(), "internet")
        
        # 确定带宽标签
        bandwidth = circuit.bandwidth or 0
        if bandwidth >= 1000:
            bandwidth_label = f"{bandwidth // 1000}G"
        elif bandwidth >= 100:
            bandwidth_label = f"{bandwidth}M"
        else:
            bandwidth_label = f"{bandwidth}M"
        
        # 构建边（假设专线连接到总部站点）
        # 实际应用中可能需要存储对端站点信息
        edge = {
            "id": f"circuit_{circuit.id}",
            "circuit_id": circuit.id,
            "source": f"site_{circuit.site_id}",
            "target": "site_hub",  # 虚拟中心节点
            "name": circuit.name,
            "provider": circuit.provider,
            "type": circuit_type,
            "bandwidth": bandwidth,
            "bandwidth_label": bandwidth_label,
            "status": circuit.status,
            "monthly_cost": circuit.monthly_cost,
            "contract_end": circuit.contract_end.isoformat() if circuit.contract_end else None,
            "days_to_expire": None,  # 可后续计算
        }
        edges.append(edge)
    
    # 更新节点的专线数量
    for node in nodes:
        node["circuit_count"] = circuit_counts.get(node["site_id"], 0)
    
    # 添加虚拟中心节点
    hub_node = {
        "id": "site_hub",
        "site_id": 0,
        "name": "网络中心",
        "city": "总部",
        "status": "normal",
        "device_count": 0,
        "circuit_count": len(edges),
        "contact": "-",
        "phone": "-",
        "location": "-",
        "room": "-",
    }
    nodes.append(hub_node)
    
    return {
        "nodes": nodes,
        "edges": edges,
    }


@router.get("/device-graph")
async def get_device_graph(
    site_id: Optional[int] = Query(None, description="站点 ID，不提供则返回所有设备"),
    db: AsyncSession = Depends(get_db)
):
    """获取站点内设备拓扑数据"""
    from src.models.ip_address import IPAddress
    from src.models.link_monitor import LinkMonitor
    
    # 获取设备连接关系（用于后续确定需要查询的设备范围）
    links_query = select(DeviceLink)
    links_result = await db.execute(links_query)
    links = links_result.scalars().all()
    
    # 收集所有需要查询的设备ID（当前站点设备 + 通过连接关系关联的设备）
    required_device_ids = set()
    
    # 获取当前站点的设备
    base_device_query = select(Device).where(
        Device.site_id == site_id if site_id else True
    )
    base_device_result = await db.execute(base_device_query)
    base_devices = base_device_result.scalars().all()
    
    for device in base_devices:
        required_device_ids.add(device.id)
    
    # 收集通过连接关系关联的设备ID
    for link in links:
        if link.source_device_id:
            required_device_ids.add(link.source_device_id)
        if link.target_device_id:
            required_device_ids.add(link.target_device_id)
    
    # 获取所有需要的设备及其关联的IP地址和站点信息
    if required_device_ids:
        query = select(Device, IPAddress, Site).outerjoin(IPAddress, Device.mgmt_ip_id == IPAddress.id).outerjoin(Site, Device.site_id == Site.id).where(
            Device.id.in_(required_device_ids)
        )
    else:
        query = select(Device, IPAddress, Site).outerjoin(IPAddress, Device.mgmt_ip_id == IPAddress.id).outerjoin(Site, Device.site_id == Site.id)
    
    result = await db.execute(query)
    device_ip_site_pairs = result.all()
    
    # 获取最新的监控数据
    monitor_query = select(
        LinkMonitor.device_id,
        LinkMonitor.latency,
        LinkMonitor.packet_loss,
        LinkMonitor.status
    ).order_by(LinkMonitor.created_at.desc())
    monitor_result = await db.execute(monitor_query)
    monitor_data = monitor_result.all()
    
    # 构建监控数据字典（按device_id分组，取最新的）
    monitor_dict = {}
    for device_id, latency, packet_loss, status in monitor_data:
        if device_id not in monitor_dict:
            monitor_dict[device_id] = {
                "latency": latency,
                "packet_loss": packet_loss,
                "monitor_status": status
            }
    
    # 获取所有专线（不限制站点，因为可能有跨站点的专线连接）
    circuit_query = select(Circuit)
    circuit_result = await db.execute(circuit_query)
    circuits = circuit_result.scalars().all()
    
    # 筛选互联网专线
    internet_circuits = [c for c in circuits if c.type and (
        "互联网" in c.type or "internet" in c.type.lower()
    )]
    
    # 收集所有配置了连接关系的专线（包括MPLS、SD-WAN等）
    linked_circuit_ids = set()
    for link in links:
        if link.source_circuit_id:
            linked_circuit_ids.add(link.source_circuit_id)
        if link.target_circuit_id:
            linked_circuit_ids.add(link.target_circuit_id)
    
    # 收集所有配置了connected_device_id的专线
    for circuit in circuits:
        if circuit.connected_device_id:
            linked_circuit_ids.add(circuit.id)
    
    # 获取所有需要显示的专线（配置了连接关系的专线）
    display_circuits = [c for c in circuits if c.id in linked_circuit_ids]
    
    nodes = []
    edges = []
    
    # 构建设备节点
    for device, ip_addr, site in device_ip_site_pairs:
        # 首先获取监控数据
        monitor_info = monitor_dict.get(device.id, {})
        latency = monitor_info.get("latency")
        packet_loss = monitor_info.get("packet_loss")
        monitor_status = monitor_info.get("monitor_status")
        
        # 状态判定优先级：监控状态 > 设备状态 > 默认状态
        status = "unknown"
        
        if monitor_status:
            status = monitor_status
        elif device.status == "offline" or device.status == "decommissioned":
            status = "offline"
        elif device.status == "warning":
            status = "warning"
        elif device.status == "maintenance":
            status = "warning"
        elif device.status == "active":
            status = "normal"
        
        device_type = "switch"
        if device.type:
            if "router" in device.type.lower() or "路由" in device.type:
                device_type = "router"
            elif "firewall" in device.type.lower() or "防火墙" in device.type:
                device_type = "firewall"
            elif "server" in device.type.lower() or "服务器" in device.type:
                device_type = "server"
            elif "internet" in device.type.lower() or "互联网" in device.type:
                device_type = "internet"
        
        node = {
            "id": f"device_{device.id}",
            "device_id": device.id,
            "name": device.name,
            "ip_address": ip_addr.address if ip_addr else None,
            "type": device_type,
            "vendor": device.vendor or "unknown",
            "status": status,
            "site_id": device.site_id,
            "site_name": site.name if site else None,
            "latency": latency,
            "packet_loss": packet_loss,
        }
        nodes.append(node)
    
    # 为每个配置了连接关系的专线创建出口节点，并建立连接
    for circuit in display_circuits:
        target_device = None
        
        # 优先从DeviceLink中查找专线与设备的连接关系
        for link in links:
            if link.source_circuit_id == circuit.id and link.target_device_id:
                for device, ip_addr, site in device_ip_site_pairs:
                    if device.id == link.target_device_id:
                        target_device = device
                        break
                break
            elif link.target_circuit_id == circuit.id and link.source_device_id:
                for device, ip_addr, site in device_ip_site_pairs:
                    if device.id == link.source_device_id:
                        target_device = device
                        break
                break
        
        # 如果没有通过DeviceLink配置，再检查circuit.connected_device_id
        if not target_device and circuit.connected_device_id:
            for device, ip_addr, site in device_ip_site_pairs:
                if device.id == circuit.connected_device_id:
                    target_device = device
                    break
        
        # 只有明确配置了连接关系的专线才在拓扑图中显示
        if not target_device:
            continue
        
        # 创建出口节点
        isp_name = circuit.provider or "运营商"
        circuit_name = circuit.name or f"{isp_name}专线"
        
        # 根据专线类型设置节点图标类型
        circuit_type = circuit.type or ""
        if "互联网" in circuit_type or "internet" in circuit_type.lower():
            node_type = "internet"
        elif "mpls" in circuit_type.lower():
            node_type = "isp"
        elif "sd-wan" in circuit_type.lower() or "sdwan" in circuit_type.lower():
            node_type = "sdwan"
        else:
            node_type = "internet"
        
        internet_node = {
            "id": f"internet_{circuit.id}",
            "device_id": -circuit.id,
            "name": circuit_name,
            "ip_address": circuit.public_ip or f"ISP:{isp_name}",
            "type": node_type,
            "vendor": isp_name,
            "status": "normal",
            "site_id": circuit.site_id,
            "site_name": None,
            "latency": None,
            "packet_loss": None,
            "circuit_id": circuit.id,
            "provider": circuit.provider,
            "bandwidth": circuit.bandwidth,
        }
        nodes.append(internet_node)
        
        # 如果找到目标设备，建立连接
        if target_device:
            internet_edge = {
                "id": f"link_internet_{circuit.id}",
                "link_id": -circuit.id,
                "source": f"internet_{circuit.id}",
                "target": f"device_{target_device.id}",
                "source_interface": None,
                "target_interface": None,
                "link_type": "internet",
                "confidence": 1.0,
            }
            edges.append(internet_edge)
    
    # 构建连接边（支持设备-设备、专线-设备、设备-专线）
    for link in links:
        # 确定source和target
        source = None
        target = None
        
        if link.source_device_id and link.target_device_id:
            source = f"device_{link.source_device_id}"
            target = f"device_{link.target_device_id}"
        elif link.source_circuit_id and link.target_device_id:
            source = f"internet_{link.source_circuit_id}"
            target = f"device_{link.target_device_id}"
        elif link.source_device_id and link.target_circuit_id:
            source = f"device_{link.source_device_id}"
            target = f"internet_{link.target_circuit_id}"
        
        if source and target:
            edge = {
                "id": f"link_{link.id}",
                "link_id": link.id,
                "source": source,
                "target": target,
                "source_interface": link.source_interface,
                "target_interface": link.target_interface,
                "link_type": link.link_type,
                "confidence": link.confidence,
            }
            edges.append(edge)
    
    return {
        "nodes": nodes,
        "edges": edges,
    }


# 设备连接关系 CRUD API
@router.get("/device-links", response_model=List[DeviceLinkResponse])
async def read_device_links(
    page: PageParams = Depends(pagination()),
    db: AsyncSession = Depends(get_db)
):
    """获取设备连接关系列表"""
    query = select(DeviceLink).offset(page.skip).limit(page.limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/device-links/{link_id}", response_model=DeviceLinkResponse)
async def read_device_link(
    link_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取单个设备连接关系"""
    query = select(DeviceLink).where(DeviceLink.id == link_id)
    result = await db.execute(query)
    link = result.scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=404, detail="Device link not found")
    return link


@router.post("/device-links", response_model=DeviceLinkResponse, status_code=status.HTTP_201_CREATED)
async def create_device_link(
    link: DeviceLinkCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建设备连接关系（支持设备-设备、专线-设备、设备-专线）"""
    # 验证至少有一端是有效的（source或target必须有device_id或circuit_id）
    if not link.source_device_id and not link.source_circuit_id:
        raise HTTPException(status_code=400, detail="Source must have device_id or circuit_id")
    if not link.target_device_id and not link.target_circuit_id:
        raise HTTPException(status_code=400, detail="Target must have device_id or circuit_id")
    
    # 验证源设备是否存在（如果提供了）
    if link.source_device_id:
        source_query = select(Device).where(Device.id == link.source_device_id)
        source_result = await db.execute(source_query)
        if not source_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Source device not found")
    
    # 验证目标设备是否存在（如果提供了）
    if link.target_device_id:
        target_query = select(Device).where(Device.id == link.target_device_id)
        target_result = await db.execute(target_query)
        if not target_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Target device not found")
    
    # 验证源专线是否存在（如果提供了）
    if link.source_circuit_id:
        source_circuit_query = select(Circuit).where(Circuit.id == link.source_circuit_id)
        source_circuit_result = await db.execute(source_circuit_query)
        if not source_circuit_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Source circuit not found")
    
    # 验证目标专线是否存在（如果提供了）
    if link.target_circuit_id:
        target_circuit_query = select(Circuit).where(Circuit.id == link.target_circuit_id)
        target_circuit_result = await db.execute(target_circuit_query)
        if not target_circuit_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Target circuit not found")
    
    # 检查是否已存在相同的连接（设备-设备连接时）
    if link.source_device_id and link.target_device_id:
        existing_query = select(DeviceLink).where(
            ((DeviceLink.source_device_id == link.source_device_id) & 
             (DeviceLink.target_device_id == link.target_device_id)) |
            ((DeviceLink.source_device_id == link.target_device_id) & 
             (DeviceLink.target_device_id == link.source_device_id))
        )
        existing_result = await db.execute(existing_query)
        if existing_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Device link already exists")
    
    # 检查是否已存在相同的连接（专线-设备连接时）
    if link.source_circuit_id and link.target_device_id:
        existing_query = select(DeviceLink).where(
            (DeviceLink.source_circuit_id == link.source_circuit_id) & 
            (DeviceLink.target_device_id == link.target_device_id)
        )
        existing_result = await db.execute(existing_query)
        if existing_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Circuit-device link already exists")
    
    # 创建连接关系
    db_link = DeviceLink(**link.model_dump())
    db_link.discovered_at = datetime.now()
    db.add(db_link)
    await db.commit()
    await db.refresh(db_link)
    return db_link


@router.put("/device-links/{link_id}", response_model=DeviceLinkResponse)
async def update_device_link(
    link_id: int,
    link_update: DeviceLinkUpdate,
    db: AsyncSession = Depends(get_db)
):
    """更新设备连接关系"""
    query = select(DeviceLink).where(DeviceLink.id == link_id)
    result = await db.execute(query)
    db_link = result.scalar_one_or_none()
    if db_link is None:
        raise HTTPException(status_code=404, detail="Device link not found")
    
    # 更新字段
    update_data = link_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_link, field, value)
    
    await db.commit()
    await db.refresh(db_link)
    return db_link


@router.delete("/device-links/{link_id}")
async def delete_device_link(
    link_id: int,
    db: AsyncSession = Depends(get_db)
):
    """删除设备连接关系"""
    query = select(DeviceLink).where(DeviceLink.id == link_id)
    result = await db.execute(query)
    db_link = result.scalar_one_or_none()
    if db_link is None:
        raise HTTPException(status_code=404, detail="Device link not found")
    
    await db.delete(db_link)
    await db.commit()
    return {"message": "Device link deleted successfully"}


@router.put("/circuits/{circuit_id}/connect")
async def update_circuit_connection(
    circuit_id: int,
    connected_device_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db)
):
    """更新专线连接的设备"""
    from pydantic import BaseModel
    
    # 查找专线
    query = select(Circuit).where(Circuit.id == circuit_id)
    result = await db.execute(query)
    circuit = result.scalar_one_or_none()
    if circuit is None:
        raise HTTPException(status_code=404, detail="Circuit not found")
    
    # 验证设备存在（如果提供了设备ID）
    if connected_device_id is not None:
        device_query = select(Device).where(Device.id == connected_device_id)
        device_result = await db.execute(device_query)
        if not device_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Device not found")
    
    # 更新连接
    circuit.connected_device_id = connected_device_id
    await db.commit()
    await db.refresh(circuit)
    
    return {
        "id": circuit.id,
        "name": circuit.name,
        "connected_device_id": circuit.connected_device_id,
        "message": "Connection updated successfully"
    }


@router.get("/site-devices")
async def get_site_devices(
    site_id: int = Query(..., description="站点 ID"),
    db: AsyncSession = Depends(get_db)
):
    """获取站点的设备列表，用于专线连接选择"""
    query = select(Device, IPAddress).outerjoin(IPAddress, Device.mgmt_ip_id == IPAddress.id).where(Device.site_id == site_id)
    result = await db.execute(query)
    device_ip_pairs = result.all()
    
    devices = []
    for device, ip_addr in device_ip_pairs:
        devices.append({
            "id": device.id,
            "name": device.name,
            "type": device.type,
            "ip_address": ip_addr.address if ip_addr else None,
        })
    
    return devices


@router.post("/discover-lldp")
async def discover_lldp_neighbors(
    db: AsyncSession = Depends(get_db)
):
    """启动 LLDP/CDP 邻居发现后台任务，返回 task_id（进度经 /discovery-tasks/{id} 轮询）"""
    from src.services.discovery_task_manager import manager, run_discovery_task
    from src.services.lldp_discovery import run_full_discovery

    if manager.has_running("lldp"):
        task = manager.latest("lldp")
        return {"task_id": task.id, "running": True}

    # 启动前先做前置校验（无设备/无凭证立即报错，不留失败任务）
    from src.services.lldp_discovery import get_all_credentials
    try:
        result = await db.execute(select(Device).where(Device.status != "offline"))
        devices = result.scalars().all()
        if not devices:
            raise Exception("没有可用设备")
        credentials = await get_all_credentials(db)
        if not credentials:
            raise Exception("系统中没有配置任何设备凭证，请先在系统设置中添加SSH登录凭证")
        devices_with_ip = [d for d in devices if d.mgmt_ip_id]
        if not devices_with_ip:
            raise ValueError("没有设备配置了管理IP，无法进行LLDP发现")

        task = manager.create("lldp", total=len(devices_with_ip))
        # 必须在当前（uvicorn 主）事件循环内直接跑后台协程：async_session 的连接池
        # 绑定主 loop，此前用 run_in_executor + asyncio.run 新开 loop 导致
        # "Future attached to a different loop"。SSH 同步采集已由 to_thread 下放线程池，
        # 在主 loop 长跑不阻塞请求。
        task.asyncio_task = asyncio.create_task(
            run_discovery_task(task, run_full_discovery, async_session)
        )
        return {"task_id": task.id, "running": False}
    except ValueError as e:
        logger.warning(f"发现任务参数校验失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/discover-mac")
async def discover_mac_endpoints(
    db: AsyncSession = Depends(get_db)
):
    """启动 MAC/ARP 表发现后台任务（发现交换机下挂服务器等不开 LLDP 的终端）"""
    from src.services.discovery_task_manager import manager, run_discovery_task
    from src.services.mac_discovery import run_mac_discovery

    if manager.has_running("mac"):
        task = manager.latest("mac")
        return {"task_id": task.id, "running": True}

    from src.services.lldp_discovery import get_all_credentials
    try:
        result = await db.execute(select(Device).where(Device.status != "offline"))
        devices = result.scalars().all()
        credentials = await get_all_credentials(db)
        if not credentials:
            raise Exception("系统中没有配置任何设备凭证，请先在系统设置中添加SSH登录凭证")
        scannable = [d for d in devices if d.mgmt_ip_id]
        if not scannable:
            raise ValueError("没有可扫描的网络设备（需为交换机/路由器配置管理IP）")

        task = manager.create("mac", total=len(scannable))
        # 同 discover-lldp：主 loop 内直接跑后台协程，避免跨 loop 使用连接池
        task.asyncio_task = asyncio.create_task(
            run_discovery_task(task, run_mac_discovery, async_session)
        )
        return {"task_id": task.id, "running": False}
    except ValueError as e:
        logger.warning(f"发现任务参数校验失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/discovery-tasks/{task_id}")
async def read_discovery_task(
    task_id: str,
):
    """轮询发现任务进度与结果"""
    from src.services.discovery_task_manager import manager

    task = manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="发现任务不存在（服务可能已重启，请重新发起发现）")
    return task.to_dict()


# 未知接入终端 API
@router.get("/unknown-endpoints")
async def read_unknown_endpoints(
    device_id: Optional[int] = Query(None, description="按接入设备过滤"),
    db: AsyncSession = Depends(get_db)
):
    """获取拓扑发现的未知接入终端列表（含接入设备名称）"""
    query = select(
        DiscoveryUnknownEndpoint,
        Device.name.label("device_name"),
        Device.site_id.label("device_site_id"),
    ).outerjoin(Device, DiscoveryUnknownEndpoint.device_id == Device.id)

    if device_id:
        query = query.where(DiscoveryUnknownEndpoint.device_id == device_id)

    query = query.order_by(DiscoveryUnknownEndpoint.last_seen_at.desc())
    result = await db.execute(query)

    endpoints = []
    for ep, device_name, site_id in result.all():
        endpoints.append({
            "id": ep.id,
            "device_id": ep.device_id,
            "device_name": device_name,
            "site_id": site_id,
            "local_interface": ep.local_interface,
            "mac_address": ep.mac_address,
            "ip_address": ep.ip_address,
            "first_seen_at": ep.first_seen_at,
            "last_seen_at": ep.last_seen_at,
        })
    return endpoints


@router.post("/unknown-endpoints/{endpoint_id}/accept")
async def accept_unknown_endpoint(
    endpoint_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db)
):
    """将未知接入终端一键入库为服务器资产

    payload:
      - name: 设备名称（必填）
      - device_type: 设备类型，默认 server
      - site_id: 站点 ID（可选，默认跟随接入交换机所在站点）
      - owner: 负责人（可选）
      - note: 备注（可选）
      - create_ip: 是否同步录入 IP 到 IPAM（有 IP 时默认 true）
    入库后自动创建「接入交换机-终端」连接关系，并删除该未知接入记录。
    """
    from pydantic import BaseModel, field_validator
    from src.constants.device_type import normalize_device_type

    class AcceptPayload(BaseModel):
        name: str
        device_type: str = "server"
        site_id: int | None = None
        owner: str | None = None
        note: str | None = None
        create_ip: bool = True

        _validate_type = field_validator("device_type")(normalize_device_type)

    try:
        data = AcceptPayload(**payload)
    except Exception as e:
        logger.warning(f"未知接入参数校验失败: {e}")
        raise HTTPException(status_code=422, detail=str(e))

    # 查找未知接入记录
    query = select(DiscoveryUnknownEndpoint).where(DiscoveryUnknownEndpoint.id == endpoint_id)
    result = await db.execute(query)
    endpoint = result.scalar_one_or_none()
    if endpoint is None:
        raise HTTPException(status_code=404, detail="未知接入记录不存在")

    # 接入交换机
    sw_query = select(Device).where(Device.id == endpoint.device_id)
    sw_result = await db.execute(sw_query)
    switch = sw_result.scalar_one_or_none()
    if switch is None:
        raise HTTPException(status_code=404, detail="接入设备不存在，无法入库")

    # 站点默认跟随交换机
    site_id = data.site_id or switch.site_id

    # 名称去重校验
    dup_query = select(Device).where(Device.name == data.name.strip())
    dup_result = await db.execute(dup_query)
    if dup_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"设备名称「{data.name.strip()}」已存在")

    # 创建设备资产
    new_device = Device(
        name=data.name.strip(),
        type=data.device_type,
        site_id=site_id,
        owner=data.owner,
        note=data.note,
        status="active",
    )
    db.add(new_device)
    await db.flush()

    # 同步录入 IP 到 IPAM 并绑定设备
    ip_record = None
    if data.create_ip and endpoint.ip_address:
        ip_query = select(IPAddress).where(IPAddress.address == endpoint.ip_address)
        ip_result = await db.execute(ip_query)
        ip_record = ip_result.scalar_one_or_none()
        if ip_record:
            # 已有 IPAM 记录则补绑设备与 MAC
            if not ip_record.device_id:
                ip_record.device_id = new_device.id
            if not ip_record.mac_address:
                ip_record.mac_address = endpoint.mac_address
            if ip_record.status == "available":
                ip_record.status = "assigned"
        else:
            ip_record = IPAddress(
                address=endpoint.ip_address,
                device_id=new_device.id,
                mac_address=endpoint.mac_address,
                status="assigned",
            )
            db.add(ip_record)
            await db.flush()
        new_device.mgmt_ip_id = ip_record.id

    # 创建「接入交换机-终端」连接关系（避免重复）
    link_query = select(DeviceLink).where(
        ((DeviceLink.source_device_id == switch.id) &
         (DeviceLink.target_device_id == new_device.id)) |
        ((DeviceLink.source_device_id == new_device.id) &
         (DeviceLink.target_device_id == switch.id))
    )
    link_result = await db.execute(link_query)
    existing_link = link_result.scalar_one_or_none()
    if not existing_link:
        db.add(DeviceLink(
            source_device_id=switch.id,
            source_interface=endpoint.local_interface,
            target_device_id=new_device.id,
            target_interface=None,
            link_type="mac_arp",
            confidence=90,
            discovered_at=datetime.now(),
            note=f"未知接入入库（MAC {endpoint.mac_address}）",
        ))

    # 删除未知接入记录
    await db.delete(endpoint)
    await db.commit()
    await db.refresh(new_device)

    return {
        "device_id": new_device.id,
        "device_name": new_device.name,
        "ip_address_id": ip_record.id if ip_record else None,
        "message": "入库成功",
    }


@router.delete("/unknown-endpoints/{endpoint_id}")
async def delete_unknown_endpoint(
    endpoint_id: int,
    db: AsyncSession = Depends(get_db)
):
    """忽略（删除）未知接入终端记录"""
    query = select(DiscoveryUnknownEndpoint).where(DiscoveryUnknownEndpoint.id == endpoint_id)
    result = await db.execute(query)
    endpoint = result.scalar_one_or_none()
    if endpoint is None:
        raise HTTPException(status_code=404, detail="未知接入记录不存在")

    await db.delete(endpoint)
    await db.commit()
    return {"message": "已忽略该未知接入"}
