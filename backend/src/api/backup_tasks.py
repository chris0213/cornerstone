from fastapi import APIRouter, Depends, HTTPException, status, Body, BackgroundTasks, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, delete, update, desc, func
from datetime import datetime, timezone, timedelta
import json

BJT = timezone(timedelta(hours=8))  # 北京时间

from ..database import get_db
from ..models import BackupTask, Backup, Credential, Device, Site
from ..tasks.backup_scheduler import add_task_to_scheduler, remove_task_from_scheduler, \
    run_backup_task, reload_tasks, running_tasks, scheduler
from ..utils.logger import audit_log
from ..utils.ip_whitelist import get_client_ip_from_request
from .dependencies import get_current_active_user, require_permission

router = APIRouter()

# 获取任务列表
@router.get("/")
async def get_backup_tasks(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("backups:read"))
):
    result = await db.execute(select(BackupTask))
    tasks = result.scalars().all()

    # next_run_at：来自进程内调度器（仅单进程部署准确；多进程/重启后由 reload_tasks 重建）
    # 注：pending 状态的 job（如测试环境调度器未启动）没有 next_run_time 属性，用 getattr 防御
    next_run_map: dict[int, object] = {}
    for job in scheduler.get_jobs():
        if job.id.startswith("backup_task_"):
            next_run = getattr(job, "next_run_time", None)
            if next_run is not None:
                try:
                    next_run_map[int(job.id.replace("backup_task_", ""))] = next_run
                except ValueError:
                    pass

    # 一次查询取全部现存设备/凭证 ID，用于缺失标识（避免每行一查）
    all_device_ids_result = await db.execute(select(Device.id))
    existing_device_ids = set(all_device_ids_result.scalars().all())
    all_credential_ids_result = await db.execute(select(Credential.id, Credential.protocol))
    credential_protocol_map = {row[0]: row[1] for row in all_credential_ids_result.all()}

    # 添加关联信息
    tasks_list = []
    for task in tasks:
        task_dict = {c.name: getattr(task, c.name) for c in task.__table__.columns}
        
        # 将 UTC 时间转换为北京时间后返回
        if task_dict.get('last_run_at') is not None:
            dt = task_dict['last_run_at']
            if dt is not None:
                if dt.tzinfo is not None:
                    dt = dt.astimezone(BJT)
                task_dict['last_run_at'] = dt.strftime("%Y-%m-%d %H:%M:%S")
        if task_dict.get('created_at') is not None:
            dt = task_dict['created_at']
            if dt is not None:
                if dt.tzinfo is not None:
                    dt = dt.astimezone(BJT)
                task_dict['created_at'] = dt.strftime("%Y-%m-%d %H:%M:%S")
        
        # 获取凭证名称/协议/缺失标识
        if task.credential_id:
            cred_result = await db.execute(select(Credential).where(Credential.id == task.credential_id))
            cred = cred_result.scalar_one_or_none()
            task_dict["credential_name"] = cred.name if cred else ""
            task_dict["credential_protocol"] = cred.protocol if cred else None
            task_dict["credential_missing"] = cred is None
        else:
            task_dict["credential_name"] = ""
            task_dict["credential_protocol"] = None
            task_dict["credential_missing"] = True

        # 获取站点名称
        if task.site_id:
            site_result = await db.execute(select(Site).where(Site.id == task.site_id))
            site = site_result.scalar_one_or_none()
            task_dict["site_name"] = site.name if site else ""

        # 解析范围与设备计数
        if task.device_ids:
            try:
                device_id_list = json.loads(task.device_ids)
            except Exception:
                device_id_list = []
            task_dict["scope_type"] = "devices"
            task_dict["device_count"] = len(device_id_list)
            task_dict["device_missing_ids"] = [d for d in device_id_list if d not in existing_device_ids]
        elif task.site_id:
            task_dict["scope_type"] = "site"
            dev_result = await db.execute(select(func.count(Device.id)).where(Device.site_id == task.site_id))
            task_dict["device_count"] = dev_result.scalar_one()
            task_dict["device_missing_ids"] = []
        else:
            # 存量数据兼容：未指定范围 = 全部设备（执行语义不变，前端显示「未指定范围」提示）
            task_dict["scope_type"] = "all"
            dev_result = await db.execute(select(func.count(Device.id)))
            task_dict["device_count"] = dev_result.scalar_one()
            task_dict["device_missing_ids"] = []

        # 下次执行时间（北京时间，与其他接口时间口径一致）；未启用或未注册为 null
        next_run = next_run_map.get(task.id) if task.is_enabled else None
        if next_run is not None:
            if next_run.tzinfo is not None:
                next_run = next_run.astimezone(BJT)
            task_dict["next_run_at"] = next_run.strftime("%Y-%m-%d %H:%M:%S")
        else:
            task_dict["next_run_at"] = None

        task_dict["is_running"] = bool(running_tasks.get(task.id))

        tasks_list.append(task_dict)
    
    return tasks_list

