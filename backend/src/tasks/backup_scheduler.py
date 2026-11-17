import json
import logging
from datetime import timedelta
from src.utils.timeutil import utc_now

from typing import Dict, List
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..tenant.bootstrap import DEFAULT_TENANT_ID
from ..tenant.context import system_scope, tenant_scope
from ..tenant.query import get_active_tenant_ids

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

    # 全库统一 UTC：created_at 为 timestamptz（SQLite 下由 UTCDateTime 归一为 UTC 挂钟），
    # 统一用 UTC 比较，避免此前 naive 北京时间导致的提前 8 小时清理
    cutoff = utc_now() - timedelta(days=AUTO_BACKUP_RETENTION_DAYS)

    async with async_session() as db:
        try:
            # 备份记录属于租户业务数据：逐租户清理，避免把其他租户的备份文件误删
            tenant_ids = await get_active_tenant_ids(db) or [DEFAULT_TENANT_ID]
            total_removed = 0
            removed_files = 0
            for tenant_id in tenant_ids:
                with tenant_scope(tenant_id):
                    result = await db.execute(
                        select(Backup).where(Backup.trigger != "manual", Backup.created_at < cutoff)
                    )
                    expired = result.scalars().all()
                    for backup in expired:
                        if backup.file_path:
                            try:
                                os.remove(backup.file_path)
                                removed_files += 1
                            except OSError:
                                pass
                        await db.delete(backup)
                    total_removed += len(expired)
                await db.commit()

            if not total_removed:
                logger.info("备份保留策略清理：无过期自动备份")
                return

            logger.info(
                f"备份保留策略清理完成：删除 {total_removed} 条超过 {AUTO_BACKUP_RETENTION_DAYS} 天的自动备份"
                f"（含文件 {removed_files} 个），手动备份不受影响"
            )
        except Exception as e:
            logger.error(f"备份保留策略清理失败: {e}")
            await db.rollback()

async def run_backup_task(task_id: int, trigger: str = "scheduled"):
    """在任务所属租户的上下文中执行备份（定时/手动触发统一入口）。

    调度器本身是系统作用域，先解析任务归属，再切换租户上下文，
    避免备份记录、设备查询跨租户。
    """
    from sqlalchemy import select
    from ..models import BackupTask
    from ..database import async_session

    # 手动触发时端点已同步置位 running_tasks[task_id]：
    # 若租户探测或执行本身抛异常，必须复位标志，否则任务永远卡在「执行中」无法再次触发
    try:
        async with async_session() as probe:
            tenant_id = (
                await probe.execute(select(BackupTask.tenant_id).where(BackupTask.id == task_id))
            ).scalar_one_or_none()
        with tenant_scope(tenant_id or DEFAULT_TENANT_ID):
            await _run_backup_in_tenant(task_id, trigger)
    except Exception as e:
        running_tasks[task_id] = False
        logger.error(f"备份任务 {task_id} 执行异常，已复位运行标志: {e}")
        raise


