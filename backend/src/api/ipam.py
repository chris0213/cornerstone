from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update, delete, func
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import uuid

from ..database import get_db
from ..models import Aggregate, Prefix, IPAddress, Device
from ..schemas import (
    AggregateCreate, AggregateUpdate, AggregateResponse,
    PrefixCreate, PrefixUpdate, PrefixResponse,
    IPAddressCreate, IPAddressUpdate, IPAddressResponse, IPExpiringResponse
)
from .dependencies import get_current_active_user, PageParams, pagination
from ..services.scanner import probe_single_ip, scan_prefix, set_scan_task, get_scan_task, remove_scan_task

router = APIRouter()

# 扫描任务状态存储
scan_tasks = {}


class ScanManager:
    """扫描管理器"""
    def __init__(self):
        self.active_tasks = {}
    
    async def start_scan(self, prefix_id: int, db: AsyncSession):
        """启动子网扫描任务"""
        # 获取子网信息
        result = await db.execute(select(Prefix).where(Prefix.id == prefix_id))
        prefix = result.scalar_one_or_none()
        
        if not prefix:
            raise HTTPException(status_code=404, detail="Prefix not found")
        
        # 获取该子网下的所有IP记录
        result = await db.execute(select(IPAddress).where(IPAddress.prefix_id == prefix_id))
        ip_records = result.scalars().all()
        
        ip_list = [{"id": ip.id, "address": ip.address} for ip in ip_records]
        
        # 创建任务ID
        task_id = str(uuid.uuid4())
        
        # 创建扫描生成器
        scanner = scan_prefix(prefix.network, ip_list)
        
        # 保存任务
        self.active_tasks[task_id] = {
            "scanner": scanner,
            "prefix_id": prefix_id,
            "network": prefix.network,
            "started_at": datetime.now(),
            "db": db
        }
        
        return task_id
    
    async def _save_scan_result(self, db: AsyncSession, prefix_id: int, ip: str, is_online: bool, mac_address: str = None, open_ports: List[int] = None):
        """保存扫描结果到数据库"""
        # 检查IP是否已存在
        result = await db.execute(select(IPAddress).where(
            IPAddress.prefix_id == prefix_id,
            IPAddress.address == ip
        ))
        existing_ip = result.scalar_one_or_none()
        
        if existing_ip:
            # 更新现有记录
            update_data = {
                "is_online": is_online,
                "mac_address": mac_address,
                "open_ports": open_ports,
                "updated_at": func.now()
            }
            # 如果状态是英文的，转换为中文
            if existing_ip.status == "assigned":
                update_data["status"] = "已分配"
            elif existing_ip.status == "reserved":
                update_data["status"] = "预留"
            elif existing_ip.status == "available":
                update_data["status"] = "未分配"
            
            stmt = update(IPAddress).where(IPAddress.id == existing_ip.id).values(**update_data)
            await db.execute(stmt)
        else:
            # 创建新记录（仅当IP在线时）
            if is_online:
                stmt = insert(IPAddress).values(
                    prefix_id=prefix_id,
                    address=ip,
                    status="已分配",
                    is_online=is_online,
                    mac_address=mac_address,
                    open_ports=open_ports,
                    created_at=func.now(),
                    updated_at=func.now()
                )
                await db.execute(stmt)
    
    async def get_scan_results(self, task_id: str):
        """获取扫描结果（异步生成）"""
        if task_id not in self.active_tasks:
            raise HTTPException(status_code=404, detail="Scan task not found")
        
        task_info = self.active_tasks[task_id]
        scanner = task_info["scanner"]
        db = task_info["db"]
        prefix_id = task_info["prefix_id"]
        
        async for result in scanner:
            # 如果是扫描结果，保存到数据库
            if result.get("type") == "result":
                await self._save_scan_result(
                    db=db,
                    prefix_id=prefix_id,
                    ip=result.get("ip", ""),
                    is_online=result.get("is_online", False),
                    mac_address=result.get("mac_address"),
                    open_ports=result.get("open_ports")
                )
                await db.commit()
            yield result
        
        # 扫描完成，清理任务
        del self.active_tasks[task_id]


scan_manager = ScanManager()

# Aggregate routes
@router.get("/aggregates/", response_model=list[AggregateResponse])
async def read_aggregates(
    page: PageParams = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(Aggregate).offset(page.skip).limit(page.limit))
    return result.scalars().all()

