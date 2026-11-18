"""数据库 dump 备份定时任务：复用备份调度器的共享 AsyncIOScheduler。

每日按配置的 schedule_time（HH:MM，Asia/Shanghai）执行一次 pg_dump（标记 __auto），
随后按 retention_days + keep_last 清理过期 __auto 文件；手动备份（__manual/历史）不受影响。
配置变更后由 API 调用 reload_db_backup_job 重新注册。
"""
import logging

from apscheduler.triggers.cron import CronTrigger

from ..tenant.context import system_scope
from .backup_scheduler import scheduler

logger = logging.getLogger("cornerstone")

JOB_ID = "db_backup_daily"


async def _db_backup_job():
    """定时入口：读配置→若启用则 pg_dump(auto) + 清理过期 auto。"""
    from ..database import async_session
    from ..services.db_backup_store import load_stored_config, get_effective_config
    from ..services.db_backup_service import run_pg_dump, apply_retention, TRIGGER_AUTO

    async with async_session() as db:
        with system_scope():
            cfg = get_effective_config(await load_stored_config(db))
    if not cfg["enabled"]:
        logger.info("[数据库备份] 定时任务触发但未启用，跳过")
        return
    try:
        res = await run_pg_dump(TRIGGER_AUTO)
        cleanup = apply_retention(cfg["retention_days"], cfg["keep_last"])
        logger.info(
            f"[数据库备份] 定时备份完成 {res['name']}（{res['size_bytes']} 字节）；"
            f"清理过期 auto {len(cleanup['deleted'])} 个"
        )
    except Exception as e:
        # 定时任务异常只记录，不抛出（避免污染调度器）
        logger.error(f"[数据库备份] 定时备份失败: {e}")


def _parse_time(schedule_time: str) -> tuple[int, int]:
    """解析 HH:MM，非法回落 03:30。"""
    try:
        hh, mm = (schedule_time or "03:30").split(":")
        h, m = int(hh), int(mm)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h, m
    except (ValueError, AttributeError):
        pass
    return 3, 30


def register_job(schedule_time: str) -> None:
    h, m = _parse_time(schedule_time)
    scheduler.add_job(
        _db_backup_job,
        CronTrigger(hour=h, minute=m),
        id=JOB_ID,
        replace_existing=True,
    )
    logger.info(f"[数据库备份] 已注册每日备份任务 {JOB_ID} @ {h:02d}:{m:02d}")


def remove_job() -> None:
    try:
        scheduler.remove_job(JOB_ID)
        logger.info("[数据库备份] 已移除每日备份任务")
    except Exception:
        pass


async def reload_db_backup_job(db) -> None:
    """按当前配置重载定时任务（启用则注册，禁用则移除）。"""
    from ..services.db_backup_store import load_stored_config
    with system_scope():
        cfg = await load_stored_config(db)
    if cfg and cfg.get("enabled"):
        register_job(cfg.get("schedule_time") or "03:30")
    else:
        remove_job()
