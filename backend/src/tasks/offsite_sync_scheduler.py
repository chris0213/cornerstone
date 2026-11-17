"""异地备份同步定时任务：复用备份调度器的共享 AsyncIOScheduler。

每日按配置的 schedule_time（HH:MM，Asia/Shanghai）执行一次同步；
配置变更后由 API 调用 reload_offsite_sync_job 重新注册。
"""
import logging

from apscheduler.triggers.cron import CronTrigger

from ..tenant.context import system_scope
from .backup_scheduler import scheduler

logger = logging.getLogger("cornerstone")

JOB_ID = "offsite_sync_daily"


async def _offsite_sync_job():
    """定时任务入口：读配置→若启用则执行同步。"""
    from ..database import async_session
    from ..services.offsite_sync_store import load_stored_config
    from ..services.offsite_sync_service import run_sync

    async with async_session() as db:
        with system_scope():
            cfg = await load_stored_config(db)
        if not cfg or not cfg.get("enabled"):
            logger.info("[异地同步] 定时任务触发但未启用，跳过")
            return
        result = await run_sync(cfg)
        logger.info(f"[异地同步] 定时任务完成 ok={result.get('ok')} msg={result.get('message')}")


def _parse_time(schedule_time: str) -> tuple[int, int]:
    """解析 HH:MM，非法回落 04:00。"""
    try:
        hh, mm = (schedule_time or "04:00").split(":")
        h, m = int(hh), int(mm)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h, m
    except (ValueError, AttributeError):
        pass
    return 4, 0


def register_job(schedule_time: str) -> None:
    h, m = _parse_time(schedule_time)
    scheduler.add_job(
        _offsite_sync_job,
        CronTrigger(hour=h, minute=m),
        id=JOB_ID,
        replace_existing=True,
    )
    logger.info(f"[异地同步] 已注册定时任务 {JOB_ID} @ {h:02d}:{m:02d}")


def remove_job() -> None:
    try:
        scheduler.remove_job(JOB_ID)
        logger.info("[异地同步] 已移除定时任务")
    except Exception:
        pass


async def reload_offsite_sync_job(db) -> None:
    """按当前配置重载定时任务（启用则注册，禁用则移除）。"""
    from ..services.offsite_sync_store import load_stored_config
    with system_scope():
        cfg = await load_stored_config(db)
    if cfg and cfg.get("enabled"):
        register_job(cfg.get("schedule_time") or "04:00")
    else:
        remove_job()
