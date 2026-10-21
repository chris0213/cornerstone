from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import List, Optional
from datetime import datetime

from src.database import get_db
from src.services.inspector import InspectorService
from src.models import (
    InspectionTask,
    InspectionResult,
    InspectionDeviceResult,
    DeviceFingerprint
)
from src.schemas.inspection import (
    InspectionTaskCreate,
    InspectionTaskUpdate,
    InspectionTaskResponse,
    InspectionResultResponse,
    DeviceFingerprintResponse,
    AlertCountResponse
)
from src.utils.ip_whitelist import get_client_ip_from_request
from src.utils.logger import audit_log
from .dependencies import get_current_active_user, require_permission
from src.tasks.inspection_scheduler import (
    add_inspection_task,
    remove_inspection_task,
    update_inspection_task as refresh_scheduled_task,
)

router = APIRouter(prefix="/inspection", tags=["inspection"])


async def _sync_scheduler(coro) -> None:
    """同步调度器注册，失败只记日志不影响主流程（任务已落库）"""
    try:
        await coro
    except Exception as e:
        import logging
        logging.getLogger("cornerstone").error(f"巡检任务调度器同步失败: {e}", exc_info=True)


# 巡检任务管理
@router.get("/tasks", response_model=List[InspectionTaskResponse])
async def get_inspection_tasks(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_active_user)
):
    """获取任务列表"""
    result = await db.execute(select(InspectionTask).order_by(InspectionTask.created_at.desc()))
    return result.scalars().all()


@router.get("/tasks/{task_id}", response_model=InspectionTaskResponse)
async def get_inspection_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """获取单个任务"""
    result = await db.execute(select(InspectionTask).where(InspectionTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="巡检任务不存在")
    return task


@router.post("/tasks", response_model=InspectionTaskResponse)
async def create_inspection_task(
    task: InspectionTaskCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_permission("inspection:write"))
):
    """创建任务"""
    new_task = InspectionTask(**task.model_dump())
    db.add(new_task)
    await db.commit()
    await db.refresh(new_task)
    await _sync_scheduler(add_inspection_task(new_task.id, db))
    await audit_log(
        db, current_user.id, "inspection_task", new_task.id, "create",
        {"name": new_task.name, "scan_type": new_task.scan_type},
        get_client_ip_from_request(request)
    )
    return new_task


@router.put("/tasks/{task_id}", response_model=InspectionTaskResponse)
async def update_inspection_task(
    task_id: int,
    task: InspectionTaskUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_permission("inspection:write"))
):
    """编辑任务"""
    result = await db.execute(select(InspectionTask).where(InspectionTask.id == task_id))
    existing = result.scalar_one_or_none()
    if not existing:
        raise HTTPException(status_code=404, detail="巡检任务不存在")

    update_data = task.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(existing, key, value)

    await db.commit()
    await db.refresh(existing)
    await _sync_scheduler(refresh_scheduled_task(task_id, db))
    await audit_log(
        db, current_user.id, "inspection_task", task_id, "update",
        {"name": existing.name, "fields": list(update_data.keys())},
        get_client_ip_from_request(request)
    )
    return existing


