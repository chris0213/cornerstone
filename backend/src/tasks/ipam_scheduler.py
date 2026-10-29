"""IPAM 自动扫描调度

启动时把 auto_scan_enabled=True 的 prefix 按各自 scan_cron 注册为 APScheduler job。
Prefix CRUD 时调用 reload_ipam_scan(prefix_id) 同步调度器。
"""
import asyncio
import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import async_session
from ..models import Prefix, IPAddress
from ..services.scanner import scan_prefix, parse_custom_ports

logger = logging.getLogger(__name__)

JOB_ID_PREFIX = "ipam_scan_"

scheduler: Optional[AsyncIOScheduler] = None


def init_ipam_scheduler(app_scheduler: AsyncIOScheduler):
    """注入全局调度器实例"""
    global scheduler
    scheduler = app_scheduler


async def _run_prefix_scan(prefix_id: int):
    """单个 prefix 的扫描执行体（被 APScheduler 定时调用）"""
    logger.info(f"[ipam-scan] 定时扫描 prefix_id={prefix_id} 开始")
    try:
        async with async_session() as db:
            prefix = (await db.execute(select(Prefix).where(Prefix.id == prefix_id))).scalar_one_or_none()
            if not prefix or not prefix.auto_scan_enabled:
                logger.info(f"[ipam-scan] prefix_id={prefix_id} 已禁用或不存在，跳过")
                return

            # 并发跑 scan_prefix，在线/离线都落库（离线只更新已登记记录，
            # 不离线也建记录，避免从未在线的 IP 长期停留在"未探测"）
            ports = parse_custom_ports(prefix.custom_scan_ports)
            scanned = 0
            online_count = 0
            async for item in scan_prefix(prefix.network, [], tcp_ports=ports):
                scanned += 1
                if item.get("type") == "result":
                    ip = item["ip"]
                    existing = (await db.execute(
                        select(IPAddress).where(IPAddress.prefix_id == prefix_id, IPAddress.address == ip)
                    )).scalar_one_or_none()
                    if existing:
                        existing.is_online = bool(item.get("is_online"))
                        if existing.is_online:
                            online_count += 1
                            existing.mac_address = item.get("mac_address")
                            existing.open_ports = item.get("open_ports")
                            if existing.status in ("available", "未分配"):
                                existing.status = "已分配"  # 在线即占位
                    elif item.get("is_online"):
                        online_count += 1
                        from sqlalchemy import insert
                        await db.execute(insert(IPAddress).values(
                            prefix_id=prefix_id, address=ip, status="已分配",
                            is_online=True, mac_address=item.get("mac_address"),
                            open_ports=item.get("open_ports"),
                        ))
                # 每 50 条 commit 一次，避免事务过大
                if scanned % 50 == 0:
                    await db.commit()
            await db.commit()
            logger.info(f"[ipam-scan] prefix_id={prefix_id} 完成: 共 {scanned} 条，在线 {online_count}")
    except Exception as e:
        logger.exception(f"[ipam-scan] prefix_id={prefix_id} 扫描异常: {e}")


def _register_prefix_job(prefix: Prefix) -> bool:
    """注册单个 prefix 的定时扫描 job（replace_existing=True，覆盖旧 job）"""
    if not scheduler:
        return False
    if not prefix.auto_scan_enabled:
        return False
    try:
        trigger = CronTrigger.from_crontab(prefix.scan_cron or "0 */6 * * *")
    except Exception as e:
        logger.error(f"[ipam-scan] prefix_id={prefix.id} cron 无效: {prefix.scan_cron!r}, {e}")
        return False
    scheduler.add_job(
        _run_prefix_scan,
        trigger=trigger,
        args=[prefix.id],
        id=f"{JOB_ID_PREFIX}{prefix.id}",
        name=f"IP扫描 {prefix.network}",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    logger.info(f"[ipam-scan] prefix_id={prefix.id} {prefix.network} 注册 cron={prefix.scan_cron}")
    return True


def _unregister_prefix_job(prefix_id: int):
    """注销单个 prefix 的定时扫描 job"""
    if not scheduler:
        return
    job_id = f"{JOB_ID_PREFIX}{prefix_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info(f"[ipam-scan] prefix_id={prefix_id} 已注销")


async def reload_ipam_scan(prefix_id: Optional[int] = None, db: Optional[AsyncSession] = None):
    """
    重新加载调度器里的 IPAM 扫描任务。

    Args:
        prefix_id: 只重载指定 prefix；None 则全量重载（启动时用）
        db: 可选外部 session；不传则用 async_session 自己开
    """
    if not scheduler:
        return

    async def _reload_all(cur_db: AsyncSession):
        # 先清掉所有旧 ipam_scan_* job
        for job in list(scheduler.get_jobs()):
            if job.id.startswith(JOB_ID_PREFIX):
                scheduler.remove_job(job.id)

        prefixes = (await cur_db.execute(select(Prefix).where(Prefix.auto_scan_enabled.is_(True)))).scalars().all()
        for p in prefixes:
            _register_prefix_job(p)

    async def _reload_one(cur_db: AsyncSession, pid: int):
        prefix = (await cur_db.execute(select(Prefix).where(Prefix.id == pid))).scalar_one_or_none()
        _unregister_prefix_job(pid)
        if prefix and prefix.auto_scan_enabled:
            _register_prefix_job(prefix)

    if db is not None:
        if prefix_id is None:
            await _reload_all(db)
        else:
            await _reload_one(db, prefix_id)
    else:
        async with async_session() as s:
            if prefix_id is None:
                await _reload_all(s)
            else:
                await _reload_one(s, prefix_id)
