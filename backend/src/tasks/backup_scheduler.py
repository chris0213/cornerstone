import json
import logging
from datetime import datetime, timedelta, timezone

BJT = timezone(timedelta(hours=8))  # 北京时间
from typing import Dict, List
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("cornerstone")

# 备份保留策略：自动备份（scheduled/pre_change）保留天数，手动备份（manual）永久保留
AUTO_BACKUP_RETENTION_DAYS = 30

# 全局调度器实例
scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

# 存储运行中的任务
running_tasks: Dict[int, bool] = {}

async def cleanup_expired_backups():
    """清理过期自动备份：scheduled/pre_change 保留 AUTO_BACKUP_RETENTION_DAYS 天，manual 永久保留"""
    import os
    from sqlalchemy import select
    from ..models import Backup
    from ..database import async_session

    # SQLite 存储为无时区字符串，去掉 tzinfo 以保证比较一致
    cutoff = datetime.now(BJT).replace(tzinfo=None) - timedelta(days=AUTO_BACKUP_RETENTION_DAYS)

    async with async_session() as db:
        try:
            result = await db.execute(
                select(Backup).where(Backup.trigger != "manual", Backup.created_at < cutoff)
            )
            expired = result.scalars().all()
            if not expired:
                logger.info("备份保留策略清理：无过期自动备份")
                return

            removed_files = 0
            for backup in expired:
                if backup.file_path:
                    try:
                        os.remove(backup.file_path)
                        removed_files += 1
                    except OSError:
                        pass
                await db.delete(backup)
            await db.commit()
            logger.info(
                f"备份保留策略清理完成：删除 {len(expired)} 条超过 {AUTO_BACKUP_RETENTION_DAYS} 天的自动备份"
                f"（含文件 {removed_files} 个），手动备份不受影响"
            )
        except Exception as e:
            logger.error(f"备份保留策略清理失败: {e}")
            await db.rollback()

