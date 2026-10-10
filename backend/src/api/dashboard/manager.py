"""仪表盘 API - manager"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import get_db
from src.models.circuit import Circuit
from src.models.device import Device
from src.models.prefix import Prefix
from src.models.ip_address import IPAddress
from src.models.backup import Backup
from src.models.site import Site
from src.models.link_monitor import LinkMonitor
from src.models.circuit_incident import CircuitIncident
from src.api.auth import get_current_active_user
from src.models.user import User
from .common import require_manager_or_admin, to_naive_bjt

router = APIRouter()


# ==================== IT负责人管理看板接口 ====================

@router.get("/manager-stats")
async def get_manager_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """获取管理看板四个核心指标"""
    require_manager_or_admin(current_user)
    
    now = datetime.now()
    today = now.date()
    month_start = datetime(now.year, now.month, 1)
    
    # 上月时间范围
    if now.month == 1:
        last_month_start = datetime(now.year - 1, 12, 1)
        last_month_end = datetime(now.year - 1, 12, 31)
    else:
        last_month_start = datetime(now.year, now.month - 1, 1)
        last_month_end = datetime(now.year, now.month, 1) - timedelta(days=1)
    
    # 1. 网络可用性（本月设备在线时长 / 总时长）
    # 统计本月所有设备的监控状态
    month_devices_result = await db.execute(
        select(Device.id).where(Device.status == 'active')
    )
    total_devices = len(month_devices_result.scalars().all())
    
    # 获取本月在线设备统计
    online_stats_result = await db.execute(
        select(
            LinkMonitor.status,
            func.count(LinkMonitor.id).label('count')
        )
        .where(LinkMonitor.created_at >= month_start)
        .group_by(LinkMonitor.status)
    )
    online_stats = {row.status: row.count for row in online_stats_result.all()}
    total_records = sum(online_stats.values()) if online_stats else 0
    # normal = 在线正常，warning/critical = 离线/异常
    online_records = online_stats.get('normal', 0)
    
    current_availability = round((online_records / total_records * 100), 1) if total_records > 0 else None
    
    # 上月可用性
    last_month_online_stats_result = await db.execute(
        select(
            LinkMonitor.status,
            func.count(LinkMonitor.id).label('count')
        )
        .where(and_(
            LinkMonitor.created_at >= last_month_start,
            LinkMonitor.created_at <= last_month_end
        ))
        .group_by(LinkMonitor.status)
    )
    last_month_stats = {row.status: row.count for row in last_month_online_stats_result.all()}
    last_month_total = sum(last_month_stats.values()) if last_month_stats else 0
    last_month_online = last_month_stats.get('normal', 0)
    last_month_availability = round((last_month_online / last_month_total * 100), 1) if last_month_total > 0 else None
    
    availability_trend = None
    if current_availability and last_month_availability:
        if current_availability > last_month_availability:
            availability_trend = "up"
        elif current_availability < last_month_availability:
            availability_trend = "down"
        else:
            availability_trend = "stable"
    
    # 2. 专线月租费用
    current_cost_result = await db.execute(
        select(func.coalesce(func.sum(Circuit.monthly_cost), 0))
        .where(or_(Circuit.status == 'active', Circuit.status == '正常'))
    )
    current_cost = current_cost_result.scalar() or 0
    
    # 上月费用（假设上月专线数量和费用不变，取当前active专线的费用作为上月参考）
    # 实际应该从历史记录获取，但当前表结构没有费用变更历史
    last_month_cost = current_cost  # 简化处理
    
    cost_trend = None
    if current_cost > 0 and last_month_cost > 0:
        if current_cost > last_month_cost:
            cost_trend = "up"
        elif current_cost < last_month_cost:
            cost_trend = "down"
        else:
            cost_trend = "stable"
    
    # 3. 未解决故障
    open_incidents_result = await db.execute(
        select(func.count(CircuitIncident.id))
        .where(CircuitIncident.status == 'open')
    )
    open_incidents_count = open_incidents_result.scalar() or 0
    
    # 最长持续时长
    max_duration_hours = 0
    if open_incidents_count > 0:
        oldest_open_result = await db.execute(
            select(CircuitIncident.started_at)
            .where(CircuitIncident.status == 'open')
            .order_by(CircuitIncident.started_at.asc())
            .limit(1)
        )
        oldest = oldest_open_result.scalar_one_or_none()
        if oldest:
            # PG timestamptz 返回 aware UTC，与 naive now 混算会抛 TypeError，先归一
            max_duration_hours = round((now - to_naive_bjt(oldest)).total_seconds() / 3600, 1)
    
    # 4. 即将到期事项（两级预警）
    now_dt = now
    thirty_days_later = now_dt + timedelta(days=30)
    sixty_days_later = now_dt + timedelta(days=60)
    
    # 🔴 紧急（30天内到期的专线合同）
    urgent_circuits_result = await db.execute(
        select(Circuit.id, Circuit.name, Circuit.contract_end, Circuit.provider)
        .where(and_(
            Circuit.contract_end != None,
            Circuit.contract_end <= thirty_days_later,
            Circuit.contract_end >= now_dt
        ))
    )
    urgent_circuits = [
        {
            "type": "专线合同",
            "name": c.name,
            "expire_date": to_naive_bjt(c.contract_end).strftime("%Y-%m-%d"),
            "days_left": (to_naive_bjt(c.contract_end).date() - now_dt.date()).days,
            "detail": c.provider or ""
        }
        for c in urgent_circuits_result.all()
    ]
    
    # 🔴 紧急（30天内到期的设备保修）
    urgent_warranties_result = await db.execute(
        select(Device.id, Device.name, Device.warranty_end, Device.model)
        .where(and_(
            Device.warranty_end != None,
            Device.warranty_end <= thirty_days_later,
            Device.warranty_end >= now_dt
        ))
    )
    urgent_warranties = [
        {
            "type": "设备保修",
            "name": d.name,
            "expire_date": d.warranty_end.strftime("%Y-%m-%d"),
            "days_left": (d.warranty_end.date() - now_dt.date()).days,
            "detail": d.model or ""
        }
        for d in urgent_warranties_result.all()
    ]
    
    # 🟡 即将到期（31-60天内到期的专线合同）
    warning_circuits_result = await db.execute(
        select(Circuit.id, Circuit.name, Circuit.contract_end, Circuit.provider)
        .where(and_(
            Circuit.contract_end != None,
            Circuit.contract_end <= sixty_days_later,
            Circuit.contract_end > thirty_days_later
        ))
    )
    warning_circuits = [
        {
            "type": "专线合同",
            "name": c.name,
            "expire_date": c.contract_end.strftime("%Y-%m-%d"),
            "days_left": (c.contract_end.date() - now_dt.date()).days,
            "detail": c.provider or ""
        }
        for c in warning_circuits_result.all()
    ]
    
    # 🟡 即将到期（31-60天内到期的设备保修）
    warning_warranties_result = await db.execute(
        select(Device.id, Device.name, Device.warranty_end, Device.model)
        .where(and_(
            Device.warranty_end != None,
            Device.warranty_end <= sixty_days_later,
            Device.warranty_end > thirty_days_later
        ))
    )
    warning_warranties = [
        {
            "type": "设备保修",
            "name": d.name,
            "expire_date": d.warranty_end.strftime("%Y-%m-%d"),
            "days_left": (d.warranty_end.date() - now_dt.date()).days,
            "detail": d.model or ""
        }
        for d in warning_warranties_result.all()
    ]
    
    urgent_items = urgent_circuits + urgent_warranties
    warning_items = warning_circuits + warning_warranties
    
    return {
        "availability": {
            "current": current_availability,
            "last_month": last_month_availability,
            "trend": availability_trend
        },
        "circuit_cost": {
            "current": int(current_cost),
            "last_month": int(last_month_cost),
            "trend": cost_trend
        },
        "open_incidents": {
            "count": open_incidents_count,
            "max_duration_hours": max_duration_hours
        },
        "expiring_soon": {
            "urgent_count": len(urgent_items),
            "warning_count": len(warning_items),
            "total_count": len(urgent_items) + len(warning_items),
            "urgent_items": sorted(urgent_items, key=lambda x: x["days_left"]),
            "warning_items": sorted(warning_items, key=lambda x: x["days_left"])
        }
    }


@router.get("/risks")
async def get_risks(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """获取IT风险看板数据"""
    require_manager_or_admin(current_user)
    
    now = datetime.now()
    thirty_days_later = now + timedelta(days=30)
    sixty_days_later = now + timedelta(days=60)
    five_years_ago = now - timedelta(days=365 * 5)
    three_years_ago = now - timedelta(days=365 * 3)
    
    risks = []
    
    # ===== 高风险 =====
    
    # 1. 保修已过期的设备
    expired_warranty_result = await db.execute(
        select(Device.name, Device.model, Site.name)
        .join(Site, Device.site_id == Site.id, isouter=True)
        .where(and_(
            Device.warranty_end != None,
            Device.warranty_end < now
        ))
    )
    expired_warranties = expired_warranty_result.all()
    if expired_warranties:
        names = "、".join([d.name for d in expired_warranties[:3]])
        if len(expired_warranties) > 3:
            names += f"等{len(expired_warranties)}台"
        risks.append({
            "severity": "high",
            "category": "warranty",
            "title": f"{len(expired_warranties)}台设备保修已过期",
            "description": f"{names} 保修已过期，故障无法获得厂商支持",
            "count": len(expired_warranties),
            "resource_ids": [],
            "action_url": "/devices?filter=warranty_expired"
        })
    
    # 2. 专线合同30天内到期
    expiring_circuits_result = await db.execute(
        select(Circuit.name, Circuit.contract_end)
        .where(and_(
            Circuit.contract_end != None,
            Circuit.contract_end <= thirty_days_later,
            Circuit.contract_end >= now
        ))
    )
    expiring_circuits = expiring_circuits_result.all()
    if expiring_circuits:
        names = "、".join([c.name for c in expiring_circuits[:3]])
        if len(expiring_circuits) > 3:
            names += f"等{len(expiring_circuits)}条"
        risks.append({
            "severity": "high",
            "category": "circuit",
            "title": f"{len(expiring_circuits)}条专线合同即将到期",
            "description": f"{names} 将于30天内到期，请尽快启动续签",
            "count": len(expiring_circuits),
            "resource_ids": [],
            "action_url": "/circuits?filter=contract_expiring"
        })
    
    # 3. 当前处于故障状态的专线
    fault_circuits_result = await db.execute(
        select(func.count(Circuit.id))
        .where(Circuit.status == '故障')
    )
    fault_circuits_count = fault_circuits_result.scalar() or 0
    if fault_circuits_count > 0:
        risks.append({
            "severity": "high",
            "category": "circuit",
            "title": f"{fault_circuits_count}条专线当前处于故障状态",
            "description": "有专线目前无法正常使用，请关注故障处理进度",
            "count": fault_circuits_count,
            "resource_ids": [],
            "action_url": "/circuits?status=fault"
        })
    
    # ===== 中风险 =====
    
    # 1. 配置备份连续失败超过3次
    failed_backups_result = await db.execute(
        select(
            Device.name,
            func.count(Backup.id).label('fail_count')
        )
        .join(Device, Backup.device_id == Device.id)
        .where(and_(
            Backup.status == 'failed',
            Backup.created_at >= now - timedelta(days=7)
        ))
        .group_by(Device.id, Device.name)
        .having(func.count(Backup.id) > 3)
    )
    failed_backups = failed_backups_result.all()
    for fb in failed_backups:
        risks.append({
            "severity": "medium",
            "category": "backup",
            "title": f"{fb.name} 配置备份连续失败",
            "description": f"{fb.name} 配置备份连续失败超过3次，请检查设备连接",
            "count": fb.fail_count,
            "resource_ids": [],
            "action_url": f"/devices/{fb.device_id}/backups"
        })
    
    # 2. 子网使用率超过90%
    def calculate_usable_ips(network: str) -> int:
        try:
            if '/' in network:
                prefix_length = int(network.split('/')[1])
                if prefix_length >= 31:
                    return 1 if prefix_length == 32 else 2
                return 2 ** (32 - prefix_length) - 2
            return 254
        except:
            return 254
    
    prefixes_result = await db.execute(select(Prefix))
    prefixes = prefixes_result.scalars().all()
    for prefix in prefixes:
        usable_ips = calculate_usable_ips(prefix.network)
        ip_count_result = await db.execute(
            select(func.count(IPAddress.id))
            .where(and_(
                IPAddress.prefix_id == prefix.id,
                IPAddress.status == 'assigned'
            ))
        )
        ip_count = ip_count_result.scalar() or 0
        usage_percent = (ip_count / usable_ips * 100) if usable_ips > 0 else 0
        
        if usage_percent > 90:
            risks.append({
                "severity": "medium",
                "category": "subnet",
                "title": f"{prefix.network} 子网使用率过高",
                "description": f"{prefix.network} 使用率达{int(usage_percent)}%，即将耗尽",
                "count": int(usage_percent),
                "resource_ids": [],
                "action_url": f"/ipam?prefix={prefix.id}"
            })
    
    # 3. 设备保修60天内到期
    expiring_warranty_result = await db.execute(
        select(Device.name, Device.warranty_end)
        .where(and_(
            Device.warranty_end != None,
            Device.warranty_end <= sixty_days_later,
            Device.warranty_end > now
        ))
    )
    expiring_warranties = expiring_warranty_result.all()
    if expiring_warranties:
        names = "、".join([d.name for d in expiring_warranties[:3]])
        if len(expiring_warranties) > 3:
            names += f"等{len(expiring_warranties)}台"
        risks.append({
            "severity": "medium",
            "category": "warranty",
            "title": f"{len(expiring_warranties)}台设备保修即将到期",
            "description": f"{names} 保修将在60天内到期",
            "count": len(expiring_warranties),
            "resource_ids": [],
            "action_url": "/devices?filter=warranty_expiring"
        })
    
    # 4. 设备使用年限超过5年
    old_devices_result = await db.execute(
        select(Device.name, Device.purchase_date)
        .where(and_(
            Device.purchase_date != None,
            Device.purchase_date < five_years_ago
        ))
    )
    old_devices = old_devices_result.all()
    if old_devices:
        names = "、".join([d.name for d in old_devices[:3]])
        if len(old_devices) > 3:
            names += f"等{len(old_devices)}台"
        risks.append({
            "severity": "medium",
            "category": "device_age",
            "title": f"{len(old_devices)}台设备使用年限超过5年",
            "description": f"{names} 使用年限较长，建议评估替换计划",
            "count": len(old_devices),
            "resource_ids": [],
            "action_url": "/devices?filter=old_devices"
        })
    
    # ===== 低风险 =====
    
    # 1. 设备使用年限3-5年
    mid_old_devices_result = await db.execute(
        select(Device.name, Device.purchase_date)
        .where(and_(
            Device.purchase_date != None,
            Device.purchase_date >= five_years_ago,
            Device.purchase_date < three_years_ago
        ))
    )
    mid_old_devices = mid_old_devices_result.all()
    if mid_old_devices:
        risks.append({
            "severity": "low",
            "category": "device_age",
            "title": f"{len(mid_old_devices)}台设备使用年限3-5年",
            "description": "部分设备即将进入高龄阶段，建议关注维护状态",
            "count": len(mid_old_devices),
            "resource_ids": [],
            "action_url": "/devices?filter=aging_devices"
        })
    
    # 2. 子网使用率80%-90%
    for prefix in prefixes:
        usable_ips = calculate_usable_ips(prefix.network)
        ip_count_result = await db.execute(
            select(func.count(IPAddress.id))
            .where(and_(
                IPAddress.prefix_id == prefix.id,
                IPAddress.status == 'assigned'
            ))
        )
        ip_count = ip_count_result.scalar() or 0
        usage_percent = (ip_count / usable_ips * 100) if usable_ips > 0 else 0
        
        if 80 <= usage_percent <= 90:
            risks.append({
                "severity": "low",
                "category": "subnet",
                "title": f"{prefix.network} 子网使用率较高",
                "description": f"{prefix.network} 使用率{int(usage_percent)}%，建议关注",
                "count": int(usage_percent),
                "resource_ids": [],
                "action_url": f"/ipam?prefix={prefix.id}"
            })
    
    # 3. 专线合同60天内到期
    later_circuits_result = await db.execute(
        select(Circuit.name)
        .where(and_(
            Circuit.contract_end != None,
            Circuit.contract_end <= sixty_days_later,
            Circuit.contract_end > thirty_days_later
        ))
    )
    later_circuits = later_circuits_result.all()
    if later_circuits:
        names = "、".join([c.name for c in later_circuits[:3]])
        if len(later_circuits) > 3:
            names += f"等{len(later_circuits)}条"
        risks.append({
            "severity": "low",
            "category": "circuit",
            "title": f"{len(later_circuits)}条专线合同将在60天内到期",
            "description": f"{names} 合同将在60天内到期",
            "count": len(later_circuits),
            "resource_ids": [],
            "action_url": "/circuits?filter=contract_expiring"
        })
    
    # 统计各级别风险数量
    high_count = len([r for r in risks if r['severity'] == 'high'])
    medium_count = len([r for r in risks if r['severity'] == 'medium'])
    low_count = len([r for r in risks if r['severity'] == 'low'])
    
    return {
        "risks": risks,
        "high_count": high_count,
        "medium_count": medium_count,
        "low_count": low_count
    }
