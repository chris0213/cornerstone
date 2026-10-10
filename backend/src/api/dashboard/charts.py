"""仪表盘 API - charts"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy import select, func, and_, or_, case
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import get_db
from src.models.circuit import Circuit
from src.models.circuit_change import CircuitChange
from src.models.device import Device
from src.models.site import Site
from src.models.circuit_incident import CircuitIncident
from src.api.auth import get_current_active_user
from src.models.user import User
from .common import require_manager_or_admin, to_naive_bjt

router = APIRouter()


@router.get("/circuit-types")
async def get_circuit_types(db: AsyncSession = Depends(get_db)):
    """获取专线类型分布统计（含带宽）"""
    
    # 获取所有专线类型的数量和总带宽
    circuits_result = await db.execute(
        select(Circuit.type, func.count(Circuit.id).label("count"), func.coalesce(func.sum(Circuit.bandwidth), 0).label("bandwidth"))
        .group_by(Circuit.type)
    )
    circuits = circuits_result.all()
    
    # 统计各类型数量和带宽
    type_stats = {}
    for circuit_type, count, bandwidth in circuits:
        if circuit_type:
            type_stats[circuit_type] = {'count': count, 'bandwidth': bandwidth}
        else:
            type_stats['未分类'] = {
                'count': type_stats.get('未分类', {}).get('count', 0) + count,
                'bandwidth': type_stats.get('未分类', {}).get('bandwidth', 0) + bandwidth
            }
    
    # 专线类型中文名映射
    type_labels = {
        '互联网专线': '互联网专线',
        'MPLS': 'MPLS',
        'SD-WAN': 'SD-WAN',
        '光纤专线': '光纤专线',
        '云专线': '云专线',
        '未分类': '未分类'
    }
    
    # 专线类型颜色映射
    type_colors = {
        '互联网专线': '#409EFF',
        'MPLS': '#67C23A',
        'SD-WAN': '#E6A23C',
        '光纤专线': '#9C27B0',
        '云专线': '#00BCD4',
        '未分类': '#909399'
    }
    
    return [
        {
            "name": type_labels.get(name, name),
            "value": stats['count'],
            "bandwidth": stats['bandwidth'],
            "type": name,
            "color": type_colors.get(name, '#909399')
        }
        for name, stats in type_stats.items()
    ]


@router.get("/device-types")
async def get_device_types(db: AsyncSession = Depends(get_db)):
    """获取设备类型分布统计"""
    
    # 按 vendor+type 分组统计（GROUP BY 下推，避免 2000+ 设备全量拉到内存）
    devices_result = await db.execute(
        select(Device.vendor, Device.type, func.count(Device.id))
        .group_by(Device.vendor, Device.type)
    )
    device_groups = devices_result.all()

    # 统计各品牌数量
    brand_counts = {}
    
    def get_brand(vendor: str, device_type: str) -> str:
        """根据vendor和type确定品牌"""
        if not vendor:
            # 如果没有vendor，尝试从type推断
            if device_type:
                normalized_type = device_type.lower()
                if 'huawei' in normalized_type or 'vrp' in normalized_type:
                    return 'huawei'
                elif 'cisco' in normalized_type:
                    return 'cisco'
                elif 'ruijie' in normalized_type or '锐捷' in device_type:
                    return 'ruijie'
                elif 'h3c' in normalized_type:
                    return 'h3c'
                elif 'juniper' in normalized_type:
                    return 'juniper'
                elif 'fortinet' in normalized_type or 'fortigate' in normalized_type:
                    return 'fortinet'
            return 'unknown'
        
        normalized_vendor = vendor.lower()
        if 'huawei' in normalized_vendor or 'vrp' in normalized_vendor:
            return 'huawei'
        elif 'cisco' in normalized_vendor:
            return 'cisco'
        elif 'ruijie' in normalized_vendor or '锐捷' in vendor:
            return 'ruijie'
        elif 'h3c' in normalized_vendor:
            return 'h3c'
        elif 'juniper' in normalized_vendor:
            return 'juniper'
        elif 'fortinet' in normalized_vendor or 'fortigate' in normalized_vendor:
            return 'fortinet'
        elif 'arista' in normalized_vendor:
            return 'arista'
        elif 'mikrotik' in normalized_vendor:
            return 'mikrotik'
        elif 'dell' in normalized_vendor or 'force10' in normalized_vendor:
            return 'dell'
        elif 'hp' in normalized_vendor:
            return 'hp'
        else:
            return 'other'
    
    for vendor, device_type, device_count in device_groups:
        brand = get_brand(vendor, device_type)
        brand_counts[brand] = brand_counts.get(brand, 0) + device_count
    
    # 品牌中文名映射
    brand_labels = {
        'huawei': '华为',
        'cisco': '思科',
        'ruijie': '锐捷',
        'h3c': 'H3C',
        'juniper': '瞻博',
        'fortinet': '飞塔',
        'arista': 'Arista',
        'mikrotik': 'MikroTik',
        'dell': '戴尔',
        'hp': '惠普',
        'other': '其他',
        'unknown': '未知'
    }
    
    return [
        {
            "name": brand_labels.get(name, name),
            "value": count,
            "type": name
        }
        for name, count in brand_counts.items()
    ]


@router.get("/circuit-cost-trend")
async def get_circuit_cost_trend(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """获取专线费用趋势（近12个月）

    每月费用 = 该月与合同期有交集的在册专线月租之和；
    若存在月租变更历史（circuit_changes.field_name='monthly_cost'），按变更时间还原到当时时点。
    全程仅 2 次查询，逐月计算在 Python 端完成。
    """
    require_manager_or_admin(current_user)

    now = datetime.now()

    def _naive(dt):
        """SQLite 存储的时区感知时间转 naive，避免与月初/月末比较时报错"""
        return dt.replace(tzinfo=None) if getattr(dt, 'tzinfo', None) else dt

    # 一次取全部在册专线（口径与"专线月租费用"卡片一致：active/正常）
    circuits = (await db.execute(
        select(
            Circuit.id, Circuit.type, Circuit.monthly_cost,
            Circuit.contract_start, Circuit.contract_end
        )
        .where(or_(Circuit.status == 'active', Circuit.status == '正常'))
    )).all()

    # 一次取全部月租变更历史，按专线分组
    changes_result = await db.execute(
        select(
            CircuitChange.circuit_id, CircuitChange.old_value,
            CircuitChange.new_value, CircuitChange.created_at
        )
        .where(CircuitChange.field_name == 'monthly_cost')
        .order_by(CircuitChange.created_at.asc())
    )
    changes_by_circuit: dict = {}
    for ch in changes_result.all():
        changes_by_circuit.setdefault(ch.circuit_id, []).append(ch)

    def cost_in_month(circuit, history, month_start, month_end) -> float:
        """专线在指定月份的生效月租：合同交集 + 变更历史还原"""
        start = _naive(circuit.contract_start) if circuit.contract_start else None
        end = _naive(circuit.contract_end) if circuit.contract_end else None
        if start and start > month_end:
            return 0.0  # 该月尚未开通
        if end and end < month_start:
            return 0.0  # 该月已过合同期

        cost = circuit.monthly_cost or 0
        if history:
            applicable = [
                h for h in history
                if h.created_at and _naive(h.created_at) <= month_end
            ]
            try:
                if applicable:
                    # 月末时点：取当时已发生的最新变更值
                    cost = float(applicable[-1].new_value) if applicable[-1].new_value is not None else 0
                else:
                    # 月末早于所有变更：用最早变更前的旧值
                    cost = float(history[0].old_value) if history[0].old_value is not None else 0
            except (TypeError, ValueError):
                cost = circuit.monthly_cost or 0  # 变更值非法时回退当前值
        return float(cost or 0)

    # 生成近12个月（年月翻页，避免按天偏移导致跳月/重复）
    base_idx = now.year * 12 + (now.month - 1)
    month_points = []
    for i in range(11, -1, -1):
        idx = base_idx - i
        month_points.append((idx // 12, idx % 12 + 1))

    type_mapping = {
        '互联网专线': '互联网专线',
        'MPLS': 'MPLS',
        'SD-WAN': 'SD-WAN',
        '光纤专线': '其他',
        '云专线': '其他',
        None: '其他',
    }

    months = []
    total_costs = []
    by_type = {"互联网专线": [], "MPLS": [], "SD-WAN": [], "其他": []}

    for year, month in month_points:
        month_start = datetime(year, month, 1)
        # 下月1日 - 1秒 作为月末
        next_idx = year * 12 + month
        month_end = datetime(next_idx // 12, next_idx % 12 + 1, 1) - timedelta(seconds=1)

        months.append(f"{year:04d}-{month:02d}")

        total = 0.0
        per_type = {k: 0.0 for k in by_type}
        for circuit in circuits:
            history = changes_by_circuit.get(circuit.id)
            value = cost_in_month(circuit, history, month_start, month_end)
            total += value
            per_type[type_mapping.get(circuit.type, '其他')] += value

        total_costs.append(int(total))
        for key in by_type:
            by_type[key].append(int(per_type[key]))

    return {
        "months": months,
        "total_costs": total_costs,
        "by_type": by_type
    }


@router.get("/device-lifecycle")
async def get_device_lifecycle_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """获取设备生命周期统计"""
    require_manager_or_admin(current_user)
    
    now = datetime.now()
    three_years_ago = now - timedelta(days=365 * 3)
    five_years_ago = now - timedelta(days=365 * 5)
    
    # 统计各年龄段设备数量（未设置采购时间单独统计，不计入任一年龄段）
    # 四段互斥，合并为一条 CASE 聚合查询
    under_3y, three_to_five, over_five, unset_count = (await db.execute(
        select(
            func.coalesce(func.sum(case((and_(
                Device.purchase_date != None,
                Device.purchase_date >= three_years_ago,
            ), 1), else_=0)), 0),
            func.coalesce(func.sum(case((and_(
                Device.purchase_date != None,
                Device.purchase_date >= five_years_ago,
                Device.purchase_date < three_years_ago,
            ), 1), else_=0)), 0),
            func.coalesce(func.sum(case((and_(
                Device.purchase_date != None,
                Device.purchase_date < five_years_ago,
            ), 1), else_=0)), 0),
            func.coalesce(func.sum(case((Device.purchase_date == None, 1), else_=0)), 0),
        )
    )).one()

    # 旧设备列表
    old_devices = []
    try:
        old_devices_result = await db.execute(
            select(
                Device.id,
                Device.name,
                Device.model,
                Device.purchase_date,
                Site.name.label('site_name')
            )
            .outerjoin(Site, Device.site_id == Site.id)
            .where(and_(
                Device.purchase_date != None,
                Device.purchase_date < three_years_ago
            ))
            .order_by(Device.purchase_date)
            .limit(10)
        )
        for row in old_devices_result.all():
            age_years = ((now - row.purchase_date).days / 365)
            old_devices.append({
                "id": row.id,
                "name": row.name,
                "model": row.model or "",
                "purchase_date": row.purchase_date.strftime("%Y-%m-%d") if row.purchase_date else "",
                "age_years": round(age_years, 1),
                "site": row.site_name or ""
            })
    except Exception:
        old_devices = []
    
    # 显示顺序：旧 → 新（5年以上 → 3-5年 → 3年以内），未设置单列在最后
    return {
        "age_distribution": [
            {"range": "5年以上", "count": over_five, "color": "#F56C6C"},
            {"range": "3-5年", "count": three_to_five, "color": "#E6A23C"},
            {"range": "3年以内", "count": under_3y, "color": "#67C23A"},
            {"range": "未设置", "count": unset_count, "color": "#909399"}
        ],
        "old_devices": old_devices
    }


@router.get("/monthly-incidents")
async def get_monthly_incidents_trend(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """获取本月故障信息"""
    require_manager_or_admin(current_user)
    
    try:
        now = datetime.now()
        month_start = datetime(now.year, now.month, 1)
        next_month = datetime(now.year + (1 if now.month == 12 else 0), 1 if now.month == 12 else now.month + 1, 1)
        
        # 本月故障总数
        total_result = await db.execute(
            select(func.count(CircuitIncident.id))
            .where(and_(
                CircuitIncident.created_at >= month_start,
                CircuitIncident.created_at < next_month
            ))
        )
        total_incidents = total_result.scalar() or 0
        
        # 上月故障总数
        last_month_start = datetime(now.year, now.month - 1 if now.month > 1 else 1, 1)
        last_month_result = await db.execute(
            select(func.count(CircuitIncident.id))
            .where(and_(
                CircuitIncident.created_at >= last_month_start,
                CircuitIncident.created_at < month_start
            ))
        )
        last_month_total = last_month_result.scalar() or 0
        
        # 平均恢复时长（duration_minutes 为分钟，换算为小时）
        avg_recovery = 0.0
        try:
            avg_recovery_result = await db.execute(
                select(func.coalesce(func.avg(CircuitIncident.duration_minutes), 0) / 60)
                .where(and_(
                    CircuitIncident.created_at >= month_start,
                    CircuitIncident.created_at < next_month,
                    CircuitIncident.duration_minutes > 0
                ))
            )
            avg_recovery = float(avg_recovery_result.scalar() or 0)
        except Exception:
            avg_recovery = 0.0
        
        # 最长中断
        max_duration = 0
        max_duration_circuit = ""
        max_duration_date = ""
        try:
            max_result = await db.execute(
                select(
                    CircuitIncident.duration_minutes,
                    Circuit.name.label('circuit_name'),
                    CircuitIncident.created_at
                )
                .outerjoin(Circuit, CircuitIncident.circuit_id == Circuit.id)
                .where(and_(
                    CircuitIncident.created_at >= month_start,
                    CircuitIncident.created_at < next_month
                ))
                .order_by(func.coalesce(CircuitIncident.duration_minutes, 0).desc())
                .limit(1)
            )
            max_row = max_result.first()
            if max_row:
                max_duration = float(max_row.duration_minutes or 0) / 60
                max_duration_circuit = max_row.circuit_name or ""
                max_duration_date = to_naive_bjt(max_row.created_at).strftime("%Y-%m-%d") if max_row.created_at else ""
        except Exception:
            pass
        
        # 故障列表
        incidents_list = []
        try:
            incidents_result = await db.execute(
                select(
                    CircuitIncident.id,
                    CircuitIncident.title,
                    Circuit.name.label('circuit_name'),
                    CircuitIncident.severity,
                    CircuitIncident.started_at,
                    CircuitIncident.duration_minutes,
                    CircuitIncident.status
                )
                .outerjoin(Circuit, CircuitIncident.circuit_id == Circuit.id)
                .where(and_(
                    CircuitIncident.created_at >= month_start,
                    CircuitIncident.created_at < next_month
                ))
                .order_by(CircuitIncident.created_at.desc())
            )
            for row in incidents_result.all():
                incidents_list.append({
                    "id": row.id,
                    "title": row.title or "",
                    "circuit_name": row.circuit_name or "",
                    "severity": row.severity or "low",
                    "started_at": to_naive_bjt(row.started_at).strftime("%Y-%m-%d %H:%M:%S") if row.started_at else "",
                    "duration_hours": float(row.duration_minutes or 0) / 60,
                    "status": row.status or "open"
                })
        except Exception:
            pass
        
        return {
            "total": total_incidents,
            "last_month_total": last_month_total,
            "avg_recovery_hours": avg_recovery,
            "max_duration": {
                "hours": max_duration,
                "circuit": max_duration_circuit,
                "date": max_duration_date
            } if max_duration > 0 else None,
            "incidents": incidents_list
        }
    except Exception:
        return {
            "total": 0,
            "last_month_total": 0,
            "avg_recovery_hours": 0,
            "max_duration": None,
            "incidents": []
        }
