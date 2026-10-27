import logging
import asyncio
from datetime import datetime
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.database import async_session
from src.services.monitor_service import run_monitoring_task
from src.services.circuit_expire_service import circuit_expire_service

scheduler = None
current_interval = 5  # 默认5分钟

logger = logging.getLogger(__name__)


def get_scheduler() -> AsyncIOScheduler:
    """获取调度器实例"""
    global scheduler
    if scheduler is None:
        scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    return scheduler


async def scheduled_monitoring_task():
    """定时执行的监控任务"""
    logger.info(f"[{datetime.now()}] Running scheduled monitoring task...")
    async with async_session() as db:
        await run_monitoring_task(db)


async def scheduled_circuit_expire_task():
    """定时执行的专线到期检查任务（每天凌晨1点执行）"""
    logger.info(f"[{datetime.now()}] Running scheduled circuit expire check...")
    async with async_session() as db:
        await circuit_expire_service.check_expiring_circuits(db, days_before=30)
        await db.commit()


async def scheduled_alert_escalation_task():
    """严重告警升级提醒：critical 长时间未认领时重复通知（幂等，内部按 escalated_at 限频24h）"""
    from src.services.alert_service import AlertService
    async with async_session() as db:
        try:
            escalated = await AlertService.escalate_stale_critical_alerts(db)
            if escalated:
                logger.info(f"[{datetime.now()}] Escalated {escalated} stale critical alerts")
        except Exception as e:
            logger.warning(f"[{datetime.now()}] Alert escalation error: {e}")


async def scheduled_monthly_report_task():
    """月报定时生成与推送：每分钟检查一次配置时间（配置保存即生效）"""
    from src.services.report_schedule_service import run_scheduled_report
    async with async_session() as db:
        try:
            result = await run_scheduled_report(db)
            if result.get("action") not in ("disabled", "not_due"):
                logger.info(f"[{datetime.now()}] Monthly report schedule: {result}")
        except Exception as e:
            logger.warning(f"[{datetime.now()}] Monthly report schedule error: {e}")


def start_scheduler(interval_minutes: int = 5):
    """启动定时任务调度器"""
    global scheduler, current_interval
    
    # 如果调度器正在运行，先停止
    if scheduler and scheduler.running:
        scheduler.shutdown()
    
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    
    # 添加设备监控定时任务
    scheduler.add_job(
        scheduled_monitoring_task,
        trigger=IntervalTrigger(minutes=interval_minutes),
        id="monitoring_task",
        replace_existing=True
    )
    
    # 添加专线到期检查定时任务（每天凌晨1点执行）
    from apscheduler.triggers.cron import CronTrigger
    scheduler.add_job(
        scheduled_circuit_expire_task,
        trigger=CronTrigger(hour=1, minute=0),
        id="circuit_expire_task",
        replace_existing=True
    )

    # 月报定时生成与推送：每分钟检查配置时间（enabled/day/hour/minute 存于 settings）
    scheduler.add_job(
        scheduled_monthly_report_task,
        trigger=CronTrigger(minute="*"),
        id="monthly_report_task",
        replace_existing=True
    )

    # 严重告警升级提醒：每小时检查一次（升级限频24h由 escalated_at 保证）
    scheduler.add_job(
        scheduled_alert_escalation_task,
        trigger=CronTrigger(minute=0),
        id="alert_escalation_task",
        replace_existing=True
    )
    
    current_interval = interval_minutes
    scheduler.start()
    logger.info(f"Scheduler started with {interval_minutes} minutes interval")


def stop_scheduler():
    """停止定时任务调度器"""
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped")


def update_scheduler_interval(interval_minutes: int):
    """更新定时任务间隔"""
    global scheduler, current_interval
    
    if interval_minutes == current_interval:
        return
    
    if scheduler and scheduler.running:
        # 修改现有任务的触发器
        scheduler.reschedule_job(
            "monitoring_task",
            trigger=IntervalTrigger(minutes=interval_minutes)
        )
        current_interval = interval_minutes
        logger.info(f"Scheduler interval updated to {interval_minutes} minutes")


def get_current_interval() -> int:
    """获取当前定时任务间隔"""
    return current_interval


def is_scheduler_running() -> bool:
    """检查调度器是否正在运行"""
    return scheduler is not None and scheduler.running
