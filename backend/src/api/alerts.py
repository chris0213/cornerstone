"""告警管理API"""
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, WebSocket
from pydantic import BaseModel
from sqlalchemy import select, update, delete, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.alert import AlertRule, AlertRecord, AlertNotification
from src.models.device import Device
from src.services.alert_service import alert_service
from src.api.dependencies import get_current_active_user
from src.schemas.alert import AlertRuleCreate, AlertRuleUpdate

router = APIRouter(tags=["alerts"])


@router.post("/rules")
async def create_alert_rule(
    data: AlertRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """创建告警规则"""
    # 验证设备是否存在
    if data.device_id:
        result = await db.execute(select(Device).where(Device.id == data.device_id))
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="设备不存在")
    
    rule = AlertRule(
        name=data.name,
        description=data.description,
        device_id=data.device_id,
        condition_type=data.condition_type,
        operator=data.operator,
        threshold=data.threshold,
        severity=data.severity,
        enabled=data.enabled,
        notification_channels=data.notification_channels or [],
        detection_mode=(data.detection_mode or "static"),
        baseline_window=data.baseline_window,
        baseline_sensitivity=data.baseline_sensitivity,
        mutation_threshold=data.mutation_threshold
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    
    return {"code": 0, "message": "告警规则创建成功", "data": rule}


@router.get("/rules")
async def get_alert_rules(
    device_id: Optional[int] = None,
    enabled: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """获取告警规则列表"""
    query = select(AlertRule).order_by(AlertRule.created_at.desc())
    
    if device_id:
        query = query.where(AlertRule.device_id == device_id)
    if enabled is not None:
        query = query.where(AlertRule.enabled == enabled)
    
    result = await db.execute(query)
    rules = result.scalars().all()
    
    return {"code": 0, "message": "ok", "data": rules}


@router.get("/rules/{rule_id}")
async def get_alert_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """获取单个告警规则"""
    result = await db.execute(select(AlertRule).where(AlertRule.id == rule_id))
    rule = result.scalar_one_or_none()
    
    if not rule:
        raise HTTPException(status_code=404, detail="告警规则不存在")
    
    return {"code": 0, "message": "ok", "data": rule}


@router.put("/rules/{rule_id}")
async def update_alert_rule(
    rule_id: int,
    data: AlertRuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """更新告警规则"""
    result = await db.execute(select(AlertRule).where(AlertRule.id == rule_id))
    rule = result.scalar_one_or_none()
    
    if not rule:
        raise HTTPException(status_code=404, detail="告警规则不存在")
    
    update_data = {}
    if data.name is not None:
        update_data["name"] = data.name
    if data.description is not None:
        update_data["description"] = data.description
    if data.device_id is not None:
        update_data["device_id"] = data.device_id
    if data.condition_type is not None:
        update_data["condition_type"] = data.condition_type
    if data.operator is not None:
        update_data["operator"] = data.operator
    if data.threshold is not None:
        update_data["threshold"] = data.threshold
    if data.severity is not None:
        update_data["severity"] = data.severity
    if data.enabled is not None:
        update_data["enabled"] = data.enabled
    if data.notification_channels is not None:
        update_data["notification_channels"] = data.notification_channels
    if data.detection_mode is not None:
        update_data["detection_mode"] = data.detection_mode
    if data.baseline_window is not None:
        update_data["baseline_window"] = data.baseline_window
    if data.baseline_sensitivity is not None:
        update_data["baseline_sensitivity"] = data.baseline_sensitivity
    if data.mutation_threshold is not None:
        update_data["mutation_threshold"] = data.mutation_threshold
    
    if update_data:
        stmt = update(AlertRule).where(AlertRule.id == rule_id).values(**update_data)
        await db.execute(stmt)
        await db.commit()
        await db.refresh(rule)
    
    return {"code": 0, "message": "告警规则更新成功", "data": rule}


@router.delete("/rules/{rule_id}")
async def delete_alert_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """删除告警规则"""
    result = await db.execute(select(AlertRule).where(AlertRule.id == rule_id))
    rule = result.scalar_one_or_none()
    
    if not rule:
        raise HTTPException(status_code=404, detail="告警规则不存在")
    
    await db.execute(delete(AlertRule).where(AlertRule.id == rule_id))
    await db.commit()
    
    return {"code": 0, "message": "告警规则删除成功"}


@router.get("/records")
async def get_alert_records(
    device_id: Optional[int] = None,
    severity: Optional[str] = Query(None, enum=["info", "warning", "critical"]),
    status: Optional[str] = Query(None, enum=["active", "acknowledged", "resolved"]),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """获取告警记录列表"""
    query = select(AlertRecord).order_by(AlertRecord.created_at.desc()).limit(limit)
    
    if device_id:
        query = query.where(AlertRecord.device_id == device_id)
    if severity:
        query = query.where(AlertRecord.severity == severity)
    if status:
        query = query.where(AlertRecord.status == status)
    
    result = await db.execute(query)
    records = result.scalars().all()
    
    return {"code": 0, "message": "ok", "data": records}


@router.get("/records/{record_id}")
async def get_alert_record(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """获取单个告警记录"""
    result = await db.execute(select(AlertRecord).where(AlertRecord.id == record_id))
    record = result.scalar_one_or_none()
    
    if not record:
        raise HTTPException(status_code=404, detail="告警记录不存在")
    
    return {"code": 0, "message": "ok", "data": record}


@router.get("/records/{record_id}/history")
async def get_alert_record_history(
    record_id: int,
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """告警事件回看：返回该告警对应指标的近期采样序列与基线统计

    说明：采样点仅在启用 detection_mode='anomaly'（自适应告警）后才开始积累；
    静态阈值规则不会产生采样点，返回空序列属预期表现。
    """
    result = await db.execute(select(AlertRecord).where(AlertRecord.id == record_id))
    record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(status_code=404, detail="告警记录不存在")

    metric = record.alert_type if record.alert_type in ("latency", "packet_loss") else None

    if not metric or record.device_id is None:
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "record_id": record_id,
                "metric": metric,
                "samples": [],
                "baseline": {"status": "not_applicable"},
                "hint": "仅 latency / packet_loss 类型且已关联设备的告警支持事件回看",
            },
        }

    data = await alert_service.get_metric_history(db, record.device_id, metric, limit)
    data["record_id"] = record_id
    data["alert"] = {
        "id": record.id,
        "severity": record.severity,
        "message": record.message,
        "current_value": record.current_value,
        "threshold": record.threshold,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }
    return {"code": 0, "message": "ok", "data": data}


@router.post("/records/{record_id}/acknowledge")
async def acknowledge_alert(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """确认告警"""
    await alert_service.acknowledge_alert(db, record_id, current_user.id)
    return {"code": 0, "message": "告警已确认"}


@router.post("/records/{record_id}/resolve")
async def resolve_alert(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """手动恢复告警"""
    stmt = update(AlertRecord).where(AlertRecord.id == record_id).values(
        status="resolved",
        resolved_at=datetime.now()
    )
    await db.execute(stmt)
    await db.commit()

    return {"code": 0, "message": "告警已恢复"}


class MuteRequest(BaseModel):
    """静默时长（小时）"""
    hours: int


@router.post("/rules/{rule_id}/mute")
async def mute_alert_rule(
    rule_id: int,
    body: MuteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """静默规则：到期前该规则不再产生新告警（已有告警不受影响）"""
    if not 1 <= body.hours <= 168:
        raise HTTPException(status_code=400, detail="静默时长须在 1-168 小时之间")

    result = await db.execute(select(AlertRule).where(AlertRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="告警规则不存在")

    muted_until = datetime.now() + timedelta(hours=body.hours)
    rule.muted_until = muted_until
    await db.commit()

    return {
        "code": 0,
        "message": f"规则已静默 {body.hours} 小时",
        "muted_until": muted_until.isoformat(),
    }


@router.post("/rules/{rule_id}/unmute")
async def unmute_alert_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """取消静默"""
    result = await db.execute(select(AlertRule).where(AlertRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="告警规则不存在")

    rule.muted_until = None
    await db.commit()
    return {"code": 0, "message": "已取消静默"}


@router.get("/summary")
async def get_alert_summary(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """获取告警统计概览"""
    summary = await alert_service.get_alert_summary(db)
    return {"code": 0, "message": "ok", "data": summary}


@router.post("/test-rule/{rule_id}")
async def test_alert_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """测试告警规则"""
    result = await db.execute(select(AlertRule).where(AlertRule.id == rule_id))
    rule = result.scalar_one_or_none()
    
    if not rule:
        raise HTTPException(status_code=404, detail="告警规则不存在")
    
    # 使用一些测试值来评估规则
    test_values = {
        "latency": [50.0, 150.0, 600.0],
        "packet_loss": [2.0, 10.0, 25.0],
        "status": ["normal", "warning", "critical"]
    }
    
    results = []
    for value in test_values.get(rule.condition_type, []):
        if rule.condition_type == "status":
            matches = value != "normal" if rule.operator == "ne" else value == "normal"
        else:
            if rule.operator == "gt":
                matches = value > rule.threshold
            elif rule.operator == "lt":
                matches = value < rule.threshold
            elif rule.operator == "eq":
                matches = value == rule.threshold
            elif rule.operator == "ne":
                matches = value != rule.threshold
            else:
                matches = False
        
        results.append({
            "value": value,
            "matches": matches
        })
    
    return {"code": 0, "message": "ok", "data": results}


@router.websocket("/ws")
async def websocket_alerts(websocket: WebSocket, db: AsyncSession = Depends(get_db)):
    """告警实时推送：新告警产生时即时下发给在线前端

    鉴权：query 参数 token（与 IP 扫描进度 WS 相同的 get_ws_user 校验）。
    """
    from fastapi import WebSocketDisconnect
    from src.api.dependencies import get_ws_user
    from src.services.alert_ws import alert_ws_manager

    # 先 accept 再验证身份（与 ipam /ws/scan 模式一致）
    await alert_ws_manager.connect(websocket)
    try:
        await get_ws_user(websocket, db)
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": f"认证失败: {e}"})
            await websocket.close(code=1008, reason="认证失败")
        finally:
            alert_ws_manager.disconnect(websocket)
        return

    try:
        # 保持连接：等待客户端消息/断开（服务端只下发，不处理上行）
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        alert_ws_manager.disconnect(websocket)
    except Exception:
        alert_ws_manager.disconnect(websocket)
