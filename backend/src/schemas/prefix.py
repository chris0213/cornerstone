from datetime import datetime

import ipaddress
from pydantic import BaseModel, field_validator


def normalize_cidr(value: str) -> str:
    """校验并规范化 CIDR。

    - strip 首尾空白
    - RFC 1878 缩写补零：'192.168.16/23' → '192.168.16.0/23'、'192.168/16' → '192.168.0.0/16'
    - host bits 自动归零（strict=False）：'192.168.1.5/24' → '192.168.1.0/24'
    - 非法格式抛 ValueError（pydantic 转为 422 / 导入服务记为失败行）

    背景：曾出现缩写格式 '192.168.16/23' 直接入库，导致首页与 IPAM 页
    容量算法解析不一致（分母差 256）。录入端统一规范化杜绝再犯。
    """
    v = (value or "").strip()
    if not v:
        raise ValueError("network 不能为空")
    if "/" not in v:
        # 无 mask 的纯 IP 会被 ipaddress 解析为 /32 主机路由，而统计端对
        # 无 mask 输入按 254 兜底——口径不一致，录入必须显式带掩码
        raise ValueError("network 必须为 CIDR 格式（如 192.168.1.0/24），需包含掩码")
    if "/" in v:
        ip_part, mask = v.split("/", 1)
        parts = ip_part.split(".")
        if 1 <= len(parts) < 4 and all(p.strip().isdigit() for p in parts):
            v = ".".join(parts + ["0"] * (4 - len(parts))) + "/" + mask.strip()
    try:
        return str(ipaddress.ip_network(v, strict=False))
    except ValueError as e:
        raise ValueError(f"network 不是合法 CIDR（如 192.168.1.0/24）: {e}")


class PrefixCreate(BaseModel):
    aggregate_id: int | None = None
    network: str
    site_id: int | None = None
    vlan: str | None = None
    usage: str | None = None
    custom_scan_ports: str | None = None
    auto_scan_enabled: bool = False
    scan_cron: str = "0 */6 * * *"

    @field_validator("network")
    @classmethod
    def _normalize_network(cls, v: str) -> str:
        return normalize_cidr(v)


class PrefixUpdate(BaseModel):
    aggregate_id: int | None = None
    network: str | None = None
    site_id: int | None = None
    vlan: str | None = None
    usage: str | None = None
    custom_scan_ports: str | None = None
    auto_scan_enabled: bool | None = None
    scan_cron: str | None = None

    @field_validator("network")
    @classmethod
    def _normalize_network(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return normalize_cidr(v)


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
    ip_count: int = 0
    created_at: datetime
    updated_at: datetime | None

    class Config:
        from_attributes = True
