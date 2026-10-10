"""运营月报 PDF 生成服务（拆分：data 数据采集 / pdf_style 样式 / pdf_build PDF 组装）"""
from .data import (
    REPORT_DIR,
    COMPANY_INFO_KEY,
    BRAND_SETTINGS_KEY,
    BRAND_SETTINGS_DEFAULTS,
    MonthlyReportData,
    get_company_info,
    get_brand_settings,
    collect_report_data,
)
from .pdf_build import generate_report_pdf, get_report_filename

__all__ = [
    "REPORT_DIR",
    "COMPANY_INFO_KEY",
    "BRAND_SETTINGS_KEY",
    "BRAND_SETTINGS_DEFAULTS",
    "MonthlyReportData",
    "get_company_info",
    "get_brand_settings",
    "collect_report_data",
    "generate_report_pdf",
    "get_report_filename",
]
