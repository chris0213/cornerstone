from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosed
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update, delete, func, or_
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging
import uuid

logger = logging.getLogger("cornerstone")

from ..database import get_db
from ..models import Aggregate, Prefix, IPAddress, Device
from ..schemas import (
    AggregateCreate, AggregateUpdate, AggregateResponse,
    PrefixCreate, PrefixUpdate, PrefixResponse,
    IPAddressCreate, IPAddressUpdate, IPAddressResponse, IPExpiringResponse
)
from .dependencies import get_current_active_user, PageParams, pagination
from ..services.scanner import probe_single_ip, scan_prefix, set_scan_task, get_scan_task, remove_scan_task, parse_custom_ports

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

        # 提前验证 CIDR（async generator 惰性执行，错了要等到消费才炸）
        from ipaddress import IPv4Network, AddressValueError, NetmaskValueError
        try:
            IPv4Network(prefix.network)
        except (AddressValueError, NetmaskValueError, ValueError) as e:
            raise HTTPException(status_code=400, detail=f"子网 CIDR 无效: {prefix.network} ({e})")

        # 获取该子网下的所有IP记录
        result = await db.execute(select(IPAddress).where(IPAddress.prefix_id == prefix_id))
        ip_records = result.scalars().all()

        ip_list = [{"id": ip.id, "address": ip.address} for ip in ip_records]

        # 解析自定义端口组
        tcp_ports = parse_custom_ports(prefix.custom_scan_ports)

        # 创建任务ID
        task_id = str(uuid.uuid4())

        # 创建扫描生成器（惰性——这里还没开始探测任何 IP）
        scanner = scan_prefix(prefix.network, ip_list, tcp_ports=tcp_ports)

        # 关键：不存 HTTP 请求注入的 db session（请求结束即关闭），
        # 让 _save_scan_result 在消费时自己开独立 session
        self.active_tasks[task_id] = {
            "scanner": scanner,
            "prefix_id": prefix_id,
            "network": prefix.network,
            "started_at": datetime.now(),
        }

        logger.info(f"[scan] task created task_id={task_id} network={prefix.network}")
        return task_id

    async def _save_scan_result(self, prefix_id: int, ip: str, is_online: bool, mac_address: str = None, open_ports: List[int] = None):
        """保存扫描结果到数据库（自己开 session，不依赖 HTTP 请求注入的 session）"""
        from ..database import async_session
        import json

        # open_ports 是 List[int]，DB 里 open_ports 是 String 列 → 序列化成 JSON 字符串存
        ports_str = json.dumps(open_ports) if open_ports else None

        async with async_session() as db:
            result = await db.execute(select(IPAddress).where(
                IPAddress.prefix_id == prefix_id,
                IPAddress.address == ip
            ))
            existing_ip = result.scalar_one_or_none()

            if existing_ip:
                update_data = {
                    "is_online": is_online,
                    "mac_address": mac_address,
                    "open_ports": ports_str,
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
                        open_ports=ports_str,
                        created_at=func.now(),
                        updated_at=func.now()
                    )
                    await db.execute(stmt)
            await db.commit()

    async def get_scan_results(self, task_id: str):
        """获取扫描结果（异步生成）"""
        if task_id not in self.active_tasks:
            raise HTTPException(status_code=404, detail="Scan task not found")

        task_info = self.active_tasks[task_id]
        scanner = task_info["scanner"]
        prefix_id = task_info["prefix_id"]
        network = task_info["network"]

        logger.info(f"[scan] task start streaming task_id={task_id} network={network}")

        try:
            # 手动驱动 async generator — async for 无法 catch 到 generator
            # 体里的异常（被惰性执行机制吞成 StopAsyncIteration），
            # 手动 __anext__() 才能真正把异常抛到外层 try/except
            it = scanner.__aiter__()
            logger.info(f"[scan] calling scanner first __anext__() network={network}")
            while True:
                try:
                    result = await it.__anext__()
                except StopAsyncIteration:
                    logger.info(f"[scan] task done task_id={task_id} network={network}")
                    break

                # 如果是扫描结果，保存到数据库
                if result.get("type") == "result":
                    try:
                        await self._save_scan_result(
                            prefix_id=prefix_id,
                            ip=result.get("ip", ""),
                            is_online=result.get("is_online", False),
                            mac_address=result.get("mac_address"),
                            open_ports=result.get("open_ports")
                        )
                    except Exception as e:
                        # 单条保存失败不影响整个扫描
                        logger.warning(f"[scan] save result failed ip={result.get('ip')}: {e}")
                yield result

        except Exception as e:
            logger.exception(f"[scan] task error task_id={task_id} network={network}: {e}")
            yield {"type": "error", "message": f"{type(e).__name__}: {e}"}
        finally:
            # 扫描完成（或中途报错）都清理任务
            self.active_tasks.pop(task_id, None)


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
    site_id: int | None = None,
    network: str | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    stmt = select(Prefix)
    if site_id is not None:
        stmt = stmt.where(Prefix.site_id == site_id)
    if network:
        stmt = stmt.where(Prefix.network.ilike(f"%{network}%"))
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(
            Prefix.network.ilike(like),
            Prefix.usage.ilike(like),
            Prefix.custom_scan_ports.ilike(like),
        ))
    stmt = stmt.offset(page.skip).limit(page.limit)
    result = await db.execute(stmt)
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
    created = result.scalar_one()

    # 如果启用了自动扫描，注册到调度器
    from ..tasks.ipam_scheduler import reload_ipam_scan
    await reload_ipam_scan(created.id, db)

    return created

