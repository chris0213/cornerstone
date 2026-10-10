from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update, delete
from datetime import datetime, timezone

from ..database import get_db
from ..models import Circuit, CircuitChange
from ..schemas import CircuitCreate, CircuitUpdate, CircuitResponse
from .dependencies import get_current_active_user, PageParams, pagination

router = APIRouter()


@router.get("/", response_model=list[CircuitResponse])
async def read_circuits(
    page: PageParams = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(Circuit).offset(page.skip).limit(page.limit))
    return result.scalars().all()


@router.get("/{circuit_id}", response_model=CircuitResponse)
async def read_circuit(
    circuit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(Circuit).where(Circuit.id == circuit_id))
    circuit = result.scalar_one_or_none()
    if circuit is None:
        raise HTTPException(status_code=404, detail="Circuit not found")
    return circuit


@router.post("/", response_model=CircuitResponse, status_code=status.HTTP_201_CREATED)
async def create_circuit(
    circuit: CircuitCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    stmt = insert(Circuit).values(**circuit.model_dump()).returning(Circuit)
    result = await db.execute(stmt)
    new_circuit = result.scalar_one()
    
    await db.execute(
        insert(CircuitChange).values(
            circuit_id=new_circuit.id,
            change_type="create",
            field_name="",
            old_value="",
            new_value=str(circuit.model_dump()),
            operator=current_user.username,
            remark="创建专线"
        )
    )
    
    await db.commit()
    return new_circuit


@router.put("/{circuit_id}", response_model=CircuitResponse)
async def update_circuit(
    circuit_id: int,
    circuit: CircuitUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(Circuit).where(Circuit.id == circuit_id))
    existing_circuit = result.scalar_one_or_none()
    if existing_circuit is None:
        raise HTTPException(status_code=404, detail="Circuit not found")
    
    update_data = circuit.model_dump(exclude_unset=True)
    
    for field_name, new_value in update_data.items():
        old_value = getattr(existing_circuit, field_name, None)
        if old_value != new_value:
            await db.execute(
                insert(CircuitChange).values(
                    circuit_id=circuit_id,
                    change_type="update",
                    field_name=field_name,
                    old_value=str(old_value) if old_value is not None else "",
                    new_value=str(new_value) if new_value is not None else "",
                    operator=current_user.username,
                    remark=f"修改{field_name}"
                )
            )
    
    stmt = update(Circuit).where(Circuit.id == circuit_id).values(**update_data).returning(Circuit)
    result = await db.execute(stmt)
    await db.commit()
    return result.scalar_one()


@router.delete("/{circuit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_circuit(
    circuit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(Circuit).where(Circuit.id == circuit_id))
    circuit = result.scalar_one_or_none()
    if circuit is None:
        raise HTTPException(status_code=404, detail="Circuit not found")
    
    # 保存电路快照用于审计日志
    circuit_data = str(circuit.__dict__)
    
    # 先记录删除操作（在电路删除前）
    await db.execute(
        insert(CircuitChange).values(
            circuit_id=circuit_id,
            change_type="delete",
            field_name="",
            old_value=circuit_data,
            new_value="",
            operator=current_user.username,
            remark=f"删除专线 #{circuit_id}"
        )
    )
    
    # 删除电路，数据库会自动级联删除关联的变更记录（ondelete="CASCADE"）
    await db.execute(delete(Circuit).where(Circuit.id == circuit_id))
    await db.commit()


@router.get("/{circuit_id}/changes")
async def get_circuit_changes(
    circuit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(Circuit).where(Circuit.id == circuit_id))
    circuit = result.scalar_one_or_none()
    if circuit is None:
        raise HTTPException(status_code=404, detail="Circuit not found")
    
    query = select(CircuitChange).where(CircuitChange.circuit_id == circuit_id).order_by(CircuitChange.created_at.desc())
    result = await db.execute(query)
    changes = result.scalars().all()
    
    result_list = []
    for change in changes:
        created_at = change.created_at
        if created_at:
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            created_at_str = created_at.isoformat().replace("+00:00", "Z")
        else:
            created_at_str = None
        
        result_list.append({
            "id": change.id,
            "circuit_id": change.circuit_id,
            "change_type": change.change_type,
            "field_name": change.field_name,
            "old_value": change.old_value,
            "new_value": change.new_value,
            "operator": change.operator,
            "remark": change.remark,
            "created_at": created_at_str
        })
    
    return result_list