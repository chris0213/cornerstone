from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update, delete
from datetime import datetime, timezone

from ..database import get_db
from ..models import Device, Credential, LinkMonitor, DeviceLink, Backup, AlertRecord, AlertRule, IPAddress, InspectionDeviceResult, DeviceFingerprint
from ..schemas import (
    DeviceCreate, DeviceUpdate, DeviceResponse
)
from ..utils import backup_config
from .dependencies import get_current_active_user, PageParams, pagination

router = APIRouter()

# Device routes
@router.get("/", response_model=list[DeviceResponse])
async def read_devices(
    page: PageParams = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(Device).offset(page.skip).limit(page.limit))
    return result.scalars().all()

@router.get("/{device_id}", response_model=DeviceResponse)
async def read_device(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return device

@router.post("/", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
async def create_device(
    device: DeviceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    payload = device.model_dump()
    # 统一将日期字段转换为 naive datetime（PostgreSQL TIMESTAMP WITHOUT TIME ZONE）
    if payload.get('purchase_date') and hasattr(payload['purchase_date'], 'astimezone'):
        payload['purchase_date'] = payload['purchase_date'].replace(tzinfo=None)
    if payload.get('warranty_end') and hasattr(payload['warranty_end'], 'astimezone'):
        payload['warranty_end'] = payload['warranty_end'].replace(tzinfo=None)
    
    stmt = insert(Device).values(**payload).returning(Device)
    result = await db.execute(stmt)
    await db.commit()
    return result.scalar_one()

@router.put("/{device_id}", response_model=DeviceResponse)
async def update_device(
    device_id: int,
    device: DeviceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    payload = device.model_dump(exclude_unset=True)
    if payload.get('purchase_date') and hasattr(payload['purchase_date'], 'astimezone'):
        payload['purchase_date'] = payload['purchase_date'].replace(tzinfo=None)
    if payload.get('warranty_end') and hasattr(payload['warranty_end'], 'astimezone'):
        payload['warranty_end'] = payload['warranty_end'].replace(tzinfo=None)
    
    stmt = update(Device).where(Device.id == device_id).values(**payload).returning(Device)
    result = await db.execute(stmt)
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    await db.commit()
    return device

@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    
    await db.execute(update(Device).where(Device.mgmt_ip_id == (select(IPAddress.id).where(IPAddress.device_id == device_id))).values(mgmt_ip_id=None))
    
    await db.execute(delete(LinkMonitor).where(LinkMonitor.device_id == device_id))
    await db.execute(delete(DeviceLink).where(DeviceLink.source_device_id == device_id))
    await db.execute(delete(DeviceLink).where(DeviceLink.target_device_id == device_id))
    await db.execute(delete(Backup).where(Backup.device_id == device_id))
    await db.execute(delete(AlertRecord).where(AlertRecord.device_id == device_id))
    await db.execute(delete(AlertRule).where(AlertRule.device_id == device_id))
    await db.execute(delete(InspectionDeviceResult).where(InspectionDeviceResult.device_id == device_id))
    await db.execute(delete(DeviceFingerprint).where(DeviceFingerprint.device_id == device_id))
    
    await db.execute(delete(IPAddress).where(IPAddress.device_id == device_id))
    await db.execute(delete(Credential).where(Credential.device_id == device_id))
    await db.execute(delete(Device).where(Device.id == device_id))
    await db.commit()

@router.post("/{device_id}/probe")
async def probe_device(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user),
):
    """单设备在线探测：对管理 IP 做一次 ARP/TCP/ICMP 探测并回写 is_online

    不依赖网段扫描，用于设备页"未探测"状态的即时探测。
    """
    from ..services.scanner import probe_single_ip

    result = await db.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    if not device.mgmt_ip_id:
        raise HTTPException(status_code=400, detail="设备未配置管理IP，无法探测")

    ip_result = await db.execute(select(IPAddress).where(IPAddress.id == device.mgmt_ip_id))
    mgmt_ip = ip_result.scalar_one_or_none()
    if not mgmt_ip:
        raise HTTPException(status_code=400, detail="管理IP记录不存在，无法探测")

    probe = await probe_single_ip(mgmt_ip.address)
    # 回写探测结果，口径与网段扫描一致（在线才更新 MAC/端口）
    mgmt_ip.is_online = probe["is_online"]
    if probe["is_online"]:
        mgmt_ip.mac_address = probe.get("mac_address") or mgmt_ip.mac_address
        if probe.get("open_ports"):
            import json as _json
            mgmt_ip.open_ports = _json.dumps(probe["open_ports"])
    await db.commit()

    return {
        "device_id": device.id,
        "address": mgmt_ip.address,
        "is_online": probe["is_online"],
        "method": probe["method"],
        "open_ports": probe.get("open_ports") or [],
        "duration_ms": probe["duration_ms"],
    }


@router.post("/{device_id}/backup")
async def backup_device_config(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    if not device.mgmt_ip_id:
        raise HTTPException(status_code=400, detail="设备未配置管理IP")

    ip_result = await db.execute(
        select(IPAddress).where(IPAddress.id == device.mgmt_ip_id)
    )
    mgmt_ip = ip_result.scalar_one_or_none()
    if not mgmt_ip:
        raise HTTPException(status_code=400, detail="管理IP记录不存在")
    
    cred_result = await db.execute(select(Credential).where(Credential.device_id == device_id))
    credential = cred_result.scalar_one_or_none()
    if credential is None:
        raise HTTPException(status_code=400, detail="No credential found for device")
    
    from ..utils.crypto import decrypt_password
    
    device_info = {
        "ip": mgmt_ip.address,
        "username": credential.username,
        "password": decrypt_password(credential.password),
        "device_type": device.vendor or "cisco_ios",
        "port": credential.port or 22,
    }
    
    # netmiko 同步阻塞，放入线程执行，避免拖慢设备时卡死整个事件循环
    import asyncio
    config = await asyncio.to_thread(backup_config, device_info)
    if config is None:
        raise HTTPException(status_code=500, detail="Failed to backup device config")
    
    return {"message": "Backup successful", "config_size": len(config)}