@router.put("/prefixes/{prefix_id}", response_model=PrefixResponse)
async def update_prefix(
    prefix_id: int,
    prefix: PrefixUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    stmt = update(Prefix).where(Prefix.id == prefix_id).values(**prefix.model_dump(exclude_unset=True)).returning(Prefix)
    result = await db.execute(stmt)
    prefix_obj = result.scalar_one_or_none()
    if prefix_obj is None:
        raise HTTPException(status_code=404, detail="Prefix not found")
    await db.commit()

    # 自动扫描相关字段变更时，同步调度器
    from ..tasks.ipam_scheduler import reload_ipam_scan
    await reload_ipam_scan(prefix_id, db)

    return prefix_obj

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

    # 注销对应的调度器 job
    from ..tasks.ipam_scheduler import reload_ipam_scan
    await reload_ipam_scan(prefix_id, db)

# IP Address routes
@router.get("/addresses/", response_model=list[IPAddressResponse])
async def read_addresses(
    page: PageParams = Depends(pagination()),
    prefix_id: int | None = None,
    device_id: int | None = None,
    status: str | None = None,
    is_online: bool | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    stmt = select(IPAddress)
    if prefix_id is not None:
        stmt = stmt.where(IPAddress.prefix_id == prefix_id)
    if device_id is not None:
        stmt = stmt.where(IPAddress.device_id == device_id)
    if status:
        stmt = stmt.where(IPAddress.status == status)
    if is_online is not None:
        stmt = stmt.where(IPAddress.is_online == is_online)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(
            IPAddress.address.ilike(like),
            IPAddress.usage.ilike(like),
            IPAddress.owner.ilike(like),
            IPAddress.mac_address.ilike(like),
        ))
    stmt = stmt.offset(page.skip).limit(page.limit)
    result = await db.execute(stmt)
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
    logger.info(f"[scan] WS accepted task_id={task_id} active_keys={list(scan_manager.active_tasks.keys())}")

    # 验证用户身份
    from .dependencies import get_ws_user
    try:
        await get_ws_user(websocket, db)
        logger.info(f"[scan] WS auth ok task_id={task_id}")
    except Exception as e:
        logger.warning(f"[scan] WS auth failed task_id={task_id}: {e}")
        await websocket.send_json({"type": "error", "message": f"认证失败: {e}"})
        await websocket.close(code=1008, reason="认证失败")
        return

    if task_id not in scan_manager.active_tasks:
        logger.warning(f"[scan] WS task not in active_tasks task_id={task_id}")
        await websocket.send_json({"type": "error", "message": "扫描任务不存在"})
        await websocket.close()
        return
    
    try:
        async for result in scan_manager.get_scan_results(task_id):
            await websocket.send_json(result)
    except WebSocketDisconnect:
        pass
    except ConnectionClosed:
        # 前端主动关闭、正常扫描完成、超时关闭都可能触发，不是错误
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
