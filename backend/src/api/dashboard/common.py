"""仪表盘公共依赖"""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from src.models.user import User

BJT = timezone(timedelta(hours=8))  # 北京时间

# IP「业务占用」口径：已分配 + 预留（不含未分配），与 IPAM 页 prefix.ipCount 聚合一致；
# 同时兼容英文枚举与 DB 存量中文值（扫描器/表单历史上写入过两种）
IP_OCCUPIED_STATUSES = ("assigned", "active", "已分配", "reserved", "预留")


def calculate_usable_ips(network: str) -> int:
    """CIDR → 可用主机容量，与 IPAM 前端 getPrefixCapacity 同一套规则：
    /32→1、/31→2、其余 2^(32-mask)-2（下限 1）；mask<8 或 >32 或解析失败 → 254。

    解析用 float+strip（容忍 '23.0'/空白等录入变体，与前端 Number 行为对齐），
    保证首页与 IPAM 页对同一份数据算出相同总容量。历史教训：int('23.0') 抛异常
    走 254 兜底而前端按 23 算 510，单条即造成 256 的分母偏差。
    """
    try:
        ip_str, mask_str = network.split('/', 1)
        mask_f = float(mask_str.strip())
        if mask_f != int(mask_f):
            return 254
        mask = int(mask_f)
        if mask < 8 or mask > 32:
            return 254
        octets = ip_str.strip().split('.')
        if len(octets) != 4:
            return 254
        vals = [int(o) for o in octets]
        if any(v < 0 or v > 255 for v in vals):
            return 254
        if mask == 32:
            return 1
        if mask == 31:
            return 2
        return max(2 ** (32 - mask) - 2, 1)
    except (ValueError, AttributeError):
        return 254


def to_naive_bjt(dt: datetime) -> datetime:
    """DB 时间转北京挂钟 naive（PG timestamptz 返回 aware UTC，SQLite 返回 naive）

    用于 naive 时间运算（如 now - db_value）以及显示日期，避免 aware/naive 混算抛 TypeError。
    """
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(BJT).replace(tzinfo=None)


def require_manager_or_admin(current_user: User) -> None:
    """验证用户角色为 viewer 或 super_admin"""
    if current_user.role.name not in ['viewer', 'super_admin']:
        raise HTTPException(status_code=403, detail="此接口需要IT负责人或管理员权限")
