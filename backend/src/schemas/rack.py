from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class RackCreate(BaseModel):
    name: str
    site_id: Optional[int] = None
    room: Optional[str] = None
    row_position: Optional[int] = 0
    total_u: Optional[int] = 42
    status: Optional[str] = "active"
    description: Optional[str] = None


class RackUpdate(BaseModel):
    name: Optional[str] = None
    site_id: Optional[int] = None
    room: Optional[str] = None
    row_position: Optional[int] = None
    total_u: Optional[int] = None
    status: Optional[str] = None
    description: Optional[str] = None


class DevicePositionUpdate(BaseModel):
    rack_id: Optional[int] = None
    u_position: Optional[int] = None
    u_size: Optional[int] = 1


class RackDevice(BaseModel):
    """机柜内设备信息（用于 RackDetailResponse 中 devices 列表）"""
    id: int
    name: str
    type: Optional[str]
    vendor: Optional[str]
    model: Optional[str]
    sn: Optional[str]
    u_position: Optional[int]
    u_size: int
    status: str
    mgmt_ip: Optional[str] = None

    class Config:
        from_attributes = True


class RackStats(BaseModel):
    """机柜容量统计"""
    total_u: int
    used_u: int
    free_u: int
    utilization: float
    device_count: int


class RackResponse(BaseModel):
    id: int
    name: str
    site_id: Optional[int]
    room: Optional[str]
    row_position: int
    total_u: int
    status: str
    description: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]
    # 列表聚合字段（供前端侧边栏利用率条使用）
    used_u: int = 0
    utilization: float = 0.0
    device_count: int = 0

    class Config:
        from_attributes = True


class RackDetailResponse(RackResponse):
    devices: list[RackDevice] = []
    stats: Optional[RackStats] = None
