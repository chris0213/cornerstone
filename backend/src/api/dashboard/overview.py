"""仪表盘 API - overview"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import get_db
from src.api.dependencies import get_current_active_user
from .common import IP_OCCUPIED_STATUSES
from src.models.user import User
from src.models.circuit import Circuit
from src.models.device import Device
from src.models.prefix import Prefix
from src.models.ip_address import IPAddress
from src.models.backup import Backup
from src.models.audit_log import AuditLog
from src.models.site import Site
from src.models.link_monitor import LinkMonitor
from src.models.alert import AlertRecord

router = APIRouter()


@router.get("/stats")
async def get_dashboard_stats(
    time_range: str = "all",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """获取仪表盘统计数据"""
    
    # 解析时间范围参数
    now = datetime.now()
    start_time = None
    
    if time_range == "24h":
        start_time = now - timedelta(hours=24)
    elif time_range == "7d":
        start_time = now - timedelta(days=7)
    elif time_range == "15d":
        start_time = now - timedelta(days=15)
    elif time_range == "30d":
        start_time = now - timedelta(days=30)
    elif time_range == "all":
        start_time = None
    else:
        start_time = None
    
    # 1~5、8：简单 count 合并为一条查询（标量子查询），避免逐项串行往返
    counts = (await db.execute(
        select(
            select(func.count(Site.id)).scalar_subquery().label("total_sites"),
            select(func.count(Device.id)).scalar_subquery().label("total_devices"),
            select(func.count(func.distinct(LinkMonitor.device_id)))
            .where(LinkMonitor.status == 'normal')
            .scalar_subquery().label("online_devices"),
            # IP 占用口径与 IPAM 页 prefix.ipCount 一致：已分配+预留（兼容中文存量），且归属子网
            select(func.count(IPAddress.id))
            .where(IPAddress.status.in_(IP_OCCUPIED_STATUSES),
                   IPAddress.prefix_id != None)
            .scalar_subquery().label("ip_used"),
            select(func.count(AlertRecord.id))
            .where(AlertRecord.status == 'active')
            .scalar_subquery().label("pending_alerts"),
        )
    )).one()
    total_sites = counts.total_sites
    total_devices = counts.total_devices
    online_devices = counts.online_devices
    ip_used = counts.ip_used
    pending_alerts = counts.pending_alerts

    # 2~3：专线总量/正常数/带宽合并为一条聚合查询
    total_circuits, normal_circuits, total_bandwidth = (await db.execute(
        select(
            func.count(Circuit.id),
            func.coalesce(func.sum(case((Circuit.status == '正常', 1), else_=0)), 0),
            func.coalesce(func.sum(case((Circuit.status == '正常', Circuit.bandwidth), else_=0)), 0),
        )
    )).one()

    # 5. IP地址统计
    # 获取所有前缀并计算实际可用IP数量
    prefixes_result = await db.execute(select(Prefix.network))
    prefixes = prefixes_result.scalars().all()

    # 根据CIDR掩码计算每个子网的可用IP数量
    def calculate_usable_ips(network: str) -> int:
        """根据CIDR格式计算可用IP数量"""
        try:
            if '/' in network:
                prefix_length = int(network.split('/')[1])
                # 可用IP数 = 2^(32-prefix_length) - 2（减去网络地址和广播地址）
                if prefix_length >= 31:
                    return 1 if prefix_length == 32 else 2  # /32只有1个IP，/31有2个
                return 2 ** (32 - prefix_length) - 2
            return 254  # 默认/24
        except:
            return 254

    ip_total = sum(calculate_usable_ips(prefix) for prefix in prefixes) if prefixes else 0

    ip_usage_percent = round((ip_used / ip_total * 100), 1) if ip_total > 0 else 0

    # 6. 备份统计（总量/成功/失败合并为一条聚合查询）
    backup_stmt = select(
        func.count(Backup.id),
        func.coalesce(func.sum(case((Backup.status == 'success', 1), else_=0)), 0),
        func.coalesce(func.sum(case((Backup.status == 'failed', 1), else_=0)), 0),
    )
    if start_time:
        backup_stmt = backup_stmt.where(Backup.created_at >= start_time)
    total_backups, successful_backups, failed_backups = (await db.execute(backup_stmt)).one()
    
    # 7. 系统健康度计算
    # 基于设备监控状态计算健康度
    health_score = 100
    
    # 获取设备监控状态分布
    health_query = (
        select(
            LinkMonitor.status,
            func.count(LinkMonitor.id).label("count")
        )
        .group_by(LinkMonitor.status)
    )
    health_result = await db.execute(health_query)
    health_data = health_result.all()
    
    total_monitored = sum(count for _, count in health_data) if health_data else 0
    
    # 使用告警占总监控数的比例来计算健康度扣分
    for status, count in health_data:
        if status == 'critical':
            health_score -= (count / total_monitored * 100) * 0.5 if total_monitored > 0 else 0
        elif status == 'warning':
            health_score -= (count / total_monitored * 100) * 0.25 if total_monitored > 0 else 0
    
    health_score = max(0, min(100, round(health_score)))

    return {
        "sites": {
            "total": total_sites
        },
        "circuits": {
            "total": total_circuits,
            "normal": normal_circuits,
            "bandwidth": total_bandwidth
        },
        "devices": {
            "total": total_devices,
            "online": online_devices,
            "offline": total_devices - online_devices
        },
        "ip": {
            "total": ip_total,
            "used": ip_used,
            "percent": ip_usage_percent
        },
        "backups": {
            "total": total_backups,
            "successful": successful_backups,
            "failed": failed_backups
        },
        "health": {
            "score": health_score,
            "status": "excellent" if health_score >= 90 else "good" if health_score >= 70 else "warning" if health_score >= 50 else "critical"
        },
        "alerts": {
            "pending": pending_alerts
        }
    }


@router.get("/prefixes-usage")
async def get_prefixes_usage(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """获取子网使用率"""
    
    def calculate_usable_ips(network: str) -> int:
        """根据CIDR格式计算可用IP数量"""
        try:
            if '/' in network:
                prefix_length = int(network.split('/')[1])
                if prefix_length >= 31:
                    return 1 if prefix_length == 32 else 2
                return 2 ** (32 - prefix_length) - 2
            return 254
        except:
            return 254
    
    # 获取所有前缀
    prefixes_result = await db.execute(select(Prefix))
    prefixes = prefixes_result.scalars().all()

    # 一次 GROUP BY 查出各前缀占用 IP 数（占用口径与 IPAM 页 ipCount 一致：已分配+预留）
    counts_result = await db.execute(
        select(IPAddress.prefix_id, func.count(IPAddress.id))
        .where(IPAddress.status.in_(IP_OCCUPIED_STATUSES))
        .group_by(IPAddress.prefix_id)
    )
    assigned_by_prefix = dict(counts_result.all())

    # 计算每个前缀的IP使用情况
    usage_list = []
    for prefix in prefixes:
        usable_ips = calculate_usable_ips(prefix.network)
        ip_count = assigned_by_prefix.get(prefix.id, 0)

        # 计算使用率（根据实际CIDR计算可用IP数）
        usage_percent = round((ip_count / usable_ips) * 100, 1) if usable_ips > 0 else 0
        
        usage_list.append({
            "id": prefix.id,
            "network": prefix.network,
            "vlan": prefix.vlan,
            "usage": f"{ip_count}/{usable_ips}",
            "usage_percent": usage_percent
        })
    
    return usage_list


@router.get("/recent-logs")
async def get_recent_logs(
    limit: int = 8,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """获取最近的操作日志"""
    
    logs_result = await db.execute(
        select(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    logs = logs_result.scalars().all()
    
    return [
        {
            "id": log.id,
            "user": log.user,
            "action": log.action,
            "resource": log.resource,
            "detail": log.detail,
            "success": log.success,
            "ip_address": log.ip_address,
            "created_at": log.created_at.isoformat() if log.created_at else None
        }
        for log in logs
    ]
