"""运营月报 PDF - pdf_style"""
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Table, TableStyle
from .data import MonthlyReportData

def _register_fonts():
    """注册中文字体。优先使用项目内开源中文字体（Noto Sans SC），如果不存在再尝试系统字体路径。"""
    import os
    # 项目内字体优先：backend/fonts/noto-sans-sc-regular.ttf（开源免费商用）
    # 放在 backend/fonts/ 而非 data/fonts/，避免 Docker 卷挂载 data/ 覆盖字体
    project_font = Path(__file__).parent.parent.parent.parent / "fonts" / "noto-sans-sc-regular.ttf"

    font_candidates = [str(project_font),
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/arphic/uming.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    ]
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    for path in font_candidates:
        try:
            if not path or not os.path.exists(path):
                continue
            pdfmetrics.registerFont(TTFont("ChineseFont", path))
            return True
        except Exception:
            continue
    return False


def _make_bar_cell(width_mm, bar_color, sty):
    """创建一个简单的色块条形图单元格"""
    data = [['']]
    t = Table(data, colWidths=[max(width_mm, 2)])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(bar_color)),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    return t


def _get_styles():
    """获取样式集合，尝试注册中文字体"""
    styles = getSampleStyleSheet()
    has_cn = _register_fonts()
    font_name = "ChineseFont" if has_cn else "Helvetica"
    font_name_bold = "ChineseFont" if has_cn else "Helvetica-Bold"

    return {
        "title": ParagraphStyle(
            'ReportTitle', fontName=font_name_bold,
            fontSize=18, leading=24, spaceAfter=8*mm,
            textColor=colors.HexColor('#1a1a2e')
        ),
        "subtitle": ParagraphStyle(
            'ReportSubtitle', fontName=font_name,
            fontSize=14, leading=20, spaceAfter=8*mm,
            textColor=colors.HexColor('#666666')
        ),
        "section": ParagraphStyle(
            'SectionTitle', fontName=font_name_bold,
            fontSize=16, leading=22, spaceBefore=6*mm, spaceAfter=4*mm,
            textColor=colors.HexColor('#1F4E79')
        ),
        "body": ParagraphStyle(
            'Body', fontName=font_name,
            fontSize=12, leading=18, spaceAfter=2*mm
        ),
        "body_center": ParagraphStyle(
            'BodyCenter', fontName=font_name,
            fontSize=12, leading=18, alignment=1
        ),
        "small": ParagraphStyle(
            'Small', fontName=font_name,
            fontSize=10, leading=14
        ),
        "footer": ParagraphStyle(
            'Footer', fontName=font_name,
            fontSize=8, textColor=colors.HexColor('#999999'), alignment=1
        ),
        "big_number": ParagraphStyle(
            'BigNumber', fontName=font_name_bold,
            fontSize=32, leading=38, alignment=1,
            textColor=colors.HexColor('#1F4E79')
        ),
        "big_number_green": ParagraphStyle(
            'BigNumberGreen', fontName=font_name_bold,
            fontSize=32, leading=38, alignment=1,
            textColor=colors.HexColor('#67C23A')
        ),
        "big_number_red": ParagraphStyle(
            'BigNumberRed', fontName=font_name_bold,
            fontSize=32, leading=38, alignment=1,
            textColor=colors.HexColor('#F56C6C')
        ),
        "kpi_label": ParagraphStyle(
            'KPILabel', fontName=font_name,
            fontSize=10, leading=14, alignment=1,
            textColor=colors.HexColor('#666666')
        ),
        "item_urgent": ParagraphStyle(
            'ItemUrgent', fontName=font_name,
            fontSize=11, leading=18, leftIndent=0,
            textColor=colors.HexColor('#F56C6C')
        ),
        "item_warning": ParagraphStyle(
            'ItemWarning', fontName=font_name,
            fontSize=11, leading=18, leftIndent=0,
            textColor=colors.HexColor('#E6A23C')
        ),
    }


def _make_header_footer(doc, sty: dict, data: MonthlyReportData):
    """添加页眉和页脚"""
    from reportlab.platypus.doctemplate import PageTemplate, BaseDocTemplate, Frame
    from reportlab.platypus import PageBreak

    company_short = data.company_short_name or data.brand_name_zh
    month_label = f"{data.year}年{data.month}月"
    # 使用注册好的中文字体（如果注册成功）
    font_name = sty['footer'].fontName

    def header_footer(canvas, doc):
        canvas.saveState()
        # 页眉
        canvas.setFont(font_name, 8)
        canvas.setFillColor(colors.HexColor('#999999'))
        canvas.drawString(25*mm, A4[1] - 15*mm, f"{data.brand_name_zh} · {data.brand_subtitle}")
        canvas.drawRightString(A4[0] - 25*mm, A4[1] - 15*mm, month_label)
        canvas.setStrokeColor(colors.HexColor('#E0E0E0'))
        canvas.setLineWidth(0.5)
        canvas.line(25*mm, A4[1] - 18*mm, A4[0] - 25*mm, A4[1] - 18*mm)
        # 页脚
        canvas.setFont(font_name, 8)
        canvas.setFillColor(colors.HexColor('#999999'))
        canvas.drawString(25*mm, 15*mm, f"{company_short} · {data.it_department}")
        canvas.drawRightString(A4[0] - 25*mm, 15*mm, f"第 {doc.page} 页")
        canvas.setStrokeColor(colors.HexColor('#E0E0E0'))
        canvas.setLineWidth(0.5)
        canvas.line(25*mm, 18*mm, A4[0] - 25*mm, 18*mm)
        canvas.restoreState()

    return header_footer