async def _run_backup_in_tenant(task_id: int, trigger: str = "scheduled"):
    """执行一次备份任务（调用方需已切换到任务所属租户上下文）
    
    Args:
        task_id: 任务ID
        trigger: 触发类型，scheduled(定时任务)/manual(手动触发)
    """
    logger.info(f"开始执行备份任务 {task_id}, 触发类型: {trigger}")
    
    from sqlalchemy import select
    from ..models import BackupTask, Device, Credential, Backup, IPAddress
    from ..services.backup_collector import collect_device_config, detect_config_change, \
        calculate_hash, save_config_to_file
    from ..utils.crypto import decrypt_password_strict
    from ..database import async_session

    async def _notify_failure(db, summary: str):
        """备份失败时推送通知（渠道未配置/发送异常均不影响备份流程）

        受任务级 notify_on_fail 开关控制；task 在闭包定义时尚未加载，
        依赖 expire_on_commit=False 保证首次调用时（task 已加载）可安全读取。
        """
        from ..services.alert_service import AlertService
        if not task.notify_on_fail:
            logger.info(f"备份任务 {task_id} 已关闭失败通知（notify_on_fail=false），跳过")
            return
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
                task.last_run_at = utc_now()
                task.last_run_status = "failed"
                await db_session.commit()
                await _notify_failure(db_session, "凭证不存在")
                return
            
            # 解密凭证密码（严格模式：解密失败立即中止任务，
            # 绝不带空密码去连生产设备——空密码重试可能触发设备侧账号锁定）
            try:
                credential_dict = {
                    "username": credential.username,
                    "password": decrypt_password_strict(credential.password),
                    "port": credential.port,
                    "protocol": credential.protocol,
                    "enable_password": decrypt_password_strict(credential.enable_password),
                    "auth_type": credential.auth_type,
                    "private_key": decrypt_password_strict(credential.private_key),
                    "jump_host": credential.jump_host,
                    "jump_port": credential.jump_port,
                    "jump_username": credential.jump_username,
                    "jump_password": decrypt_password_strict(credential.jump_password),
                }
            except ValueError as e:
                logger.error(f"备份任务 {task_id} 凭证解密失败，中止执行（不使用空密码连接设备）: {e}")
                task.last_run_at = utc_now()
                task.last_run_status = "failed"
                await db_session.commit()
                await _notify_failure(db_session, "凭证解密失败（密钥可能不一致），已中止任务")
                return
            
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
                    select(Device).where(Device.site_id == task.site_id)
                )
                for device in devices.scalars():
                    ip_address = None
                    if device.mgmt_ip_id:
                        ip = await db_session.get(IPAddress, device.mgmt_ip_id)
                        if ip:
                            ip_address = ip.address
                    devices_with_ip.append((device, ip_address))
            else:
                devices = await db_session.execute(select(Device))
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
                task.last_run_at = utc_now()
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

                    # 设备级互斥：与手动/批量备份共用一把锁，避免并发 SSH
                    # 踢掉在线管理员会话；被占用时本轮跳过（不落失败记录）
                    from ..services.backup_locks import get_device_backup_lock
                    device_lock = get_device_backup_lock(device.id)
                    if device_lock.locked():
                        logger.warning(f"设备 {device.id} ({device.name}) 正在执行其他备份任务，本轮跳过")
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
                        # 采集阶段持设备锁，防止与手动/批量路径并发 SSH 同一设备；
                        # 结果落库在 gather 后的结果处理循环里再次持锁完成
                        async with device_lock:
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
            changed_devices = []  # 本次检测到配置变更的设备（用于 notify_on_change 变更通知）
            succeeded_device_ids = []  # 本次备份成功的设备（用于任务级保留策略清理）
            
            for device_id, result in results:
                # 如果result为None，说明设备没有管理IP或设备锁被占用，跳过
                if result is None:
                    continue

                # 写入阶段同样持设备锁：与手动/批量路径互斥，
                # 保证「查最新版本→+1→插入」窗口内不会有并发写产生重复 version
                from ..services.backup_locks import get_device_backup_lock
                async with get_device_backup_lock(device_id):
                    # 版本号取全量最大（含失败记录，避免版本号回退碰撞）
                    latest_any = await db_session.execute(
                        select(Backup.version)
                        .where(Backup.device_id == device_id)
                        .order_by(Backup.version.desc())
                        .limit(1)
                    )
                    latest_any_row = latest_any.first()
                    new_version = (latest_any_row[0] if latest_any_row else 0) + 1

                    # diff 基线只取最近一次成功备份：失败记录 content 为空，若被选为基线会漏报真实变更
                    latest_success = await db_session.execute(
                        select(Backup)
                        .where(Backup.device_id == device_id, Backup.status == "success")
                        .order_by(Backup.version.desc())
                        .limit(1)
                    )
                    latest_backup = latest_success.scalar_one_or_none()

                    # 计算哈希
                    content_hash = calculate_hash(result.config_content) if result.success else ""

                    # 检测变更
                    has_change = False
                    change_summary = ""
                    if result.success and latest_backup:
                        old_content = latest_backup.content
                        if latest_backup.file_path:
                            from ..services.backup_collector import load_config_from_file
                            try:
                                old_content = load_config_from_file(latest_backup.file_path)
                            except Exception:
                                # 旧备份文件缺失/损坏时退化为库内 content，本次采集结果照常入库
                                logger.warning(
                                    f"读取旧备份文件失败 device_id={device_id} file_path={latest_backup.file_path}，使用库内内容做 diff"
                                )

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
                    # 逐设备提交：锁内完成「查询→插入→提交」整段，
                    # 手动路径在锁外看到的 max(version) 一定包含本条
                    await db_session.commit()

                if result.success:
                    success_count += 1
                    succeeded_device_ids.append(device_id)
                    if has_change:
                        device = next((d for d, _ in devices_with_ip if d.id == device_id), None)
                        changed_devices.append(device.name if device else f"设备{device_id}")
                else:
                    failed_count += 1
                    device = next((d for d, _ in devices_with_ip if d.id == device_id), None)
                    device_name = device.name if device else f"设备{device_id}"
                    device_ip = next((ip for d, ip in devices_with_ip if d.id == device_id), None)
                    failed_details.append(
                        f"{device_name}({device_ip or '无IP'}): {result.error_message or '未知错误'}"
                    )
            
            # 更新任务状态（需要重新关联 session，因为 commit 后对象可能已脱离跟踪）
            task = await db_session.get(BackupTask, task_id)
            if task:
                task.last_run_at = utc_now()
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

                # 配置变更通知（受任务级 notify_on_change 开关控制）
                if changed_devices and task.notify_on_change:
                    from ..services.alert_service import AlertService
                    summary = f"检测到 {len(changed_devices)} 台设备配置变更：{('、'.join(changed_devices))}"
                    await AlertService.send_backup_change_notification(db_session, task_id, task.name, summary)

                # 任务级保留策略：按任务配置的数量/天数清理本次成功设备的旧自动备份
                if succeeded_device_ids:
                    for did in set(succeeded_device_ids):
                        await execute_retention_policy(
                            did, task.retention_count, task.retention_days, db_session
                        )
            
            logger.info(f"备份任务 {task_id} 执行完成: success={success_count}, failed={failed_count}")
    finally:
        running_tasks[task_id] = False

