"""仪表盘 API（按业务域拆分：overview 概览 / charts 图表 / manager 管理看板 / report 月报）"""
from fastapi import APIRouter

from . import overview, charts, manager, report

router = APIRouter(tags=["dashboard"])
router.include_router(overview.router)
router.include_router(charts.router)
router.include_router(manager.router)
router.include_router(report.router)
