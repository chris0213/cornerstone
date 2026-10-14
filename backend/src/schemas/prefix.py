from pydantic import BaseModel
from datetime import datetime

class PrefixCreate(BaseModel):
    aggregate_id: int | None = None
    network: str
    site_id: int | None = None
    vlan: str | None = None
    usage: str | None = None
    custom_scan_ports: str | None = None
    auto_scan_enabled: bool = False
    scan_cron: str = "0 */6 * * *"

class PrefixUpdate(BaseModel):
    aggregate_id: int | None = None
    network: str | None = None
    site_id: int | None = None
    vlan: str | None = None
    usage: str | None = None
    custom_scan_ports: str | None = None
    auto_scan_enabled: bool | None = None
    scan_cron: str | None = None

class PrefixResponse(BaseModel):
    id: int
    aggregate_id: int | None
    network: str
    site_id: int | None
    vlan: str | None
    usage: str | None
    custom_scan_ports: str | None = None
    auto_scan_enabled: bool = False
    scan_cron: str = "0 */6 * * *"
    created_at: datetime
    updated_at: datetime | None

    class Config:
        from_attributes = True
