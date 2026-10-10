from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, insert, update, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Circuit, CircuitIncident, CircuitIncidentLog, AuditLog
from ..schemas.circuit_incident import (
    CircuitIncidentCreate,
    CircuitIncidentUpdate,
    CircuitIncidentResolve,
    CircuitIncidentLogCreate,
    CircuitIncidentResponse,
    CircuitIncidentLogResponse,
    CircuitIncidentStats
)
from .dependencies import get_current_active_user, PageParams, pagination

router = APIRouter()


async def log_audit(db: AsyncSession, user: str, action: str, resource: str, detail: str):
    await db.execute(
        insert(AuditLog).values(
            user=user,
            action=action,
            resource=resource,
            detail=detail
        )
    )


@router.get("/circuits/{circuit_id}/incidents", response_model=list[CircuitIncidentResponse])
async def get_circuit_incidents(
    circuit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(Circuit).where(Circuit.id == circuit_id))
    circuit = result.scalar_one_or_none()
    if circuit is None:
        raise HTTPException(status_code=404, detail="Circuit not found")
    
    query = select(CircuitIncident).where(CircuitIncident.circuit_id == circuit_id).order_by(CircuitIncident.started_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/circuits/{circuit_id}/incidents", response_model=CircuitIncidentResponse, status_code=status.HTTP_201_CREATED)
async def create_circuit_incident(
    circuit_id: int,
    incident: CircuitIncidentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(Circuit).where(Circuit.id == circuit_id))
    circuit = result.scalar_one_or_none()
    if circuit is None:
        raise HTTPException(status_code=404, detail="Circuit not found")
    
    stmt = insert(CircuitIncident).values(
        **incident.model_dump(),
        circuit_id=circuit_id,
        reported_by=current_user.username
    ).returning(CircuitIncident)
    result = await db.execute(stmt)
    new_incident = result.scalar_one()
    
    await log_audit(db, current_user.username, "创建故障记录", f"circuit_incident:{new_incident.id}", f"专线 {circuit.name} 新增故障: {incident.title}")
    
    await db.commit()
    return new_incident


@router.get("/incidents/{incident_id}", response_model=CircuitIncidentResponse)
async def get_incident(
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(CircuitIncident).where(CircuitIncident.id == incident_id))
    incident = result.scalar_one_or_none()
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@router.put("/incidents/{incident_id}", response_model=CircuitIncidentResponse)
async def update_incident(
    incident_id: int,
    incident_update: CircuitIncidentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(CircuitIncident).where(CircuitIncident.id == incident_id))
    incident = result.scalar_one_or_none()
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    
    update_data = incident_update.model_dump(exclude_unset=True)
    stmt = update(CircuitIncident).where(CircuitIncident.id == incident_id).values(**update_data).returning(CircuitIncident)
    result = await db.execute(stmt)
    
    await log_audit(db, current_user.username, "更新故障记录", f"circuit_incident:{incident_id}", f"更新故障信息")
    
    await db.commit()
    return result.scalar_one()


@router.post("/incidents/{incident_id}/resolve", response_model=CircuitIncidentResponse)
async def resolve_incident(
    incident_id: int,
    resolve_data: CircuitIncidentResolve,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(CircuitIncident).where(CircuitIncident.id == incident_id))
    incident = result.scalar_one_or_none()
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    
    if incident.status == "resolved":
        raise HTTPException(status_code=400, detail="Incident is already resolved")
    
    now = datetime.now()
    duration_minutes = int((now - incident.started_at).total_seconds() / 60)
    
    update_data = resolve_data.model_dump(exclude_unset=True)
    update_data.update({
        "status": "resolved",
        "resolved_at": now,
        "duration_minutes": duration_minutes
    })
    
    stmt = update(CircuitIncident).where(CircuitIncident.id == incident_id).values(**update_data).returning(CircuitIncident)
    result = await db.execute(stmt)
    
    await log_audit(db, current_user.username, "解决故障", f"circuit_incident:{incident_id}", f"故障已解决，根因: {resolve_data.root_cause or '未填写'}")
    
    await db.commit()
    return result.scalar_one()


@router.post("/incidents/{incident_id}/logs", response_model=CircuitIncidentLogResponse, status_code=status.HTTP_201_CREATED)
async def add_incident_log(
    incident_id: int,
    log: CircuitIncidentLogCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(CircuitIncident).where(CircuitIncident.id == incident_id))
    incident = result.scalar_one_or_none()
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    
    stmt = insert(CircuitIncidentLog).values(
        incident_id=incident_id,
        content=log.content,
        operator=current_user.username
    ).returning(CircuitIncidentLog)
    result = await db.execute(stmt)
    
    await log_audit(db, current_user.username, "追加处理记录", f"circuit_incident:{incident_id}", f"新增处理记录")
    
    await db.commit()
    return result.scalar_one()


@router.get("/incidents/{incident_id}/logs", response_model=list[CircuitIncidentLogResponse])
async def get_incident_logs(
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(CircuitIncident).where(CircuitIncident.id == incident_id))
    incident = result.scalar_one_or_none()
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    
    query = select(CircuitIncidentLog).where(CircuitIncidentLog.incident_id == incident_id).order_by(CircuitIncidentLog.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/incidents/", response_model=list[CircuitIncidentResponse])
async def get_all_incidents(
    status: str = None,
    severity: str = None,
    page: PageParams = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    query = select(CircuitIncident).order_by(CircuitIncident.started_at.desc())
    
    if status:
        query = query.where(CircuitIncident.status == status)
    if severity:
        query = query.where(CircuitIncident.severity == severity)
    
    query = query.offset(page.skip).limit(page.limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/circuits/{circuit_id}/incidents/stats", response_model=CircuitIncidentStats)
async def get_circuit_incident_stats(
    circuit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(Circuit).where(Circuit.id == circuit_id))
    circuit = result.scalar_one_or_none()
    if circuit is None:
        raise HTTPException(status_code=404, detail="Circuit not found")
    
    now = datetime.now()
    this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    current_count_result = await db.execute(
        select(func.count(CircuitIncident.id)).where(
            and_(
                CircuitIncident.circuit_id == circuit_id,
                CircuitIncident.status == "open"
            )
        )
    )
    current_count = current_count_result.scalar() or 0
    
    monthly_count_result = await db.execute(
        select(func.count(CircuitIncident.id)).where(
            and_(
                CircuitIncident.circuit_id == circuit_id,
                CircuitIncident.started_at >= this_month_start
            )
        )
    )
    monthly_count = monthly_count_result.scalar() or 0
    
    avg_duration_result = await db.execute(
        select(func.avg(CircuitIncident.duration_minutes)).where(
            and_(
                CircuitIncident.circuit_id == circuit_id,
                CircuitIncident.status == "resolved",
                CircuitIncident.duration_minutes.is_not(None)
            )
        )
    )
    avg_duration_minutes = avg_duration_result.scalar() or 0
    avg_duration_hours = round(avg_duration_minutes / 60, 2)
    
    last_incident_result = await db.execute(
        select(CircuitIncident.started_at).where(CircuitIncident.circuit_id == circuit_id).order_by(CircuitIncident.started_at.desc()).limit(1)
    )
    last_incident_at = last_incident_result.scalar_one_or_none()
    
    return CircuitIncidentStats(
        current_count=current_count,
        monthly_count=monthly_count,
        avg_duration_hours=avg_duration_hours,
        last_incident_at=last_incident_at
    )