@router.post("/aggregates/", response_model=AggregateResponse, status_code=status.HTTP_201_CREATED)
async def create_aggregate(
    aggregate: AggregateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    stmt = insert(Aggregate).values(**aggregate.model_dump()).returning(Aggregate)
    result = await db.execute(stmt)
    await db.commit()
    return result.scalar_one()

@router.put("/aggregates/{aggregate_id}", response_model=AggregateResponse)
async def update_aggregate(
    aggregate_id: int,
    aggregate: AggregateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    stmt = update(Aggregate).where(Aggregate.id == aggregate_id).values(**aggregate.model_dump(exclude_unset=True)).returning(Aggregate)
    result = await db.execute(stmt)
    aggregate = result.scalar_one_or_none()
    if aggregate is None:
        raise HTTPException(status_code=404, detail="Aggregate not found")
    await db.commit()
    return aggregate

@router.delete("/aggregates/{aggregate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_aggregate(
    aggregate_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(Aggregate).where(Aggregate.id == aggregate_id))
    aggregate = result.scalar_one_or_none()
    if aggregate is None:
        raise HTTPException(status_code=404, detail="Aggregate not found")
    
    await db.execute(delete(IPAddress).where(IPAddress.prefix_id.in_(select(Prefix.id).where(Prefix.aggregate_id == aggregate_id))))
    await db.execute(delete(Prefix).where(Prefix.aggregate_id == aggregate_id))
    await db.execute(delete(Aggregate).where(Aggregate.id == aggregate_id))
    await db.commit()

# Prefix routes
@router.get("/prefixes/", response_model=list[PrefixResponse])
async def read_prefixes(
    page: PageParams = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(Prefix).offset(page.skip).limit(page.limit))
    return result.scalars().all()

@router.post("/prefixes/", response_model=PrefixResponse, status_code=status.HTTP_201_CREATED)
async def create_prefix(
    prefix: PrefixCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    stmt = insert(Prefix).values(**prefix.model_dump()).returning(Prefix)
    result = await db.execute(stmt)
    await db.commit()
    return result.scalar_one()

@router.put("/prefixes/{prefix_id}", response_model=PrefixResponse)
async def update_prefix(
    prefix_id: int,
    prefix: PrefixUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    stmt = update(Prefix).where(Prefix.id == prefix_id).values(**prefix.model_dump(exclude_unset=True)).returning(Prefix)
    result = await db.execute(stmt)
    prefix = result.scalar_one_or_none()
    if prefix is None:
        raise HTTPException(status_code=404, detail="Prefix not found")
    await db.commit()
    return prefix

@router.delete("/prefixes/{prefix_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_prefix(
    prefix_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(Prefix).where(Prefix.id == prefix_id))
    prefix = result.scalar_one_or_none()
    if prefix is None:
        raise HTTPException(status_code=404, detail="Prefix not found")
    
    await db.execute(update(Device).where(Device.mgmt_ip_id.in_(select(IPAddress.id).where(IPAddress.prefix_id == prefix_id))).values(mgmt_ip_id=None))
    await db.execute(delete(IPAddress).where(IPAddress.prefix_id == prefix_id))
    await db.execute(delete(Prefix).where(Prefix.id == prefix_id))
    await db.commit()

# IP Address routes
@router.get("/addresses/", response_model=list[IPAddressResponse])
async def read_addresses(
    page: PageParams = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(IPAddress).offset(page.skip).limit(page.limit))
    return result.scalars().all()

@router.post("/addresses/", response_model=IPAddressResponse, status_code=status.HTTP_201_CREATED)
async def create_address(
    address: IPAddressCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    stmt = insert(IPAddress).values(**address.model_dump()).returning(IPAddress)
    result = await db.execute(stmt)
    await db.commit()
    return result.scalar_one()

@router.put("/addresses/{address_id}", response_model=IPAddressResponse)
async def update_address(
    address_id: int,
    address: IPAddressUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    stmt = update(IPAddress).where(IPAddress.id == address_id).values(**address.model_dump(exclude_unset=True)).returning(IPAddress)
    result = await db.execute(stmt)
    address = result.scalar_one_or_none()
    if address is None:
        raise HTTPException(status_code=404, detail="IP Address not found")
    await db.commit()
    return address

@router.delete("/addresses/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_address(
    address_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(IPAddress).where(IPAddress.id == address_id))
    address = result.scalar_one_or_none()
    if address is None:
        raise HTTPException(status_code=404, detail="IP Address not found")
    
    await db.execute(update(Device).where(Device.mgmt_ip_id == address_id).values(mgmt_ip_id=None))
    await db.execute(delete(IPAddress).where(IPAddress.id == address_id))
    await db.commit()


# === IP扫描相关接口 ===

@router.post("/prefixes/{prefix_id}/scan")
async def scan_prefix_addresses(
    prefix_id: int,
    tcp_ports: List[int] = [22, 80, 443, 445, 3389],
    timeout_ms: int = 2000,
    max_concurrent: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """触发子网IP扫描"""
    task_id = await scan_manager.start_scan(prefix_id, db)
    return {"task_id": task_id, "message": "扫描任务已启动"}


@router.get("/scan/tasks")
async def get_scan_tasks(
    current_user: dict = Depends(get_current_active_user)
):
    """获取扫描任务列表"""
    tasks = []
    for task_id, info in scan_manager.active_tasks.items():
        tasks.append({
            "task_id": task_id,
            "prefix_id": info["prefix_id"],
            "network": info["network"],
            "started_at": info["started_at"]
        })
    return {"code": 0, "message": "ok", "data": tasks}


@router.websocket("/ws/scan/{task_id}")
async def websocket_scan(
    websocket: WebSocket,
    task_id: str,
    db: AsyncSession = Depends(get_db)
):
    """WebSocket实时推送扫描进度"""
    await websocket.accept()
    
    # 验证用户身份
    from .dependencies import get_ws_user
    try:
        await get_ws_user(websocket, db)
    except Exception as e:
        await websocket.send_json({"type": "error", "message": f"认证失败: {e}"})
        await websocket.close(code=1008, reason="认证失败")
        return
    
    if task_id not in scan_manager.active_tasks:
        await websocket.send_json({"type": "error", "message": "扫描任务不存在"})
        await websocket.close()
        return
    
    try:
        async for result in scan_manager.get_scan_results(task_id):
            await websocket.send_json(result)
    except WebSocketDisconnect:
        pass


# === IP到期相关接口 ===

@router.get("/addresses/expiring")
async def get_expiring_addresses(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """获取即将到期的IP地址"""
    now = datetime.now()
    expire_end = now + timedelta(days=days)
    
    result = await db.execute(
        select(IPAddress).filter(
            IPAddress.expire_at.isnot(None),
            IPAddress.expire_at <= expire_end,
            IPAddress.status != "available"
        )
    )
    
    addresses = result.scalars().all()
    expiring_list = []
    
    for addr in addresses:
        remaining_days = (addr.expire_at - now).days if addr.expire_at else 0
        expiring_list.append({
            "id": addr.id,
            "address": addr.address,
            "prefix_id": addr.prefix_id,
            "usage": addr.usage,
            "owner": addr.owner,
            "expire_at": addr.expire_at,
            "remaining_days": remaining_days
        })
    
    return {"code": 0, "message": "ok", "data": expiring_list}


@router.post("/addresses/{address_id}/release")
async def release_address(
    address_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """一键释放IP地址"""
    result = await db.execute(select(IPAddress).where(IPAddress.id == address_id))
    address = result.scalar_one_or_none()
    
    if not address:
        raise HTTPException(status_code=404, detail="IP Address not found")
    
    stmt = update(IPAddress).where(IPAddress.id == address_id).values(
        device_id=None,
        usage=None,
        owner=None,
        status="available",
        expire_at=None,
        updated_at=func.now()
    ).returning(IPAddress)
    
    result = await db.execute(stmt)
    await db.commit()
    
    return {"code": 0, "message": "IP地址已成功释放", "data": result.scalar_one()}


@router.get("/prefixes/{prefix_id}/next-available")
async def get_next_available_ip(
    prefix_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """获取子网下下一个可用的IP地址"""
    result = await db.execute(select(Prefix).where(Prefix.id == prefix_id))
    prefix = result.scalar_one_or_none()
    
    if not prefix:
        raise HTTPException(status_code=404, detail="Prefix not found")
    
    import ipaddress
    network = ipaddress.IPv4Network(prefix.network, strict=False)
    
    assigned_result = await db.execute(
        select(IPAddress.address).where(
            IPAddress.prefix_id == prefix_id,
            IPAddress.status != "available"
        )
    )
    assigned_ips = set(assigned_result.scalars().all())
    
    next_ip = None
    for ip in network.hosts():
        ip_str = str(ip)
        if ip_str not in assigned_ips:
            next_ip = ip_str
            break
    
    if not next_ip:
        return {"code": 1, "message": "子网已无可用IP", "data": None}
    
    total_ips = network.num_addresses - 2
    used_count = len(assigned_ips)
    available_count = total_ips - used_count
    usage_rate = (used_count / total_ips) * 100 if total_ips > 0 else 0
    
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "ip_address": next_ip,
            "total_ips": total_ips,
            "used_count": used_count,
            "available_count": available_count,
            "usage_rate": round(usage_rate, 1)
        }
    }
