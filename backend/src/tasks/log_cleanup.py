"""
日志自动清理定时任务
每天凌晨3点执行，清理过期日志
"""
import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import async_session
from ..models.setting import Setting
from ..models.audit_log import AuditLog
from ..models.ai_chat_log import AIChatLog
from ..models.link_monitor import LinkMonitor
import json

logger = logging.getLogger(__name__)

LOG_SETTINGS_KEY = "log_settings"

# 链路监控数据保留天数：每设备每轮监控插一行，不清理会无限膨胀
LINK_MONITOR_RETENTION_DAYS = 30


async def cleanup_expired_logs():
    """
    读取 log_retention_days 和 login_log_retention_days 配置
    删除 audit_logs 表中超出保留天数的记录，并删除 30 天前的 AI 聊天日志
    log_auto_cleanup=False 时跳过执行
    执行结果写入系统日志（不写 audit_logs，避免循环）
    """
    async with async_session() as db:
        try:
            # 获取日志保留设置
            result = await db.execute(select(Setting).filter(Setting.key == LOG_SETTINGS_KEY))
            setting = result.scalars().first()
            
            log_retention_days = 90
            login_log_retention_days = 180
            log_auto_cleanup = True
            
            if setting:
                try:
                    config = json.loads(setting.value)
                    log_retention_days = config.get("log_retention_days", 90)
                    login_log_retention_days = config.get("login_log_retention_days", 180)
                    log_auto_cleanup = config.get("log_auto_cleanup", True)
                except json.JSONDecodeError:
                    pass
            
            # 如果自动清理关闭，跳过执行
            if not log_auto_cleanup:
                logger.info("日志自动清理已关闭，跳过执行")
                return
            
            logger.info(f"开始清理过期日志：审计日志保留{log_retention_days}天，登录日志保留{login_log_retention_days}天")
            
            # 计算截止日期
            audit_cutoff = datetime.now() - timedelta(days=log_retention_days)
            login_cutoff = datetime.now() - timedelta(days=login_log_retention_days)
            
            deleted_count = 0
            
            # 删除审计日志（登录日志除外）
            audit_result = await db.execute(
                delete(AuditLog).where(
                    AuditLog.created_at < audit_cutoff,
                    AuditLog.action != 'login',
                    AuditLog.action != 'logout'
                )
            )
            deleted_count += audit_result.rowcount
            logger.info(f"删除了 {audit_result.rowcount} 条过期审计日志")
            
            # 删除登录日志
            login_result = await db.execute(
                delete(AuditLog).where(
                    AuditLog.created_at < login_cutoff,
                    AuditLog.action.in_(['login', 'logout'])
                )
            )
            deleted_count += login_result.rowcount
            logger.info(f"删除了 {login_result.rowcount} 条过期登录日志")

            # 删除过期 AI 聊天日志（保留 30 天，与模型注释一致）
            ai_log_cutoff = datetime.now() - timedelta(days=30)
            ai_log_result = await db.execute(
                delete(AIChatLog).where(AIChatLog.created_at < ai_log_cutoff)
            )
            deleted_count += ai_log_result.rowcount
            logger.info(f"删除了 {ai_log_result.rowcount} 条过期 AI 聊天日志")

            # 删除过期链路监控数据（保留 30 天）：监控任务每设备每轮插一行，
            # 不清理会导致 link_monitor 表无限膨胀拖慢监控写入
            monitor_cutoff = datetime.now() - timedelta(days=LINK_MONITOR_RETENTION_DAYS)
            monitor_result = await db.execute(
                delete(LinkMonitor).where(LinkMonitor.created_at < monitor_cutoff)
            )
            deleted_count += monitor_result.rowcount
            logger.info(f"删除了 {monitor_result.rowcount} 条过期链路监控数据")

            await db.commit()
            
            logger.info(f"日志清理完成，共删除 {deleted_count} 条记录")
            
        except Exception as e:
            logger.error(f"日志清理失败: {str(e)}")
            await db.rollback()


async def schedule_log_cleanup():
    """
    定时任务调度器
    使用简单的循环实现，每天凌晨3点执行
    """
    while True:
        now = datetime.now()
        # 计算下一个凌晨3点
        next_run = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if now >= next_run:
            next_run = next_run + timedelta(days=1)
        
        wait_seconds = (next_run - now).total_seconds()
        logger.info(f"下次日志清理将在 {next_run} 执行，等待 {wait_seconds} 秒")
        
        await asyncio.sleep(wait_seconds)
        await cleanup_expired_logs()


# 启动定时任务
async def start_log_cleanup_scheduler():
    """启动日志清理定时任务"""
    logger.info("启动日志清理定时任务")
    asyncio.create_task(schedule_log_cleanup())