# 获取单个任务
@router.get("/{task_id}")
async def get_backup_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("backups:read"))
):
    result = await db.execute(select(BackupTask).where(BackupTask.id == task_id))
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(status_code=404, detail="Backup task not found")
    
    task_dict = {c.name: getattr(task, c.name) for c in task.__table__.columns}
    
    # 获取凭证名称
    if task.credential_id:
        cred_result = await db.execute(select(Credential).where(Credential.id == task.credential_id))
        cred = cred_result.scalar_one_or_none()
        task_dict["credential_name"] = cred.name if cred else ""
    
    return task_dict

# 创建任务
@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_backup_task(
    request: Request,
    name: str = Body(..., embed=True),
    cron_expr: str = Body(..., embed=True),
    credential_id: int = Body(..., embed=True),
    device_ids: list[int] = Body(None, embed=True),
    site_id: int = Body(None, embed=True),
    vendor: str = Body(None, embed=True),
    retention_count: int = Body(30, embed=True),
    retention_days: int = Body(90, embed=True),
    notify_on_change: bool = Body(True, embed=True),
    notify_on_fail: bool = Body(True, embed=True),
    is_enabled: bool = Body(True, embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("backups:write"))
):
    # 验证名称唯一性
    result = await db.execute(select(BackupTask).where(BackupTask.name == name))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="任务名称已存在")

    # 验证凭证存在
    result = await db.execute(select(Credential).where(Credential.id == credential_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Credential not found")

    # 验证站点存在
    if site_id:
        result = await db.execute(select(Site).where(Site.id == site_id))
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Site not found")

    # scope 必须明确指定：设备列表或站点二选一，禁止隐式「全部设备」
    if not device_ids and not site_id:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "backup_task.scope_required",
                "message": "必须指定备份设备或备份站点，不允许隐式备份全部设备",
            },
        )
    
    # 转换设备列表为JSON
    device_ids_json = json.dumps(device_ids) if device_ids else None
    
    task = BackupTask(
        name=name,
        cron_expr=cron_expr,
        credential_id=credential_id,
        device_ids=device_ids_json,
        site_id=site_id,
        vendor=vendor,
        retention_count=retention_count,
        retention_days=retention_days,
        notify_on_change=notify_on_change,
        notify_on_fail=notify_on_fail,
        is_enabled=is_enabled,
    )
    
    db.add(task)
    await db.commit()
    await db.refresh(task)
    
    # 如果启用，添加到调度器
    if is_enabled:
        add_task_to_scheduler(task.id, cron_expr)
    
    client_ip = get_client_ip_from_request(request)
    await audit_log(db, current_user.id, "backup_task", task.id, "create", {"name": name}, client_ip)
    
    return {c.name: getattr(task, c.name) for c in task.__table__.columns}

# 更新任务
@router.put("/{task_id}")
async def update_backup_task(
    request: Request,
    task_id: int,
    name: str = Body(None, embed=True),
    cron_expr: str = Body(None, embed=True),
    credential_id: int = Body(None, embed=True),
    device_ids: list[int] = Body(None, embed=True),
    site_id: int = Body(None, embed=True),
    vendor: str = Body(None, embed=True),
    retention_count: int = Body(None, embed=True),
    retention_days: int = Body(None, embed=True),
    notify_on_change: bool = Body(None, embed=True),
    notify_on_fail: bool = Body(None, embed=True),
    is_enabled: bool = Body(None, embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("backups:write"))
):
    result = await db.execute(select(BackupTask).where(BackupTask.id == task_id))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail="Backup task not found")

    # scope 校验：以「本次请求最终生效的范围」判断（未传字段沿用库中现值）
    final_device_ids = device_ids if device_ids is not None else (
        json.loads(task.device_ids) if task.device_ids else None
    )
    final_site_id = site_id if site_id is not None else task.site_id
    if not final_device_ids and not final_site_id:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "backup_task.scope_required",
                "message": "必须指定备份设备或备份站点，不允许隐式备份全部设备",
            },
        )
    
    # 构建更新数据
    update_data = {}
    if name is not None:
        update_data["name"] = name
    if cron_expr is not None:
        update_data["cron_expr"] = cron_expr
    if credential_id is not None:
        update_data["credential_id"] = credential_id
    if device_ids is not None:
        update_data["device_ids"] = json.dumps(device_ids)
    if site_id is not None:
        update_data["site_id"] = site_id
    if vendor is not None:
        update_data["vendor"] = vendor
    if retention_count is not None:
        update_data["retention_count"] = retention_count
    if retention_days is not None:
        update_data["retention_days"] = retention_days
    if notify_on_change is not None:
        update_data["notify_on_change"] = notify_on_change
    if notify_on_fail is not None:
        update_data["notify_on_fail"] = notify_on_fail
    if is_enabled is not None:
        update_data["is_enabled"] = is_enabled
    
    if update_data:
        stmt = update(BackupTask).where(BackupTask.id == task_id).values(**update_data)
        await db.execute(stmt)
        await db.commit()
        await db.refresh(task)
        
        # 更新调度器
        if "is_enabled" in update_data or "cron_expr" in update_data:
            if task.is_enabled:
                add_task_to_scheduler(task.id, task.cron_expr)
            else:
                remove_task_from_scheduler(task.id)
    
    client_ip = get_client_ip_from_request(request)
    await audit_log(db, current_user.id, "backup_task", task_id, "update", {"name": name}, client_ip)
    
    return {c.name: getattr(task, c.name) for c in task.__table__.columns}

