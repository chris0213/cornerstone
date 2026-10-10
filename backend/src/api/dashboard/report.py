"""仪表盘 API - report"""
from datetime import datetime
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from fastapi import APIRouter, Depends
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import StreamingResponse
import io
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from src.database import get_db
from src.models.circuit import Circuit
from src.models.circuit_incident import CircuitIncident
from src.api.auth import get_current_active_user
from src.models.user import User
from .common import require_manager_or_admin

router = APIRouter()


@router.get("/monthly-report")
async def download_monthly_report(
    month: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """下载运营月报（PDF）"""
    require_manager_or_admin(current_user)
    
    now = datetime.now()
    if not month:
        month = now.strftime("%Y-%m")
    year, mon = [int(x) for x in month.split("-")]
    month_start = datetime(year, mon, 1)
    next_month = datetime(year + (1 if mon == 12 else 0), 1 if mon == 12 else mon + 1, 1)
    
    # ===== 查询数据 =====
    # 专线总费用
    cost_result = await db.execute(
        select(func.coalesce(func.sum(Circuit.monthly_cost), 0))
        .where(or_(Circuit.status == 'active', Circuit.status == '正常'))
    )
    total_cost = int(cost_result.scalar() or 0)
    
    # 本月故障次数
    incidents_result = await db.execute(
        select(func.count(CircuitIncident.id))
        .where(and_(
            CircuitIncident.created_at >= month_start,
            CircuitIncident.created_at < next_month
        ))
    )
    incidents = incidents_result.scalar() or 0
    
    # 专线总数
    circuit_count_result = await db.execute(
        select(func.count(Circuit.id))
        .where(or_(Circuit.status == 'active', Circuit.status == '正常'))
    )
    circuit_count = circuit_count_result.scalar() or 0
    
    # 本月最长中断
    max_duration_result = await db.execute(
        select(func.coalesce(func.max(CircuitIncident.duration_hours), 0))
        .where(and_(
            CircuitIncident.created_at >= month_start,
            CircuitIncident.created_at < next_month
        ))
    )
    max_duration = float(max_duration_result.scalar() or 0)
    
    # 本月故障列表
    incidents_list_result = await db.execute(
        select(
            CircuitIncident.title,
            CircuitIncident.severity,
            CircuitIncident.started_at,
            CircuitIncident.duration_hours,
            CircuitIncident.status
        )
        .where(and_(
            CircuitIncident.created_at >= month_start,
            CircuitIncident.created_at < next_month
        ))
        .order_by(CircuitIncident.started_at.desc())
    )
    incidents_list = incidents_list_result.all()
    
    # ===== 生成 PDF =====
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=20*mm, bottomMargin=20*mm,
        leftMargin=15*mm, rightMargin=15*mm
    )
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'ReportTitle', parent=styles['Heading1'],
        fontSize=22, leading=28, spaceAfter=6*mm,
        textColor=colors.HexColor('#1a1a2e')
    )
    subtitle_style = ParagraphStyle(
        'ReportSubtitle', parent=styles['Normal'],
        fontSize=12, leading=16, spaceAfter=10*mm,
        textColor=colors.HexColor('#666666')
    )
    section_style = ParagraphStyle(
        'SectionTitle', parent=styles['Heading2'],
        fontSize=14, leading=20, spaceBefore=6*mm, spaceAfter=4*mm,
        textColor=colors.HexColor('#1a1a2e')
    )
    normal_style = ParagraphStyle(
        'NormalCenter', parent=styles['Normal'],
        fontSize=11, leading=16, alignment=1
    )
    
    elements = []
    
    # 标题
    elements.append(Paragraph(f"{month} 运营月报", title_style))
    elements.append(Paragraph(f"生成时间：{now.strftime('%Y-%m-%d %H:%M')}", subtitle_style))
    elements.append(Spacer(1, 4*mm))
    
    # 分隔线
    line_data = [['', '']]
    line_table = Table(line_data, colWidths=[180*mm])
    line_table.setStyle(TableStyle([
        ('LINEBELOW', (0, 0), (-1, 0), 2, colors.HexColor('#409EFF')),
    ]))
    elements.append(line_table)
    elements.append(Spacer(1, 6*mm))
    
    # ===== 核心指标 =====
    elements.append(Paragraph("核心指标", section_style))
    
    metrics_data = [
        ['指标', '数值'],
        ['专线总数（条）', str(circuit_count)],
        ['月租总费用（元）', f'¥{total_cost:,}'],
        ['本月故障次数', str(incidents)],
        ['最长中断时长', f'{max_duration:.1f} 小时' if max_duration > 0 else '无'],
    ]
    metrics_table = Table(metrics_data, colWidths=[80*mm, 80*mm])
    metrics_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#409EFF')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E0E0E0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5F7FA')]),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(metrics_table)
    
    # ===== 本月故障明细 =====
    if incidents_list:
        elements.append(Spacer(1, 8*mm))
        elements.append(Paragraph("本月故障明细", section_style))
        
        detail_header = ['故障标题', '级别', '发生时间', '时长(h)', '状态']
        detail_rows = [detail_header]
        for inc in incidents_list:
            sev_label = {'high': '高危', 'medium': '中危', 'low': '低危'}.get(inc.severity or '', inc.severity or '')
            sev_color = colors.HexColor('#F56C6C') if inc.severity == 'high' else (
                colors.HexColor('#E6A23C') if inc.severity == 'medium' else colors.HexColor('#67C23A')
            )
            started = inc.started_at.strftime('%m-%d %H:%M') if inc.started_at else '-'
            status_label = '已恢复' if inc.status == 'resolved' else '处理中'
            detail_rows.append([
                Paragraph(inc.title or '-', normal_style),
                Paragraph(sev_label, normal_style),
                started,
                f'{inc.duration_hours:.1f}' if inc.duration_hours else '-',
                status_label
            ])
        
        detail_table = Table(detail_rows, colWidths=[60*mm, 20*mm, 35*mm, 20*mm, 20*mm])
        detail_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#409EFF')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E0E0E0')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5F7FA')]),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        elements.append(detail_table)
    
    # 页脚
    elements.append(Spacer(1, 15*mm))
    footer_style = ParagraphStyle(
        'Footer', parent=styles['Normal'],
        fontSize=9, textColor=colors.HexColor('#999999'),
        alignment=1
    )
    elements.append(Paragraph("本报告由基石 IT 资源管理系统自动生成", footer_style))
    
    doc.build(elements)
    pdf_content = buf.getvalue()
    buf.close()
    
    return StreamingResponse(
        io.BytesIO(pdf_content),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=report_{month}.pdf"
        }
    )
