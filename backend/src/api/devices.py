from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update, delete
from datetime import datetime, timezone

from ..database import get_db
from ..models import Device, Credential, LinkMonitor, DeviceLink, Backup, AlertRecord, AlertRule, IPAddress, InspectionDeviceResult, DeviceFingerprint
from ..schemas import (
    DeviceCreate, DeviceUpdate, DeviceResponse,
    CredentialCreate, CredentialUpdate, CredentialResponse
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
    
    config = backup_config(device_info)
    if config is None:
        raise HTTPException(status_code=500, detail="Failed to backup device config")
    
    return {"message": "Backup successful", "config_size": len(config)}

# Credential routes
@router.get("/{device_id}/credentials", response_model=list[CredentialResponse])
async def read_credentials(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(Credential).where(Credential.device_id == device_id))
    return result.scalars().all()

@router.post("/{device_id}/credentials", response_model=CredentialResponse, status_code=status.HTTP_201_CREATED)
async def create_credential(
    device_id: int,
    credential: CredentialCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    
    data = credential.model_dump()
    data["device_id"] = device_id

    from ..utils.crypto import encrypt_password
    if data.get("password"):
        data["password"] = encrypt_password(data["password"])
    if data.get("enable_password"):
        data["enable_password"] = encrypt_password(data["enable_password"])
    if data.get("private_key"):
        data["private_key"] = encrypt_password(data["private_key"])
    if data.get("jump_password"):
        data["jump_password"] = encrypt_password(data["jump_password"])

    stmt = insert(Credential).values(**data).returning(Credential)
    result = await db.execute(stmt)
    await db.commit()
    return result.scalar_one()

@router.put("/credentials/{credential_id}", response_model=CredentialResponse)
async def update_credential(
    credential_id: int,
    credential: CredentialUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    data = credential.model_dump(exclude_unset=True)

    from ..utils.crypto import encrypt_password
    if data.get("password") and data["password"] != "********":
        data["password"] = encrypt_password(data["password"])
    if data.get("enable_password") and data["enable_password"] != "********":
        data["enable_password"] = encrypt_password(data["enable_password"])
    if data.get("private_key") and data["private_key"] != "********":
        data["private_key"] = encrypt_password(data["private_key"])
    if data.get("jump_password") and data["jump_password"] != "********":
        data["jump_password"] = encrypt_password(data["jump_password"])

    stmt = update(Credential).where(Credential.id == credential_id).values(**data).returning(Credential)
    result = await db.execute(stmt)
    credential = result.scalar_one_or_none()
    if credential is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    await db.commit()
    return credential

@router.delete("/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    credential_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(Credential).where(Credential.id == credential_id))
    credential = result.scalar_one_or_none()
    if credential is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    await db.execute(delete(Credential).where(Credential.id == credential_id))
    await db.commit()