async def execute_retention_policy(device_id: int, retention_count: int, retention_days: int, db_session):
    """执行任务级保留策略：按数量（保留最新 N 个）和按天数双重限制清理自动备份。

    与全局清理策略语义一致：手动备份（manual）永久保留，不参与任务级清理。
    参数为 None/<=0 表示对应维度不限制（保持向后兼容）。
    """
    import os
    from sqlalchemy import select
    from ..models import Backup
    from ..utils.timeutil import ensure_utc

    # 任务级清理只针对自动备份；manual 备份由用户显式管理，永不自动删除
    result = await db_session.execute(
        select(Backup)
        .where(Backup.device_id == device_id, Backup.trigger != "manual")
        .order_by(Backup.version.desc())
    )
    backups = result.scalars().all()
    to_delete = []

    # 按数量清理：保留最新的 retention_count 个版本
    if retention_count and retention_count > 0 and len(backups) > retention_count:
        to_delete.extend(backups[retention_count:])

    # 按天数清理：删除创建时间早于 retention_days 天的备份
    if retention_days and retention_days > 0:
        cutoff = ensure_utc(utc_now()) - timedelta(days=retention_days)
        to_delete.extend(b for b in backups if b.created_at < cutoff)

    # 去重（同一备份可能同时命中两个维度）
    seen_ids = set()
    for backup in to_delete:
        if backup.id in seen_ids:
            continue
        seen_ids.add(backup.id)
        if backup.file_path:
            try:
                os.remove(backup.file_path)
            except OSError:
                pass
        await db_session.delete(backup)

    if seen_ids:
        await db_session.commit()
        logger.info(f"设备 {device_id} 任务级保留策略：清理 {len(seen_ids)} 个过期自动备份")

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
    
    # 加载并注册启用的任务（调度器为进程级共享状态：必须全量加载，
    # 且不能只摘除当前租户的 job，因此显式使用系统作用域）
    with system_scope():
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