async def run_backup_task(task_id: int, trigger: str = "scheduled"):
    """执行一次备份任务
    
    Args:
        task_id: 任务ID
        trigger: 触发类型，scheduled(定时任务)/manual(手动触发)
    """
    logger.info(f"开始执行备份任务 {task_id}, 触发类型: {trigger}")
    
    from sqlalchemy import select
    from ..models import BackupTask, Device, Credential, Backup, IPAddress
    from ..services.backup_collector import collect_device_config, detect_config_change, \
        calculate_hash, save_config_to_file
    from ..utils.crypto import decrypt_password
    from ..database import async_session

    async def _notify_failure(db, summary: str):
        """备份失败时推送通知（渠道未配置/发送异常均不影响备份流程）"""
        from ..services.alert_service import AlertService
        await AlertService.send_backup_failure_notification(db, task_id, task.name, summary)
    
    # 防重复执行守卫（仅定时触发）：手动触发的检查+置位已在端点内同步完成，
    # 定时触发若与执行中的任务重叠则跳过本次（finally 复位由执行中的那次负责）
    if trigger == "scheduled" and running_tasks.get(task_id):
        logger.warning(f"备份任务 {task_id} 已在执行中，跳过本次定时触发")
        return

    running_tasks[task_id] = True
    
    try:
        async with async_session() as db_session:
            # 获取任务配置
            task = await db_session.get(BackupTask, task_id)
            if not task:
                logger.error(f"备份任务 {task_id} 不存在")
                return
            if not task.is_enabled:
                logger.warning(f"备份任务 {task_id} 已禁用")
                return
            
            logger.info(f"备份任务 {task_id} 配置: name={task.name}, cron_expr={task.cron_expr}, "
                       f"device_ids={task.device_ids}, site_id={task.site_id}, credential_id={task.credential_id}")
            
            # 获取凭证
            credential = await db_session.get(Credential, task.credential_id)
            if not credential:
                logger.error(f"备份任务 {task_id} 凭证不存在")
                task.last_run_at = datetime.now(BJT)
                task.last_run_status = "failed"
                await db_session.commit()
                await _notify_failure(db_session, "凭证不存在")
                return
            
            # 解密凭证密码
            credential_dict = {
                "username": credential.username,
                "password": decrypt_password(credential.password),
                "port": credential.port,
                "protocol": credential.protocol,
                "enable_password": decrypt_password(credential.enable_password),
                "auth_type": credential.auth_type,
                "private_key": decrypt_password(credential.private_key),
                "jump_host": credential.jump_host,
                "jump_port": credential.jump_port,
                "jump_username": credential.jump_username,
                "jump_password": decrypt_password(credential.jump_password),
            }
            
            # 检查凭证解密是否成功
            if not credential_dict["password"]:
                logger.warning(f"备份任务 {task_id} 凭证解密失败，密码为空")
            
            # 获取设备列表（包含管理IP）
            devices_with_ip = []
            if task.device_ids:
                device_id_list = json.loads(task.device_ids)
                for did in device_id_list:
                    device = await db_session.get(Device, did)
                    if device:
                        # 获取管理IP
                        ip_address = None
                        if device.mgmt_ip_id:
                            ip = await db_session.get(IPAddress, device.mgmt_ip_id)
                            if ip:
                                ip_address = ip.address
                        devices_with_ip.append((device, ip_address))
            elif task.site_id:
                devices = await db_session.execute(
                    Device.__table__.select().where(Device.site_id == task.site_id)
                )
                for device in devices.scalars():
                    ip_address = None
                    if device.mgmt_ip_id:
                        ip = await db_session.get(IPAddress, device.mgmt_ip_id)
                        if ip:
                            ip_address = ip.address
                    devices_with_ip.append((device, ip_address))
            else:
                devices = await db_session.execute(Device.__table__.select())
                for device in devices.scalars():
                    ip_address = None
                    if device.mgmt_ip_id:
                        ip = await db_session.get(IPAddress, device.mgmt_ip_id)
                        if ip:
                            ip_address = ip.address
                    devices_with_ip.append((device, ip_address))
            
            logger.info(f"备份任务 {task_id} 共找到 {len(devices_with_ip)} 台设备")
            
            # 如果没有设备，更新任务状态
            if not devices_with_ip:
                logger.warning(f"备份任务 {task_id} 没有找到可备份的设备")
                task.last_run_at = datetime.now(BJT)
                task.last_run_status = "failed"
                await db_session.commit()
                await _notify_failure(db_session, "没有找到可备份的设备")
                return
            
            # 并发采集（最多10台并发）
            import asyncio
            semaphore = asyncio.Semaphore(10)
            
            async def collect_with_semaphore(device_info):
                device, ip_address = device_info
                async with semaphore:
                    if not ip_address:
                        logger.warning(f"设备 {device.id} ({device.name}) 没有管理IP，跳过")
                        return device.id, None
                    
                    # 优先使用任务级别的vendor，如果任务没有设置则使用设备级别的vendor，如果都没有则使用默认值
                    device_vendor = task.vendor or device.vendor or "huawei_vrp"
                    device_dict = {
                        "id": device.id,
                        "ip_address": ip_address,
                        "vendor": device_vendor,
                    }
                    logger.debug(f"开始采集设备 {device.id} ({device.name}), IP: {ip_address}, vendor: {device_vendor}")
                    try:
                        return device.id, await collect_device_config(device_dict, credential_dict)
                    except Exception as e:
                        logger.error(f"采集设备 {device.id} ({device.name}) 时发生异常: {str(e)}")
                        from ..services.backup_collector import CollectResult
                        return device.id, CollectResult(
                            success=False,
                            error_message=f"采集异常: {str(e)}",
                            duration_ms=0
                        )
            
            tasks = [collect_with_semaphore(d) for d in devices_with_ip]
            results = await asyncio.gather(*tasks)
            
            # 处理结果并写入备份记录
            success_count = 0
            failed_count = 0
            failed_details = []
            
            for device_id, result in results:
                # 如果result为None，说明设备没有管理IP，跳过
                if result is None:
                    continue
                
                # 获取设备当前版本号
                latest_backup = await db_session.execute(
                    select(Backup)
                    .where(Backup.device_id == device_id)
                    .order_by(Backup.version.desc())
                    .limit(1)
                )
                latest_backup = latest_backup.scalar_one_or_none()
                new_version = (latest_backup.version if latest_backup else 0) + 1
                
                # 计算哈希
                content_hash = calculate_hash(result.config_content) if result.success else ""
                
                # 检测变更
                has_change = False
                change_summary = ""
                if result.success and latest_backup:
                    old_content = latest_backup.content
                    if latest_backup.file_path:
                        from ..services.backup_collector import load_config_from_file
                        old_content = load_config_from_file(latest_backup.file_path)
                    
                    if old_content:
                        change_result = detect_config_change(old_content, result.config_content)
                        has_change = change_result.has_change
                        change_summary = change_result.change_summary
            
                # 决定存储方式（>100KB存文件）
                content = result.config_content if result.success else ""
                file_path = ""
                if result.success and len(content) > 100 * 1024:
                    file_path = save_config_to_file(device_id, 0, content)
                    content = ""
                
                # 创建备份记录
                backup = Backup(
                    device_id=device_id,
                    version=new_version,
                    content=content,
                    content_hash=content_hash,
                    file_path=file_path,
                    trigger=trigger,
                    operator="system",
                    status="success" if result.success else "failed",
                    error_message=result.error_message,
                    has_change=has_change,
                    change_summary=change_summary,
                    duration_ms=result.duration_ms,
                    size=len(result.config_content) if result.success else 0,
                )
                db_session.add(backup)
                
                if result.success:
                    success_count += 1
                else:
                    failed_count += 1
                    device = next((d for d, _ in devices_with_ip if d.id == device_id), None)
                    device_name = device.name if device else f"设备{device_id}"
                    device_ip = next((ip for d, ip in devices_with_ip if d.id == device_id), None)
                    failed_details.append(
                        f"{device_name}({device_ip or '无IP'}): {result.error_message or '未知错误'}"
                    )
            
            await db_session.commit()
            
            # 更新任务状态（需要重新关联 session，因为 commit 后对象可能已脱离跟踪）
            task = await db_session.get(BackupTask, task_id)
            if task:
                task.last_run_at = datetime.now(BJT)
                if failed_count == 0:
                    task.last_run_status = "success"
                elif success_count == 0:
                    task.last_run_status = "failed"
                else:
                    task.last_run_status = "partial_fail"
                await db_session.commit()

                if failed_count > 0:
                    status_label = "部分失败" if task.last_run_status == "partial_fail" else "全部失败"
                    summary = f"{status_label}（成功 {success_count} / 失败 {failed_count}）"
                    if failed_details:
                        summary += "\n" + "\n".join(failed_details)
                    await _notify_failure(db_session, summary)
            
            logger.info(f"备份任务 {task_id} 执行完成: success={success_count}, failed={failed_count}")
    finally:
        running_tasks[task_id] = False

