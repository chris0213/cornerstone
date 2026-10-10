"""运营月报 PDF - data"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
import json
from sqlalchemy import select, func, and_, or_, Date, cast
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.circuit import Circuit
from src.models.circuit_incident import CircuitIncident
from src.models.device import Device
from src.models.setting import Setting

REPORT_DIR = Path(__file__).parent.parent.parent.parent / "data" / "reports"
COMPANY_INFO_KEY = "company_info"
BRAND_SETTINGS_KEY = "brand_settings"

# 默认品牌设置
BRAND_SETTINGS_DEFAULTS = {
    "brand_name_zh": "基石",
    "brand_name_en": "Cornerstone",
    "brand_slogan": "智能运维，尽在掌控",
    "brand_subtitle": "企业级IT基础设施智能运维平台",
    "brand_logo_url": "",
}

@dataclass
class MonthlyReportData:
    year: int
    month: int
    company_name: str = ""
    company_short_name: str = ""
    it_department: str = "信息技术部"
    it_contact: str = ""
    it_contact_email: str = ""
    generated_at: datetime = field(default_factory=datetime.now)

    # 本月概况
    availability_pct: Optional[float] = None
    circuit_cost_total: int = 0
    incident_count: int = 0
    max_duration_hours: float = 0
    circuit_count: int = 0

    # 下月行动项
    urgent_items: list = field(default_factory=list)
    warning_items: list = field(default_factory=list)

    # 故障明细
    incidents: list = field(default_factory=list)
    avg_recovery_hours: float = 0

    # 费用分析
    cost_by_type: list = field(default_factory=list)  # [{"type": "互联网专线", "cost": 22000, "pct": 51.4}]
    cost_history: list = field(default_factory=list)   # [{"month": "2026-01", "cost": 40000}, ...]

    # 品牌信息（来自配置）
    brand_name_zh: str = BRAND_SETTINGS_DEFAULTS["brand_name_zh"]
    brand_name_en: str = BRAND_SETTINGS_DEFAULTS["brand_name_en"]
    brand_slogan: str = BRAND_SETTINGS_DEFAULTS["brand_slogan"]
    brand_subtitle: str = BRAND_SETTINGS_DEFAULTS["brand_subtitle"]


async def get_company_info(db: AsyncSession) -> dict:
    """从数据库获取公司信息"""
    result = await db.execute(select(Setting).filter(Setting.key == COMPANY_INFO_KEY))
    setting = result.scalars().first()
    if setting:
        try:
            return json.loads(setting.value)
        except (json.JSONDecodeError, TypeError):
            pass
    return {}


async def get_brand_settings(db: AsyncSession) -> dict:
    """从数据库获取品牌设置"""
    result = await db.execute(select(Setting).filter(Setting.key == BRAND_SETTINGS_KEY))
    setting = result.scalars().first()
    if setting:
        try:
            config = json.loads(setting.value)
            # 填充默认值
            for key, default in BRAND_SETTINGS_DEFAULTS.items():
                if key not in config:
                    config[key] = default
            return config
        except (json.JSONDecodeError, TypeError):
            pass
    return BRAND_SETTINGS_DEFAULTS.copy()


async def collect_report_data(year: int, month: int, db: AsyncSession) -> MonthlyReportData:
    """从数据库收集月报所需数据"""
    # 使用 naive datetime 配合 cast(column, Date) 避免 SQLite/PostgreSQL 时区不兼容
    month_start = datetime(year, month, 1)
    next_month = datetime(
        year + (1 if month == 12 else 0), 1 if month == 12 else month + 1, 1
    )

    # 用于展示的北京时间
    beijing_tz = timezone(timedelta(hours=8))
    bj_now = datetime.now(beijing_tz)

    # 品牌&公司信息
    brand = await get_brand_settings(db)
    company = await get_company_info(db)

    # 专线统计
    cost_result = await db.execute(
        select(func.coalesce(func.sum(Circuit.monthly_cost), 0))
        .where(or_(Circuit.status == 'active', Circuit.status == '正常'))
    )
    total_cost = int(cost_result.scalar() or 0)

    circuit_count_result = await db.execute(
        select(func.count(Circuit.id))
        .where(or_(Circuit.status == 'active', Circuit.status == '正常'))
    )
    circuit_count = circuit_count_result.scalar() or 0

    # 费用按类型分组
    cost_by_type_result = await db.execute(
        select(Circuit.type, func.coalesce(func.sum(Circuit.monthly_cost), 0))
        .where(and_(
            or_(Circuit.status == 'active', Circuit.status == '正常'),
            Circuit.type != None,
            Circuit.type != ''
        ))
        .group_by(Circuit.type)
    )
    raw_cost_by_type = cost_by_type_result.all()
    cost_by_type = []
    for t, c in raw_cost_by_type:
        pct = round(c / total_cost * 100, 1) if total_cost > 0 else 0
        cost_by_type.append({"type": t, "cost": int(c), "pct": pct})

    # 近6个月费用历史（从现有专线数据推算）
    cost_history = []
    for i in range(5, -1, -1):
        ym = bj_now.replace(day=1) - timedelta(days=30 * i)
        cost_history.append({
            "month": ym.strftime("%Y-%m"),
            "cost": total_cost  # 静态取当前月费用作为近似
        })

    # 计算网络可用性：从 inspection_device_results 表统计本月在线率
    from src.models.inspection import InspectionDeviceResult
    # 使用 cast(column, Date) 确保 SQLite/PostgreSQL 时区兼容
    avail_result = await db.execute(
        select(func.count(InspectionDeviceResult.id)).where(
            and_(
                cast(InspectionDeviceResult.scanned_at, Date) >= month_start.date(),
                cast(InspectionDeviceResult.scanned_at, Date) < next_month.date()
            )
        )
    )
    total_count = avail_result.scalar() or 0

    online_result = await db.execute(
        select(func.count(InspectionDeviceResult.id)).where(
            and_(
                cast(InspectionDeviceResult.scanned_at, Date) >= month_start.date(),
                cast(InspectionDeviceResult.scanned_at, Date) < next_month.date(),
                InspectionDeviceResult.is_online.is_(True)
            )
        )
    )
    online_count = online_result.scalar() or 0

    availability_pct = (online_count / total_count * 100) if total_count > 0 else None

    # 本月故障统计
    incidents_result = await db.execute(
        select(func.count(CircuitIncident.id))
        .where(and_(
            cast(CircuitIncident.created_at, Date) >= month_start.date(),
            cast(CircuitIncident.created_at, Date) < next_month.date()
        ))
    )
    incident_count = incidents_result.scalar() or 0

    max_duration_min_result = await db.execute(
        select(func.coalesce(func.max(CircuitIncident.duration_minutes), 0))
        .where(and_(
            cast(CircuitIncident.created_at, Date) >= month_start.date(),
            cast(CircuitIncident.created_at, Date) < next_month.date()
        ))
    )
    max_duration = float(max_duration_min_result.scalar() or 0) / 60.0

    avg_recovery_min_result = await db.execute(
        select(func.coalesce(func.avg(CircuitIncident.duration_minutes), 0))
        .where(and_(
            cast(CircuitIncident.created_at, Date) >= month_start.date(),
            cast(CircuitIncident.created_at, Date) < next_month.date(),
            CircuitIncident.duration_minutes > 0
        ))
    )
    avg_recovery = float(avg_recovery_min_result.scalar() or 0) / 60.0

    # 故障明细
    incidents_list_result = await db.execute(
        select(
            CircuitIncident.title,
            CircuitIncident.severity,
            CircuitIncident.started_at,
            CircuitIncident.duration_minutes,
            CircuitIncident.status,
            CircuitIncident.id
        )
        .where(and_(
            cast(CircuitIncident.created_at, Date) >= month_start.date(),
            cast(CircuitIncident.created_at, Date) < next_month.date()
        ))
        .order_by(CircuitIncident.started_at.desc())
    )
    incidents_list = incidents_list_result.all()

    # 到期事项（使用 date 比较，避免 datetime 时区兼容问题）
    thirty_days_later = bj_now.date() + timedelta(days=30)
    sixty_days_later = bj_now.date() + timedelta(days=60)
    bj_today = bj_now.date()

    urgent_circuits_result = await db.execute(
        select(Circuit.name, Circuit.contract_end, Circuit.provider)
        .where(and_(
            Circuit.contract_end != None,
            cast(Circuit.contract_end, Date) <= thirty_days_later
        ))
    )
    urgent_items = []
    for c in urgent_circuits_result.all():
        end_date = c.contract_end.date() if hasattr(c.contract_end, 'date') else c.contract_end
        days_left = (end_date - bj_today).days if end_date else -1
        if days_left >= 0:
            urgent_items.append({
                "type": "专线合同",
                "name": c.name,
                "expire_date": end_date.strftime("%Y-%m-%d") if end_date else "",
                "days_left": days_left
            })

    urgent_warranties_result = await db.execute(
        select(Device.name, Device.warranty_end, Device.model)
        .where(and_(
            Device.warranty_end != None,
            cast(Device.warranty_end, Date) <= thirty_days_later
        ))
    )
    for d in urgent_warranties_result.all():
        end_date = d.warranty_end.date() if hasattr(d.warranty_end, 'date') else d.warranty_end
        days_left = (end_date - bj_today).days if end_date else -1
        if days_left >= 0:
            urgent_items.append({
                "type": "设备保修",
                "name": d.name,
                "expire_date": end_date.strftime("%Y-%m-%d") if end_date else "",
                "days_left": days_left
            })

    warning_items = []
    warning_circuits_result = await db.execute(
        select(Circuit.name, Circuit.contract_end, Circuit.provider)
        .where(and_(
            Circuit.contract_end != None,
            cast(Circuit.contract_end, Date) <= sixty_days_later,
            cast(Circuit.contract_end, Date) > thirty_days_later
        ))
    )
    for c in warning_circuits_result.all():
        end_date = c.contract_end.date() if hasattr(c.contract_end, 'date') else c.contract_end
        days_left = (end_date - bj_today).days if end_date else -1
        if days_left >= 0:
            warning_items.append({
                "type": "专线合同",
                "name": c.name,
                "expire_date": end_date.strftime("%Y-%m-%d") if end_date else "",
                "days_left": days_left
            })

    warning_warranties_result = await db.execute(
        select(Device.name, Device.warranty_end, Device.model)
        .where(and_(
            Device.warranty_end != None,
            cast(Device.warranty_end, Date) <= sixty_days_later,
            cast(Device.warranty_end, Date) > thirty_days_later
        ))
    )
    for d in warning_warranties_result.all():
        end_date = d.warranty_end.date() if hasattr(d.warranty_end, 'date') else d.warranty_end
        days_left = (end_date - bj_today).days if end_date else -1
        if days_left >= 0:
            warning_items.append({
                "type": "设备保修",
                "name": d.name,
                "expire_date": end_date.strftime("%Y-%m-%d") if end_date else "",
                "days_left": days_left
            })

    return MonthlyReportData(
        year=year,
        month=month,
        company_name=company.get("company_name", ""),
        company_short_name=company.get("company_short_name", ""),
        it_department=company.get("it_department_name", "信息技术部"),
        it_contact=company.get("it_contact_name", ""),
        generated_at=bj_now,
        availability_pct=availability_pct,
        circuit_cost_total=total_cost,
        incident_count=incident_count,
        max_duration_hours=max_duration,
        circuit_count=circuit_count,
        avg_recovery_hours=avg_recovery,
        urgent_items=sorted(urgent_items, key=lambda x: x["days_left"]),
        warning_items=sorted(warning_items, key=lambda x: x["days_left"]),
        cost_by_type=cost_by_type,
        cost_history=cost_history,
        incidents=[{
            "title": i.title or "-",
            "severity": i.severity or "low",
            "started_at": (i.started_at + timedelta(hours=8)).strftime("%m-%d %H:%M") if i.started_at else "-",
            "duration": f"{(i.duration_minutes or 0)/60.0:.1f}" if i.duration_minutes else "-",
            "status": "已恢复" if i.status == "resolved" else "处理中"
        } for i in incidents_list],
        brand_name_zh=brand.get("brand_name_zh", "基石"),
        brand_name_en=brand.get("brand_name_en", "Cornerstone"),
        brand_slogan=brand.get("brand_slogan", "看得见，管得住"),
        brand_subtitle=brand.get("brand_subtitle", "IT基础设施资源管理平台"),
    )
