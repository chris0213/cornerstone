from pydantic import BaseModel, field_validator
from datetime import datetime

from ..constants.device_type import normalize_device_type


def _validate_device_type(value: str | None) -> str | None:
    """设备类型枚举校验：归一化历史中文别名，未知值拒绝。"""
    return normalize_device_type(value)

class DeviceCreate(BaseModel):
    name: str
    type: str | None = None
    vendor: str | None = None
    model: str | None = None
    sn: str | None = None
    asset_tag: str | None = None
    site_id: int | None = None
    location: str | None = None
    mgmt_ip_id: int | None = None
    status: str = "active"
    purchase_date: datetime | None = None
    warranty_end: datetime | None = None
    purchase_amount: float | None = None
    owner: str | None = None
    note: str | None = None

    _validate_type = field_validator("type")(_validate_device_type)

class DeviceUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    vendor: str | None = None
    model: str | None = None
    sn: str | None = None
    asset_tag: str | None = None
    site_id: int | None = None
    location: str | None = None
    mgmt_ip_id: int | None = None
    status: str | None = None
    purchase_date: datetime | None = None
    warranty_end: datetime | None = None
    purchase_amount: float | None = None
    owner: str | None = None
    note: str | None = None

    _validate_type = field_validator("type")(_validate_device_type)

class DeviceResponse(BaseModel):
    id: int
    name: str
    type: str | None
    vendor: str | None
    model: str | None
    sn: str | None
    asset_tag: str | None = None
    site_id: int | None
    location: str | None
    mgmt_ip_id: int | None
    status: str
    purchase_date: datetime | None
    warranty_end: datetime | None
    purchase_amount: float | None
    owner: str | None
    note: str | None
    created_at: datetime
    updated_at: datetime | None
    
    class Config:
        from_attributes = True
