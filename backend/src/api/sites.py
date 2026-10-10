from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update, delete

from ..database import get_db
from ..models import Site, Circuit, Device, Vlan, VlanGroup, Prefix, BackupTask, InspectionResult, InspectionTask, InspectionDeviceResult, DeviceFingerprint, IPAddress, Backup, LinkMonitor, DeviceLink, AlertRecord, AlertRule, Credential
from ..schemas import SiteCreate, SiteUpdate, SiteResponse
from .dependencies import get_current_active_user, PageParams, pagination

router = APIRouter()

@router.get("/", response_model=list[SiteResponse])
async def read_sites(
    page: PageParams = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(Site).offset(page.skip).limit(page.limit))
    return result.scalars().all()

@router.get("/{site_id}", response_model=SiteResponse)
async def read_site(
    site_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(Site).where(Site.id == site_id))
    site = result.scalar_one_or_none()
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")
    return site

@router.post("/", response_model=SiteResponse, status_code=status.HTTP_201_CREATED)
async def create_site(
    site: SiteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    stmt = insert(Site).values(**site.model_dump()).returning(Site)
    result = await db.execute(stmt)
    await db.commit()
    return result.scalar_one()

@router.put("/{site_id}", response_model=SiteResponse)
async def update_site(
    site_id: int,
    site: SiteUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(Site).where(Site.id == site_id))
    existing_site = result.scalar_one_or_none()
    if existing_site is None:
        raise HTTPException(status_code=404, detail="Site not found")
    
    stmt = update(Site).where(Site.id == site_id).values(**site.model_dump(exclude_unset=True)).returning(Site)
    result = await db.execute(stmt)
    await db.commit()
    return result.scalar_one()

@router.delete("/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_site(
    site_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(Site).where(Site.id == site_id))
    site = result.scalar_one_or_none()
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")
    
    await db.execute(delete(Circuit).where(Circuit.site_id == site_id))
    await db.execute(delete(Vlan).where(Vlan.site_id == site_id))
    await db.execute(delete(VlanGroup).where(VlanGroup.site_id == site_id))
    await db.execute(delete(BackupTask).where(BackupTask.site_id == site_id))
    
    await db.execute(update(Device).where(Device.site_id == site_id).values(mgmt_ip_id=None))
    
    await db.execute(delete(LinkMonitor).where(LinkMonitor.device_id.in_(select(Device.id).where(Device.site_id == site_id))))
    await db.execute(delete(DeviceLink).where(DeviceLink.source_device_id.in_(select(Device.id).where(Device.site_id == site_id))))
    await db.execute(delete(DeviceLink).where(DeviceLink.target_device_id.in_(select(Device.id).where(Device.site_id == site_id))))
    await db.execute(delete(Backup).where(Backup.device_id.in_(select(Device.id).where(Device.site_id == site_id))))
    await db.execute(delete(AlertRecord).where(AlertRecord.device_id.in_(select(Device.id).where(Device.site_id == site_id))))
    await db.execute(delete(AlertRule).where(AlertRule.device_id.in_(select(Device.id).where(Device.site_id == site_id))))
    
    await db.execute(delete(IPAddress).where(IPAddress.device_id.in_(select(Device.id).where(Device.site_id == site_id))))
    await db.execute(delete(IPAddress).where(IPAddress.prefix_id.in_(select(Prefix.id).where(Prefix.site_id == site_id))))
    
    await db.execute(delete(Credential).where(Credential.device_id.in_(select(Device.id).where(Device.site_id == site_id))))
    await db.execute(delete(InspectionDeviceResult).where(InspectionDeviceResult.device_id.in_(select(Device.id).where(Device.site_id == site_id))))
    await db.execute(delete(DeviceFingerprint).where(DeviceFingerprint.device_id.in_(select(Device.id).where(Device.site_id == site_id))))
    await db.execute(delete(Device).where(Device.site_id == site_id))
    
    await db.execute(delete(InspectionResult).where(InspectionResult.task_id.in_(select(InspectionTask.id).where(InspectionTask.site_id == site_id))))
    await db.execute(delete(InspectionTask).where(InspectionTask.site_id == site_id))
    
    await db.execute(delete(Prefix).where(Prefix.site_id == site_id))
    await db.execute(delete(Site).where(Site.id == site_id))
    await db.commit()
