from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update, delete, func, and_

from ..database import get_db
from ..models import Rack, Device, Site
from ..schemas import (
    RackCreate, RackUpdate, RackResponse, RackDetailResponse,
    RackStats, RackDevice, DevicePositionUpdate
)
from .dependencies import (
    get_current_active_user,
    require_permission,
    PageParams,
    pagination,
)

router = APIRouter()


def _compute_rack_stats(total_u: int, devices: list) -> RackStats:
    used_u = sum(d.u_size for d in devices if d.u_position)
    free_u = total_u - used_u
    utilization = (used_u / total_u * 100) if total_u > 0 else 0.0
    return RackStats(
        total_u=total_u,
        used_u=used_u,
        free_u=free_u,
        utilization=round(utilization, 2),
        device_count=len(devices),
    )


@router.get("/", response_model=list[RackResponse])
async def list_racks(
    site_id: int | None = None,
    page: PageParams = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("devices:read")),
):
    stmt = select(Rack)
    if site_id:
        stmt = stmt.where(Rack.site_id == site_id)
    stmt = stmt.order_by(Rack.site_id, Rack.room, Rack.row_position, Rack.name).offset(page.skip).limit(page.limit)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{rack_id}", response_model=RackDetailResponse)
async def get_rack(
    rack_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("devices:read")),
):
    result = await db.execute(select(Rack).where(Rack.id == rack_id))
    rack = result.scalar_one_or_none()
    if rack is None:
        raise HTTPException(status_code=404, detail="Rack not found")

    devices_result = await db.execute(
        select(Device).where(Device.rack_id == rack_id).order_by(Device.u_position.desc())
    )
    devices = devices_result.scalars().all()

    return RackDetailResponse(
        id=rack.id,
        name=rack.name,
        site_id=rack.site_id,
        room=rack.room,
        row_position=rack.row_position or 0,
        total_u=rack.total_u or 42,
        status=rack.status or "active",
        description=rack.description,
        created_at=rack.created_at,
        updated_at=rack.updated_at,
        devices=[
            RackDevice(
                id=d.id,
                name=d.name,
                type=d.type,
                vendor=d.vendor,
                model=d.model,
                sn=d.sn,
                u_position=d.u_position,
                u_size=d.u_size or 1,
                status=d.status or "active",
            )
            for d in devices
        ],
        stats=_compute_rack_stats(rack.total_u or 42, devices),
    )


@router.get("/{rack_id}/stats", response_model=RackStats)
async def get_rack_stats(
    rack_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("devices:read")),
):
    result = await db.execute(select(Rack).where(Rack.id == rack_id))
    rack = result.scalar_one_or_none()
    if rack is None:
        raise HTTPException(status_code=404, detail="Rack not found")

    devices_result = await db.execute(select(Device).where(Device.rack_id == rack_id))
    devices = devices_result.scalars().all()
    return _compute_rack_stats(rack.total_u or 42, devices)


@router.post("/", response_model=RackResponse, status_code=status.HTTP_201_CREATED)
async def create_rack(
    payload: RackCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("sites:write")),
):
    if payload.site_id:
        check = await db.execute(select(Site.id).where(Site.id == payload.site_id))
        if not check.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Site not found")

    stmt = insert(Rack).values(**payload.model_dump()).returning(Rack)
    result = await db.execute(stmt)
    await db.commit()
    return result.scalar_one()


@router.put("/{rack_id}", response_model=RackResponse)
async def update_rack(
    rack_id: int,
    payload: RackUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("sites:write")),
):
    result = await db.execute(select(Rack).where(Rack.id == rack_id))
    rack = result.scalar_one_or_none()
    if rack is None:
        raise HTTPException(status_code=404, detail="Rack not found")

    data = payload.model_dump(exclude_unset=True)
    if data.get("site_id"):
        check = await db.execute(select(Site.id).where(Site.id == data["site_id"]))
        if not check.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Site not found")

    stmt = (
        update(Rack).where(Rack.id == rack_id).values(**data).returning(Rack)
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.scalar_one()


@router.delete("/{rack_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rack(
    rack_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("sites:delete")),
):
    result = await db.execute(select(Rack).where(Rack.id == rack_id))
    rack = result.scalar_one_or_none()
    if rack is None:
        raise HTTPException(status_code=404, detail="Rack not found")

    # 先解除所有设备的机架关联
    await db.execute(
        update(Device).where(Device.rack_id == rack_id).values(rack_id=None, u_position=None)
    )
    await db.execute(delete(Rack).where(Rack.id == rack_id))
    await db.commit()


# --- 设备位置更新端点 ---
@router.put("/devices/{device_id}/rack-position", response_model=RackDevice | None)
async def update_device_rack_position(
    device_id: int,
    payload: DevicePositionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("devices:write")),
):
    result = await db.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    rack_id = payload.rack_id
    u_position = payload.u_position
    u_size = payload.u_size or 1

    # 校验 rack_id 存在
    if rack_id:
        rack_check = await db.execute(select(Rack.id).where(Rack.id == rack_id))
        if not rack_check.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Rack not found")

    # 校验 U 位区间在机柜范围内 + 无重叠
    if rack_id and u_position is not None:
        rack_result = await db.execute(select(Rack.total_u).where(Rack.id == rack_id))
        total_u = (rack_result.scalar_one_or_none() or 42)
        if u_position < 1 or u_position + u_size - 1 > total_u:
            raise HTTPException(
                status_code=400,
                detail=f"U位超出范围: {u_position}-{u_position + u_size - 1} 总U数:{total_u}",
            )

        # 检查重叠（排除当前设备自身）
        overlap_check = await db.execute(
            select(Device).where(
                and_(
                    Device.rack_id == rack_id,
                    Device.id != device_id,
                    Device.u_position.isnot(None),
                    Device.u_position <= u_position + u_size - 1,
                    Device.u_position + Device.u_size - 1 >= u_position,
                )
            )
        )
        overlap = overlap_check.scalars().all()
        if overlap:
            names = ", ".join(d.name for d in overlap)
            raise HTTPException(
                status_code=400,
                detail=f"U位冲突: 与设备 [{names}] 占用位置重叠",
            )

    stmt = (
        update(Device)
        .where(Device.id == device_id)
        .values(rack_id=rack_id, u_position=u_position, u_size=u_size)
        .returning(Device)
    )
    result = await db.execute(stmt)
    await db.commit()
    updated = result.scalar_one_or_none()
    if updated is None:
        return None
    return RackDevice(
        id=updated.id,
        name=updated.name,
        type=updated.type,
        vendor=updated.vendor,
        model=updated.model,
        sn=updated.sn,
        u_position=updated.u_position,
        u_size=updated.u_size or 1,
        status=updated.status or "active",
    )