async def execute_retention_policy(device_id: int, retention_count: int, retention_days: int, db_session):
    """执行保留策略，删除超出限制的旧备份"""
    from ..models import Backup
    
    # 获取需要删除的备份（按版本号排序，保留最新的N个）
    backups = await db_session.execute(
        Backup.__table__.select()
        .where(Backup.device_id == device_id)
        .order_by(Backup.version.desc())
    )
    backups = [b for b in backups.scalars()]
    
    # 删除超出保留数量的备份
    if len(backups) > retention_count:
        to_delete = backups[retention_count:]
        for backup in to_delete:
            # 删除文件（如果存在）
            if backup.file_path and backup.file_path:
                import os
                try:
                    os.remove(backup.file_path)
                except:
                    pass
            await db_session.delete(backup)
    
    await db_session.commit()

def add_task_to_scheduler(task_id: int, cron_expr: str):
    """添加任务到调度器"""
    logger.info(f"添加备份任务到调度器: task_id={task_id}, cron_expr={cron_expr}")
    scheduler.add_job(
        run_backup_task,
        CronTrigger.from_crontab(cron_expr),
        args=[task_id],
        id=f"backup_task_{task_id}",
        replace_existing=True
    )
    logger.info(f"调度器当前任务: {[job.id for job in scheduler.get_jobs()]}")

def remove_task_from_scheduler(task_id: int):
    """从调度器移除任务"""
    try:
        scheduler.remove_job(f"backup_task_{task_id}")
        logger.info(f"从调度器移除任务: task_id={task_id}")
    except Exception as e:
        logger.warning(f"从调度器移除任务失败: task_id={task_id}, error={e}")

async def reload_tasks(db_session):
    """重新从DB加载所有任务"""
    from ..models import BackupTask
    from sqlalchemy import select
    
    logger.info("开始重新加载备份任务")
    
    # 移除所有现有任务
    for job in scheduler.get_jobs():
        if job.id.startswith("backup_task_"):
            scheduler.remove_job(job.id)
    
    # 加载并注册启用的任务
    result = await db_session.execute(select(BackupTask).where(BackupTask.is_enabled))
    tasks = result.scalars().all()
    logger.info(f"找到 {len(tasks)} 个启用的备份任务")
    
    for task in tasks:
        if task.cron_expr:
            add_task_to_scheduler(task.id, task.cron_expr)
    
    logger.info(f"重新加载完成，调度器当前任务: {[job.id for job in scheduler.get_jobs()]}")

def start_scheduler():
    """启动调度器"""
    logger.info("启动备份调度器")
    # 每天凌晨 3:30 清理过期自动备份（manual 永久保留）
    scheduler.add_job(
        cleanup_expired_backups,
        CronTrigger(hour=3, minute=30),
        id="backup_retention_cleanup",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"调度器状态: running={scheduler.running}, jobs={[job.id for job in scheduler.get_jobs()]}")

def stop_scheduler():
    """停止调度器"""
    logger.info("停止备份调度器")
    scheduler.shutdown()
