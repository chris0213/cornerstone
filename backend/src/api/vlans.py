from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update, delete
from typing import List, Optional

from ..database import get_db
from ..models import VlanGroup, Vlan, Prefix
from ..schemas import VlanGroupCreate, VlanGroupUpdate, VlanGroupResponse, VlanCreate, VlanUpdate, VlanResponse, PrefixResponse
from .dependencies import get_current_active_user, PageParams, pagination

router = APIRouter()


# === VLAN组相关接口 ===

@router.get("/vlans/groups/", response_model=list[VlanGroupResponse])
async def read_vlan_groups(
    page: PageParams = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """获取VLAN组列表"""
    result = await db.execute(select(VlanGroup).offset(page.skip).limit(page.limit))
    return result.scalars().all()


@router.post("/vlans/groups/", response_model=VlanGroupResponse, status_code=status.HTTP_201_CREATED)
async def create_vlan_group(
    vlan_group: VlanGroupCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """创建VLAN组"""
    stmt = insert(VlanGroup).values(**vlan_group.model_dump()).returning(VlanGroup)
    result = await db.execute(stmt)
    await db.commit()
    return result.scalar_one()


@router.put("/vlans/groups/{group_id}/", response_model=VlanGroupResponse)
async def update_vlan_group(
    group_id: int,
    vlan_group: VlanGroupUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """编辑VLAN组"""
    stmt = update(VlanGroup).where(VlanGroup.id == group_id).values(**vlan_group.model_dump(exclude_unset=True)).returning(VlanGroup)
    result = await db.execute(stmt)
    vlan_group = result.scalar_one_or_none()
    if vlan_group is None:
        raise HTTPException(status_code=404, detail="VLAN group not found")
    await db.commit()
    return vlan_group


@router.delete("/vlans/groups/{group_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vlan_group(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """删除VLAN组"""
    result = await db.execute(select(VlanGroup).where(VlanGroup.id == group_id))
    vlan_group = result.scalar_one_or_none()
    if vlan_group is None:
        raise HTTPException(status_code=404, detail="VLAN group not found")
    
    # 检查是否有VLAN关联到该组
    result = await db.execute(select(Vlan).where(Vlan.group_id == group_id))
    if result.scalars().first():
        raise HTTPException(status_code=400, detail={
            "code": "vlan.group_not_empty",
            "message": "该VLAN组下还有VLAN，请先删除关联的VLAN",
            "params": {},
        })
    
    await db.execute(delete(VlanGroup).where(VlanGroup.id == group_id))
    await db.commit()


# === VLAN相关接口 ===

@router.get("/vlans/", response_model=list[VlanResponse])
async def read_vlans(
    group_id: Optional[int] = None,
    site_id: Optional[int] = None,
    status: Optional[str] = None,
    page: PageParams = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """获取VLAN列表"""
    query = select(Vlan)
    
    if group_id is not None:
        query = query.where(Vlan.group_id == group_id)
    if site_id is not None:
        query = query.where(Vlan.site_id == site_id)
    if status is not None:
        query = query.where(Vlan.status == status)
    
    result = await db.execute(query.offset(page.skip).limit(page.limit))
    return result.scalars().all()


@router.post("/vlans/", response_model=VlanResponse, status_code=status.HTTP_201_CREATED)
async def create_vlan(
    vlan: VlanCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """创建VLAN（自动检测同组内VID重复）"""
    # 验证VID范围
    if vlan.vid < 1 or vlan.vid > 4094:
        raise HTTPException(status_code=400, detail={
            "code": "vlan.vid_out_of_range",
            "message": "VLAN ID必须在1-4094之间",
            "params": {"vid": vlan.vid},
        })

    # 检查同站点+同组内VID是否重复
    query = select(Vlan).where(Vlan.vid == vlan.vid)
    if vlan.site_id is None:
        query = query.where(Vlan.site_id.is_(None))
    else:
        query = query.where(Vlan.site_id == vlan.site_id)
    if vlan.group_id is None:
        query = query.where(Vlan.group_id.is_(None))
    else:
        query = query.where(Vlan.group_id == vlan.group_id)

    result = await db.execute(query)
    if result.scalars().first():
        raise HTTPException(status_code=400, detail={
            "code": "vlan.vid_exists",
            "message": f"该站点/组下 VLAN ID {vlan.vid}已存在",
            "params": {"vid": vlan.vid},
        })

    stmt = insert(Vlan).values(**vlan.model_dump()).returning(Vlan)
    result = await db.execute(stmt)
    await db.commit()
    return result.scalar_one()


@router.put("/vlans/{vlan_id}", response_model=VlanResponse)
async def update_vlan(
    vlan_id: int,
    vlan: VlanUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """编辑VLAN"""
    # 检查现有VLAN
    result = await db.execute(select(Vlan).where(Vlan.id == vlan_id))
    existing_vlan = result.scalar_one_or_none()
    
    if existing_vlan is None:
        raise HTTPException(status_code=404, detail="VLAN not found")
    
    # 如果修改了VID，检查同站点+同组内是否重复
    if vlan.vid is not None and vlan.vid != existing_vlan.vid:
        if vlan.vid < 1 or vlan.vid > 4094:
            raise HTTPException(status_code=400, detail={
                "code": "vlan.vid_out_of_range",
                "message": "VLAN ID必须在1-4094之间",
                "params": {"vid": vlan.vid},
            })
        
        query = select(Vlan).where(Vlan.vid == vlan.vid)
        if existing_vlan.site_id is None:
            query = query.where(Vlan.site_id.is_(None))
        else:
            query = query.where(Vlan.site_id == existing_vlan.site_id)
        if existing_vlan.group_id is None:
            query = query.where(Vlan.group_id.is_(None))
        else:
            query = query.where(Vlan.group_id == existing_vlan.group_id)
        
        result = await db.execute(query)
        if result.scalars().first():
            raise HTTPException(status_code=400, detail={
                "code": "vlan.vid_exists",
                "message": f"该站点/组下 VLAN ID {vlan.vid}已存在",
                "params": {"vid": vlan.vid},
            })
    
    stmt = update(Vlan).where(Vlan.id == vlan_id).values(**vlan.model_dump(exclude_unset=True)).returning(Vlan)
    result = await db.execute(stmt)
    await db.commit()
    return result.scalar_one()


@router.delete("/vlans/{vlan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vlan(
    vlan_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """删除VLAN"""
    result = await db.execute(select(Vlan).where(Vlan.id == vlan_id))
    vlan = result.scalar_one_or_none()
    if vlan is None:
        raise HTTPException(status_code=404, detail="VLAN not found")
    
    # 检查是否有子网关联到该VLAN（同VID且同站点口径，避免跨站点误拦）
    prefix_query = select(Prefix).where(Prefix.vlan == str(vlan.vid))
    if vlan.site_id is None:
        prefix_query = prefix_query.where(Prefix.site_id.is_(None))
    else:
        prefix_query = prefix_query.where(Prefix.site_id == vlan.site_id)
    result = await db.execute(prefix_query)
    if result.scalars().first():
        raise HTTPException(status_code=400, detail={
            "code": "vlan.has_prefixes",
            "message": "该VLAN已关联子网，请先解除关联",
            "params": {},
        })
    
    await db.execute(delete(Vlan).where(Vlan.id == vlan_id))
    await db.commit()


@router.get("/vlans/{vlan_id}/prefixes", response_model=list[PrefixResponse])
async def get_vlan_prefixes(
    vlan_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """获取VLAN关联的所有子网"""
    result = await db.execute(select(Vlan).where(Vlan.id == vlan_id))
    vlan = result.scalar_one_or_none()
    
    if not vlan:
        raise HTTPException(status_code=404, detail="VLAN not found")
    
    # 获取关联的子网（同VID且同站点口径，避免跨站点误关联）
    prefix_query = select(Prefix).where(Prefix.vlan == str(vlan.vid))
    if vlan.site_id is None:
        prefix_query = prefix_query.where(Prefix.site_id.is_(None))
    else:
        prefix_query = prefix_query.where(Prefix.site_id == vlan.site_id)
    result = await db.execute(prefix_query)
    return result.scalars().all()