@router.delete("/tasks/{task_id}")
async def delete_inspection_task(
    task_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_permission("inspection:write"))
):
    """删除任务"""
    result = await db.execute(select(InspectionTask).where(InspectionTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="巡检任务不存在")

    task_name = task.name
    await db.delete(task)
    await db.commit()
    await _sync_scheduler(remove_inspection_task(task_id))
    await audit_log(
        db, current_user.id, "inspection_task", task_id, "delete",
        {"name": task_name},
        get_client_ip_from_request(request)
    )
    return {"message": "删除成功"}


@router.patch("/tasks/{task_id}/toggle")
async def toggle_inspection_task(
    task_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_permission("inspection:write"))
):
    """启用/停用任务"""
    result = await db.execute(select(InspectionTask).where(InspectionTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="巡检任务不存在")

    task.is_enabled = not task.is_enabled
    await db.commit()
    await db.refresh(task)
    if task.is_enabled:
        await _sync_scheduler(add_inspection_task(task_id, db))
    else:
        await _sync_scheduler(remove_inspection_task(task_id))
    await audit_log(
        db, current_user.id, "inspection_task", task_id, "toggle",
        {"name": task.name, "is_enabled": task.is_enabled},
        get_client_ip_from_request(request)
    )
    return {"message": "已启用" if task.is_enabled else "已停用", "is_enabled": task.is_enabled}


# 手动触发执行
@router.post("/tasks/{task_id}/run")
async def run_inspection(
    task_id: int,
    request: Request,
    scan_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_permission("inspection:write"))
):
    """立即触发执行，返回 result_id"""
    result = await db.execute(select(InspectionTask).where(InspectionTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="巡检任务不存在")
    
    # 检查是否有正在运行的任务
    running_result = await db.execute(
        select(InspectionResult)
        .where(InspectionResult.task_id == task_id)
        .where(InspectionResult.status == "running")
    )
    if running_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该任务已有巡检正在执行")
    
    # 设置扫描类型
    original_scan_type = task.scan_type
    if scan_type:
        task.scan_type = scan_type
    
    try:
        inspection_result = await InspectorService.run_inspection(
            task=task,
            trigger="manual",
            operator=getattr(current_user, 'username', 'unknown'),
            db=db
        )
        
        # 更新任务最后执行记录
        task.last_run_at = datetime.now()
        task.last_run_status = inspection_result.status
        await db.commit()

        await audit_log(
            db, current_user.id, "inspection_task", task_id, "run",
            {"name": task.name, "scan_type": scan_type or original_scan_type,
             "result_id": inspection_result.id, "status": inspection_result.status},
            get_client_ip_from_request(request)
        )

        return {"result_id": inspection_result.id}
    finally:
        # 恢复原始扫描类型
        task.scan_type = original_scan_type


# 执行记录
@router.get("/results", response_model=List[InspectionResultResponse])
async def get_inspection_results(
    task_id: Optional[int] = None,
    scan_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """获取巡检执行历史，支持按 task_id/scan_type/status 筛选，分页"""
    query = select(InspectionResult)
    
    if task_id:
        query = query.where(InspectionResult.task_id == task_id)
    if scan_type:
        query = query.where(InspectionResult.scan_type == scan_type)
    if status:
        query = query.where(InspectionResult.status == status)
    
    query = query.order_by(InspectionResult.started_at.desc()).limit(limit)
    
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/results/{result_id}", response_model=InspectionResultResponse)
async def get_inspection_result(
    result_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """获取单次巡检详情（含统计信息）"""
    result = await db.execute(select(InspectionResult).where(InspectionResult.id == result_id))
    inspection_result = result.scalar_one_or_none()
    if not inspection_result:
        raise HTTPException(status_code=404, detail="巡检记录不存在")
    return inspection_result


@router.get("/results/{result_id}/devices")
async def get_inspection_device_results(
    result_id: int,
    is_online: Optional[bool] = None,
    is_new_device: Optional[bool] = None,
    has_fingerprint_change: Optional[bool] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """获取该次巡检中所有设备的扫描结果"""
    query = select(InspectionDeviceResult).where(InspectionDeviceResult.result_id == result_id)
    
    if is_online is not None:
        query = query.where(InspectionDeviceResult.is_online == is_online)
    if is_new_device is not None:
        query = query.where(InspectionDeviceResult.is_new_device == is_new_device)
    if has_fingerprint_change is not None:
        query = query.where(InspectionDeviceResult.has_fingerprint_change == has_fingerprint_change)
    
    query = query.limit(limit)
    
    result = await db.execute(query)
    return result.scalars().all()


# 设备指纹
@router.get("/fingerprints", response_model=List[DeviceFingerprintResponse])
async def get_device_fingerprints(
    vendor: Optional[str] = None,
    ip: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """获取设备指纹列表（最新快照），支持按 vendor/ip 搜索"""
    query = select(DeviceFingerprint)
    
    if vendor:
        query = query.where(DeviceFingerprint.vendor == vendor)
    if ip:
        query = query.where(DeviceFingerprint.ip_address.like(f"%{ip}%"))
    
    query = query.order_by(DeviceFingerprint.last_seen_online.desc())
    
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/fingerprints/{ip}")
async def get_device_fingerprint(
    ip: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """获取指定IP的指纹详情"""
    result = await db.execute(select(DeviceFingerprint).where(DeviceFingerprint.ip_address == ip))
    fingerprint = result.scalar_one_or_none()
    if not fingerprint:
        raise HTTPException(status_code=404, detail="设备指纹不存在")
    return fingerprint


# 巡检结果智能分类
@router.get("/results/{result_id}/categories")
async def get_inspection_categories(
    result_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """获取巡检结果的分类统计"""
    result = await db.execute(select(InspectionResult).where(InspectionResult.id == result_id))
    inspection_result = result.scalar_one_or_none()
    if not inspection_result:
        raise HTTPException(status_code=404, detail="巡检记录不存在")
    
    offline_result = await db.execute(
        select(InspectionDeviceResult)
        .where(InspectionDeviceResult.result_id == result_id)
        .where(InspectionDeviceResult.is_online == False)
    )
    offline_count = len(offline_result.scalars().all())
    
    new_device_result = await db.execute(
        select(InspectionDeviceResult)
        .where(InspectionDeviceResult.result_id == result_id)
        .where(InspectionDeviceResult.is_new_device == True)
    )
    new_device_count = len(new_device_result.scalars().all())
    
    change_result = await db.execute(
        select(InspectionDeviceResult)
        .where(InspectionDeviceResult.result_id == result_id)
        .where(InspectionDeviceResult.has_fingerprint_change == True)
    )
    change_count = len(change_result.scalars().all())
    
    high_cpu_result = await db.execute(
        select(InspectionDeviceResult)
        .where(InspectionDeviceResult.result_id == result_id)
        .where(InspectionDeviceResult.is_online == True)
        .where(InspectionDeviceResult.cpu_usage > 80)
    )
    high_cpu_count = len(high_cpu_result.scalars().all())
    
    high_memory_result = await db.execute(
        select(InspectionDeviceResult)
        .where(InspectionDeviceResult.result_id == result_id)
        .where(InspectionDeviceResult.is_online == True)
        .where(InspectionDeviceResult.memory_usage > 80)
    )
    high_memory_count = len(high_memory_result.scalars().all())
    
    error_result = await db.execute(
        select(InspectionDeviceResult)
        .where(InspectionDeviceResult.result_id == result_id)
        .where(InspectionDeviceResult.error_message.is_not(None))
        .where(InspectionDeviceResult.error_message != "")
    )
    error_count = len(error_result.scalars().all())
    
    normal_count = (inspection_result.total_targets or 0) - offline_count - new_device_count - change_count - high_cpu_count - high_memory_count - error_count
    
    categories = [
        {"name": "offline", "label": "离线设备", "count": offline_count, "color": "#F56C6C", "icon": "offline"},
        {"name": "new_device", "label": "新发现设备", "count": new_device_count, "color": "#409EFF", "icon": "plus"},
        {"name": "change", "label": "配置变更", "count": change_count, "color": "#E6A23C", "icon": "refresh"},
        {"name": "high_cpu", "label": "高CPU使用率", "count": high_cpu_count, "color": "#9C27B0", "icon": "cpu"},
        {"name": "high_memory", "label": "高内存使用率", "count": high_memory_count, "color": "#67C23A", "icon": "harddisk"},
        {"name": "error", "label": "采集异常", "count": error_count, "color": "#FA541C", "icon": "alert"},
        {"name": "normal", "label": "正常设备", "count": normal_count, "color": "#67C23A", "icon": "check"},
    ]
    
    return {"categories": categories}


@router.get("/results/{result_id}/devices/category/{category}")
async def get_inspection_devices_by_category(
    result_id: int,
    category: str,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """按分类获取设备巡检结果"""
    query = select(InspectionDeviceResult).where(InspectionDeviceResult.result_id == result_id)
    
    if category == "offline":
        query = query.where(InspectionDeviceResult.is_online == False)
    elif category == "new_device":
        query = query.where(InspectionDeviceResult.is_new_device == True)
    elif category == "change":
        query = query.where(InspectionDeviceResult.has_fingerprint_change == True)
    elif category == "high_cpu":
        query = query.where(InspectionDeviceResult.is_online == True).where(InspectionDeviceResult.cpu_usage > 80)
    elif category == "high_memory":
        query = query.where(InspectionDeviceResult.is_online == True).where(InspectionDeviceResult.memory_usage > 80)
    elif category == "error":
        query = query.where(InspectionDeviceResult.error_message.is_not(None)).where(InspectionDeviceResult.error_message != "")
    elif category == "normal":
        query = query.where(InspectionDeviceResult.is_online == True)
        query = query.where(InspectionDeviceResult.is_new_device == False)
        query = query.where(InspectionDeviceResult.has_fingerprint_change == False)
        query = query.where((InspectionDeviceResult.cpu_usage <= 80) | (InspectionDeviceResult.cpu_usage.is_(None)))
        query = query.where((InspectionDeviceResult.memory_usage <= 80) | (InspectionDeviceResult.memory_usage.is_(None)))
        query = query.where((InspectionDeviceResult.error_message == "") | (InspectionDeviceResult.error_message.is_(None)))
    else:
        raise HTTPException(status_code=400, detail="无效的分类类型")
    
    query = query.limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


# 告警统计
@router.get("/alerts/count", response_model=AlertCountResponse)
async def get_alert_count(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """获取告警统计信息"""
    # 统计新设备数量（最近一次巡检发现的新设备）
    new_device_count = await db.execute(
        select(InspectionDeviceResult)
        .where(InspectionDeviceResult.is_new_device == True)
    )
    new_device_count = len(new_device_count.scalars().all())
    
    # 统计变更设备数量
    change_count = await db.execute(
        select(InspectionDeviceResult)
        .where(InspectionDeviceResult.has_fingerprint_change == True)
    )
    change_count = len(change_count.scalars().all())
    
    # 统计离线设备数量（基于最近一次全量扫描）
    offline_count = await db.execute(
        select(InspectionDeviceResult)
        .where(InspectionDeviceResult.is_online == False)
    )
    offline_count = len(offline_count.scalars().all())
    
    total = new_device_count + change_count + offline_count
    
    return AlertCountResponse(
        total=total,
        unresolved=total,
        new_device=new_device_count,
        missing_device=offline_count,
        changed_device=change_count
    )


# WebSocket 实时进度
@router.websocket("/ws/{result_id}")
async def inspection_ws(
    websocket: WebSocket,
    result_id: int,
    db: AsyncSession = Depends(get_db)
):
    """WebSocket 推送巡检进度"""
    await websocket.accept()
    
    # 验证用户身份
    from .dependencies import get_ws_user
    try:
        await get_ws_user(websocket, db)
    except Exception as e:
        await websocket.send_json({"type": "error", "message": f"认证失败: {e}"})
        await websocket.close(code=1008, reason="认证失败")
        return
    
    async def send_progress(data):
        try:
            import json
            await websocket.send_json(data)
        except WebSocketDisconnect:
            pass
    
    # 查询巡检记录
    result = await db.execute(select(InspectionResult).where(InspectionResult.id == result_id))
    inspection_result = result.scalar_one_or_none()
    
    if not inspection_result:
        await websocket.send_json({"type": "error", "message": "巡检记录不存在"})
        await websocket.close()
        return
    
    # 如果正在运行，重新执行（简化实现）
    if inspection_result.status == "running":
        # 获取任务
        task_result = await db.execute(select(InspectionTask).where(InspectionTask.id == inspection_result.task_id))
        task = task_result.scalar_one_or_none()
        
        if task:
            await InspectorService.run_inspection(
                task=task,
                trigger=inspection_result.trigger,
                operator=inspection_result.operator,
                db=db,
                ws_callback=send_progress
            )
    
    # 发送完成状态
    result = await db.execute(select(InspectionResult).where(InspectionResult.id == result_id))
    inspection_result = result.scalar_one_or_none()
    
    if inspection_result:
        await websocket.send_json({
            "type": "done",
            "total": inspection_result.total_targets,
            "online": inspection_result.online_count,
            "offline": inspection_result.offline_count,
            "new_devices": inspection_result.new_device_count,
            "changes": inspection_result.change_count,
            "duration_seconds": inspection_result.duration_seconds
        })
    
    await websocket.close()