# 删除任务
@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_backup_task(
    request: Request,
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("backups:delete"))
):
    result = await db.execute(select(BackupTask).where(BackupTask.id == task_id))
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(status_code=404, detail="Backup task not found")
    
    # 从调度器移除
    remove_task_from_scheduler(task_id)
    
    await db.execute(delete(BackupTask).where(BackupTask.id == task_id))
    await db.commit()
    
    client_ip = get_client_ip_from_request(request)
    await audit_log(db, current_user.id, "backup_task", task_id, "delete", {}, client_ip)

# 启用/停用任务
@router.patch("/{task_id}/toggle")
async def toggle_backup_task(
    request: Request,
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("backups:write"))
):
    result = await db.execute(select(BackupTask).where(BackupTask.id == task_id))
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(status_code=404, detail="Backup task not found")
    
    task.is_enabled = not task.is_enabled
    await db.commit()
    
    # 更新调度器
    if task.is_enabled:
        add_task_to_scheduler(task.id, task.cron_expr)
    else:
        remove_task_from_scheduler(task.id)
    
    client_ip = get_client_ip_from_request(request)
    await audit_log(db, current_user.id, "backup_task", task_id, "toggle", {"is_enabled": task.is_enabled}, client_ip)
    
    return {"is_enabled": task.is_enabled}

# 立即执行任务
@router.post("/{task_id}/run-now")
async def run_backup_task_now(
    request: Request,
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("backups:backup_exec"))
):
    result = await db.execute(select(BackupTask).where(BackupTask.id == task_id))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail="Backup task not found")

    # 防重复执行：与定时触发共用 running_tasks 状态（run_backup_task 内部置位/复位）
    if running_tasks.get(task_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "backup_task.already_running",
                "message": "任务正在执行中，请稍后再试",
            },
        )

    import asyncio
    asyncio.create_task(run_backup_task(task_id, "manual"))
    
    client_ip = get_client_ip_from_request(request)
    await audit_log(db, current_user.id, "backup_task", task_id, "run_now", {}, client_ip)
    
    return {"message": "任务已启动，请在几秒后刷新历史记录查看结果"}

# 获取任务执行历史
@router.get("/{task_id}/history")
async def get_task_history(
    task_id: int,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("backups:read"))
):
    # 先获取任务信息
    result = await db.execute(select(BackupTask).where(BackupTask.id == task_id))
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(status_code=404, detail="Backup task not found")
    
    # 获取任务关联的设备列表
    device_ids = []
    if task.device_ids:
        try:
            device_ids = json.loads(task.device_ids)
        except:
            device_ids = []
    elif task.site_id:
        # 按站点查询设备
        dev_result = await db.execute(select(Device.id).where(Device.site_id == task.site_id))
        device_ids = [d for d in dev_result.scalars().all()]
    else:
        # 所有设备
        dev_result = await db.execute(select(Device.id))
        device_ids = [d for d in dev_result.scalars().all()]
    
    if not device_ids:
        return []
    
    # 查询该任务关联设备的备份记录（包括scheduled和manual）
    result = await db.execute(
        select(Backup)
        .where(
            Backup.device_id.in_(device_ids),
            Backup.trigger.in_(["scheduled", "manual"])
        )
        .order_by(desc(Backup.created_at))
        .limit(limit)
    )
    
    backups = result.scalars().all()
    
    # 按日期分组统计
    history = {}
    for backup in backups:
        # 将 UTC 时间转换为北京时间后格式化输出
        dt = backup.created_at
        if dt.tzinfo is not None:
            dt = dt.astimezone(BJT)
        date_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        if date_str not in history:
            history[date_str] = {"success": 0, "failed": 0, "total": 0, "backups": []}
        history[date_str]["total"] += 1
        if backup.status == "success":
            history[date_str]["success"] += 1
        else:
            history[date_str]["failed"] += 1
        history[date_str]["backups"].append(backup)
    
    # 转换为列表并排序
    history_list = []
    for date_str, stats in history.items():
        history_list.append({
            "time": date_str,
            "success": stats["success"],
            "failed": stats["failed"],
            "total": stats["total"],
            "backups": [
                {"id": b.id, "device_id": b.device_id, "status": b.status, "duration_ms": b.duration_ms}
                for b in stats["backups"]
            ]
        })
    
    return sorted(history_list, key=lambda x: x["time"], reverse=True)[:limit]