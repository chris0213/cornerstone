from datetime import datetime
from typing import Optional
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import InspectionTask
from src.database import async_session
from src.services.inspector import InspectorService

logger = logging.getLogger("cornerstone")

scheduler = None


async def run_scheduled_inspection(task_id: int):
    """执行定时巡检任务"""
    async with async_session() as db:
        result = await db.execute(select(InspectionTask).where(InspectionTask.id == task_id))
        task = result.scalar_one_or_none()

        if not task or not task.is_enabled:
            return

        try:
            await InspectorService.run_inspection(
                task=task,
                trigger="scheduled",
                operator="system",
                db=db
            )
        except Exception as e:
            logger.error(f"定时巡检任务 {task_id} 执行失败: {e}", exc_info=True)
            # 更新任务状态为失败
            await db.execute(
                InspectionTask.__table__.update()
                .where(InspectionTask.id == task_id)
                .values({
                    "last_run_at": datetime.now(),
                    "last_run_status": "failed"
                })
            )
            await db.commit()


def init_inspection_scheduler(app_scheduler: AsyncIOScheduler):
    """初始化巡检任务调度器"""
    global scheduler
    scheduler = app_scheduler


async def reload_inspection_tasks(db: AsyncSession):
    """重新加载所有巡检任务到调度器"""
    if not scheduler:
        return

    # 移除所有现有的巡检任务
    for job in scheduler.get_jobs():
        if job.id.startswith("inspection_"):
            scheduler.remove_job(job.id)

    # 加载所有启用的巡检任务
    result = await db.execute(
        select(InspectionTask)
        .where(InspectionTask.is_enabled == True)
    )
    tasks = result.scalars().all()

    for task in tasks:
        _register_task(task)


def _register_task(task: InspectionTask) -> bool:
    """把任务注册到调度器，cron 无效时记日志跳过（不影响调用方）"""
    if not scheduler:
        return False
    try:
        trigger = CronTrigger.from_crontab(task.cron_expr)
    except Exception as e:
        logger.error(f"巡检任务 {task.id}（{task.name}）cron 表达式无效: {task.cron_expr!r}, {e}")
        return False
    scheduler.add_job(
        run_scheduled_inspection,
        trigger=trigger,
        args=[task.id],
        id=f"inspection_{task.id}",
        name=task.name,
        replace_existing=True
    )
    logger.info(f"巡检任务 {task.id}（{task.name}）已注册到调度器: {task.cron_expr}")
    return True


async def add_inspection_task(task_id: int, db: AsyncSession):
    """添加单个巡检任务到调度器"""
    if not scheduler:
        return

    result = await db.execute(select(InspectionTask).where(InspectionTask.id == task_id))
    task = result.scalar_one_or_none()

    if task and task.is_enabled:
        _register_task(task)


async def remove_inspection_task(task_id: int):
    """从调度器移除巡检任务"""
    if not scheduler:
        return
    
    job_id = f"inspection_{task_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


async def update_inspection_task(task_id: int, db: AsyncSession):
    """更新调度器中的巡检任务"""
    await remove_inspection_task(task_id)
    await add_inspection_task(task_id, db)
