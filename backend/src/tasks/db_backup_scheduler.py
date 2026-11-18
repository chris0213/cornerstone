"""数据库 dump 备份定时任务：复用备份调度器的共享 AsyncIOScheduler。

每日按配置的 schedule_time（HH:MM，Asia/Shanghai）执行一次 pg_dump（标记 __auto），
随后按 retention_days + keep_last 清理过期 __auto 文件；手动备份（__manual/历史）不受影响。
若 auto_verify 开启，备份成功后立即对刚产出的 dump 跑一次隔离库校验，失败/异常则告警。
配置变更后由 API 调用 reload_db_backup_job 重新注册。
"""
import logging
import time

from apscheduler.triggers.cron import CronTrigger

from ..tenant.context import system_scope
from .backup_scheduler import scheduler

logger = logging.getLogger("cornerstone")

JOB_ID = "db_backup_daily"

# 进程内最近一次自动校验结果（重启即清，足够展示用）
_last_verify: dict = {}


def get_last_verify() -> dict:
    return dict(_last_verify)


async def _send_alert(title: str, summary: str) -> None:
    """独立短会话发送告警，避免长时间持有备份/校验期间的连接。"""
    from ..database import async_session
    from ..services.alert_service import AlertService
    try:
        async with async_session() as db:
            with system_scope():
                await AlertService.send_db_backup_alert(db, title, summary)
    except Exception as e:
        logger.error(f"[数据库备份] 告警发送失败: {e}")


async def _db_backup_job():
    """定时入口：备份 → 清理 → （可选）自动校验 → 失败告警；全程结果写入 db_backup_runs 台账。"""
    global _last_verify
    from ..database import async_session
    from ..services.db_backup_store import load_stored_config, get_effective_config
    from ..services.db_backup_service import (
        run_pg_dump, apply_retention, verify_dump, _safe_resolve, record_run, TRIGGER_AUTO,
    )

    async with async_session() as db:
        with system_scope():
            cfg = get_effective_config(await load_stored_config(db))
    if not cfg["enabled"]:
        logger.info("[数据库备份] 定时任务触发但未启用，跳过")
        return

    t0 = time.monotonic()
    run = {"trigger": TRIGGER_AUTO, "operator": "system"}

    # 1) 备份 + 保留清理
    try:
        res = await run_pg_dump(TRIGGER_AUTO)
        cleanup = apply_retention(cfg["retention_days"], cfg["keep_last"])
        run.update(status="success", filename=res["name"], size_bytes=res["size_bytes"],
                   duration_ms=int((time.monotonic() - t0) * 1000),
                   retention_deleted=len(cleanup["deleted"]))
        logger.info(
            f"[数据库备份] 定时备份完成 {res['name']}（{res['size_bytes']} 字节）；"
            f"清理过期 auto {len(cleanup['deleted'])} 个"
        )
    except Exception as e:
        run.update(status="failed", error=str(e)[:500],
                   duration_ms=int((time.monotonic() - t0) * 1000), verify_status="skipped")
        async with async_session() as db:
            with system_scope():
                await record_run(db, **run)
        logger.error(f"[数据库备份] 定时备份失败: {e}")
        await _send_alert("数据库备份失败", f"定时 pg_dump 失败：{e}")
        return

    # 2) 自动校验（可选）：对刚产出的 dump 跑隔离库恢复，失败/异常告警
    if cfg.get("auto_verify"):
        try:
            path = _safe_resolve(res["name"])
            vr = await verify_dump(path)
            _last_verify = {"name": res["name"], "ok": bool(vr["ok"]),
                            "at": time.time(), "error": vr.get("error")}
            run["verify_status"] = "passed" if vr["ok"] else "failed"
            run["verify_error"] = vr.get("error")
            run["verify_checks"] = vr.get("checks")
            if not vr["ok"]:
                reason = vr.get("error") or "校验未通过（隔离库恢复或关键表行数异常）"
                logger.warning(f"[数据库备份] 自动校验未通过 {res['name']}: {reason}")
                await _send_alert("数据库备份校验未通过", f"{res['name']}：{reason}")
            else:
                logger.info(f"[数据库备份] 自动校验通过 {res['name']}")
        except Exception as e:
            _last_verify = {"name": res["name"], "ok": False, "at": time.time(), "error": str(e)}
            run["verify_status"] = "error"
            run["verify_error"] = str(e)[:500]
            logger.error(f"[数据库备份] 自动校验异常 {res['name']}: {e}")
            await _send_alert("数据库备份校验异常", f"{res['name']}：{e}")
    else:
        run["verify_status"] = "skipped"

    # 3) 写运行台账
    async with async_session() as db:
        with system_scope():
            await record_run(db, **run)


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
