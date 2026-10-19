from fastapi import APIRouter, Depends, HTTPException, status, Query, Body, Request
from fastapi.websockets import WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, delete, update, desc, func
from datetime import datetime, timezone, timedelta
import ipaddress
import time

BJT = timezone(timedelta(hours=8))  # 北京时间
import json
import uuid

from ..database import get_db
from ..config import settings
from ..models import Backup, Device, Credential, IPAddress, BackupAnalysis, BackupTask
from ..schemas import BackupResponse, CredentialResponse, CredentialCreate, CredentialUpdate
from ..services.backup_collector import collect_device_config, detect_config_change, \
    calculate_hash, save_config_to_file, load_config_from_file, apply_config_to_device, \
    test_device_connection
from ..utils.crypto import encrypt_password, decrypt_password
from ..utils.logger import audit_log
from ..utils.ip_whitelist import get_client_ip_from_request
from .dependencies import get_current_active_user, require_permission, PageParams, pagination

router = APIRouter()

# 存储WebSocket连接
active_connections: dict = {}

# 凭证测试连接限流：记录每个凭证上次放行的 monotonic 时间戳
# 仅在请求通过校验、真正发起连接前更新（无论连接结果成功或失败）
_credential_test_last: dict[int, float] = {}


async def _check_credential_test_target(test_ip: str, db_conn) -> None:
    """R5：校验测试连接目标 IP。

    通过条件（满足其一）：
    - IP 已登记在设备表关联的 ip_addresses 中；
    - credential_test_allow_private=True 且目标为私网/环回/链路本地地址。

    不通过抛出 HTTPException 400（结构化错误码，与 vlan.has_prefixes 同模式）。
    """
    try:
        ip_obj = ipaddress.ip_address(test_ip)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"code": "credential.test_ip_invalid", "message": f"无效的 IP 地址: {test_ip}", "params": {}},
        )

    if settings.credential_test_allow_private and ip_obj.is_private:
        return

    result = await db_conn.execute(select(IPAddress.address).where(IPAddress.address == test_ip))
    if result.scalar_one_or_none():
        return

    raise HTTPException(
        status_code=400,
        detail={
            "code": "credential.test_ip_not_allowed",
            "message": "目标 IP 不允许测试：仅允许设备表内已登记 IP" + ("或私网段" if settings.credential_test_allow_private else ""),
            "params": {"test_ip": test_ip},
        },
    )


def _check_credential_test_rate(credential_id: int) -> None:
    """R5：同一凭证限流，间隔不足返回 400（结构化错误码）。"""
    limit_seconds = settings.credential_test_rate_limit_seconds
    if limit_seconds <= 0:
        return
    last = _credential_test_last.get(credential_id)
    if last is not None:
        elapsed = time.monotonic() - last
        if elapsed < limit_seconds:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "credential.test_rate_limited",
                    "message": f"测试过于频繁，同一凭证每 {limit_seconds} 秒仅允许测试 1 次",
                    "params": {"retry_after_seconds": int(limit_seconds - elapsed) + 1},
                },
            )


def _mark_credential_test(credential_id: int) -> None:
    """放行后立即记录时间戳（不论后续连接成功或失败）。"""
    _credential_test_last[credential_id] = time.monotonic()

# ==================== 凭证管理 ====================

# 获取凭证列表
@router.get("/credentials")
async def get_credentials(
    device_id: int = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("backups:read"))
):
    query = select(Credential)
    if device_id:
        query = query.where(Credential.device_id == device_id)
    result = await db.execute(query)
    credentials = result.scalars().all()
    
    # 隐藏密码字段
    result = []
    for cred in credentials:
        cred_dict = {c.name: getattr(cred, c.name) for c in cred.__table__.columns}
        cred_dict["password"] = "********"
        cred_dict["enable_password"] = "********" if cred_dict["enable_password"] else ""
        cred_dict["private_key"] = "********" if cred_dict["private_key"] else ""
        cred_dict["jump_password"] = "********" if cred_dict["jump_password"] else ""
        result.append(cred_dict)
    
    return result

# 获取单个凭证
@router.get("/credentials/{credential_id}")
async def get_credential(
    credential_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("backups:read"))
):
    result = await db.execute(select(Credential).where(Credential.id == credential_id))
    credential = result.scalar_one_or_none()
    
    if not credential:
        raise HTTPException(status_code=404, detail="Credential not found")
    
    # 隐藏密码字段
    cred_dict = {c.name: getattr(credential, c.name) for c in credential.__table__.columns}
    cred_dict["password"] = "********"
    cred_dict["enable_password"] = "********" if cred_dict["enable_password"] else ""
    cred_dict["private_key"] = "********" if cred_dict["private_key"] else ""
    cred_dict["jump_password"] = "********" if cred_dict["jump_password"] else ""
    
    return cred_dict

# 创建凭证
@router.post("/credentials", status_code=status.HTTP_201_CREATED)
async def create_credential(
    request: Request,
    credential: CredentialCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("backups:write"))
):
    # 验证名称唯一性
    result = await db.execute(select(Credential).where(Credential.name == credential.name))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="凭证名称已存在")
    
    # 加密密码字段
    data = credential.model_dump()
    if data.get("password"):
        data["password"] = encrypt_password(data["password"])
    if data.get("enable_password"):
        data["enable_password"] = encrypt_password(data["enable_password"])
    if data.get("private_key"):
        data["private_key"] = encrypt_password(data["private_key"])
    if data.get("jump_password"):
        data["jump_password"] = encrypt_password(data["jump_password"])
    
    stmt = insert(Credential).values(**data).returning(Credential)
    result = await db.execute(stmt)
    await db.commit()
    
    new_credential = result.scalar_one()
    
    client_ip = get_client_ip_from_request(request)
    await audit_log(db, current_user.id, "credential", new_credential.id, "create", {"name": credential.name}, client_ip)
    
    # 返回时隐藏密码
    cred_dict = {c.name: getattr(new_credential, c.name) for c in new_credential.__table__.columns}
    cred_dict["password"] = "********"
    cred_dict["enable_password"] = "********" if cred_dict["enable_password"] else ""
    cred_dict["private_key"] = "********" if cred_dict["private_key"] else ""
    cred_dict["jump_password"] = "********" if cred_dict["jump_password"] else ""
    
    return cred_dict

# 更新凭证
@router.put("/credentials/{credential_id}")
async def update_credential(
    request: Request,
    credential_id: int,
    credential: CredentialUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("backups:write"))
):
    result = await db.execute(select(Credential).where(Credential.id == credential_id))
    existing = result.scalar_one_or_none()
    
    if not existing:
        raise HTTPException(status_code=404, detail="Credential not found")
    
    data = credential.model_dump(exclude_unset=True)
    
    # 加密新密码（如果提供）
    if data.get("password"):
        data["password"] = encrypt_password(data["password"])
    if data.get("enable_password"):
        data["enable_password"] = encrypt_password(data["enable_password"])
    if data.get("private_key"):
        data["private_key"] = encrypt_password(data["private_key"])
    if data.get("jump_password"):
        data["jump_password"] = encrypt_password(data["jump_password"])
    
    stmt = update(Credential).where(Credential.id == credential_id).values(**data)
    await db.execute(stmt)
    await db.commit()
    
    await db.refresh(existing)
    
    client_ip = get_client_ip_from_request(request)
    await audit_log(db, current_user.id, "credential", credential_id, "update", {"name": credential.name}, client_ip)
    
    # 返回时隐藏密码
    cred_dict = {c.name: getattr(existing, c.name) for c in existing.__table__.columns}
    cred_dict["password"] = "********"
    cred_dict["enable_password"] = "********" if cred_dict["enable_password"] else ""
    cred_dict["private_key"] = "********" if cred_dict["private_key"] else ""
    cred_dict["jump_password"] = "********" if cred_dict["jump_password"] else ""
    
    return cred_dict

# 删除凭证
@router.delete("/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    request: Request,
    credential_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("backups:delete"))
):
    result = await db.execute(select(Credential).where(Credential.id == credential_id))
    credential = result.scalar_one_or_none()

    if not credential:
        raise HTTPException(status_code=404, detail="Credential not found")

    # R4：被备份任务引用的凭证禁止删除（结构化错误码，与 vlan.has_prefixes 同模式）
    refs = await db.execute(
        select(BackupTask.id, BackupTask.name).where(BackupTask.credential_id == credential_id)
    )
    ref_tasks = [{"id": row.id, "name": row.name} for row in refs.all()]
    if ref_tasks:
        task_names = "、".join(t["name"] for t in ref_tasks)
        raise HTTPException(
            status_code=409,
            detail={
                "code": "credential.in_use",
                "message": f"凭证已被 {len(ref_tasks)} 个备份任务使用（{task_names}），请先解绑后再删除",
                "params": {"tasks": ref_tasks},
            },
        )

    await db.execute(delete(Credential).where(Credential.id == credential_id))
    await db.commit()

    client_ip = get_client_ip_from_request(request)
    await audit_log(db, current_user.id, "credential", credential_id, "delete", {}, client_ip)

# 测试凭证连通性
@router.post("/credentials/{credential_id}/test")
async def test_credential(
    request: Request,
    credential_id: int,
    test_ip: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("backups:write"))
):
    result = await db.execute(select(Credential).where(Credential.id == credential_id))
    credential = result.scalar_one_or_none()

    if not credential:
        raise HTTPException(status_code=404, detail="Credential not found")

    # R5：限流与目标 IP 校验（拒绝时写审计 action=test_denied）
    try:
        _check_credential_test_rate(credential_id)
        await _check_credential_test_target(test_ip, db)
    except HTTPException as denied:
        await audit_log(
            db, current_user.id, "credential", credential_id, "test_denied",
            {"test_ip": test_ip, "reason": denied.detail.get("code") if isinstance(denied.detail, dict) else str(denied.detail)},
            get_client_ip_from_request(request),
        )
        raise

    # R6：按凭证关联设备的厂商构造参数；取不到时保持默认并在响应中标注
    vendor = "huawei_vrp"
    defaults_applied = ["vendor"]
    if credential.device_id:
        dev = await db.execute(select(Device).where(Device.id == credential.device_id))
        device = dev.scalar_one_or_none()
        if device and device.vendor:
            vendor = device.vendor
            defaults_applied = []

    # 放行：立即更新限流时间戳（不论连接成功或失败）
    _mark_credential_test(credential_id)

    # 解密凭证
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

    # 测试连接
    device_dict = {
        "id": 0,
        "ip_address": test_ip,
        "vendor": vendor,
    }

    result = await test_device_connection(device_dict, credential_dict)

    # R7：测试连接写审计（记录目标 IP 与结果，不记录任何凭证内容）
    await audit_log(
        db, current_user.id, "credential", credential_id, "test",
        {"test_ip": test_ip, "success": result.success, "error": result.error_message},
        get_client_ip_from_request(request),
    )

    return {
        "success": result.success,
        "message": result.error_message if not result.success else "连接成功",
        "duration_ms": result.duration_ms,
        "vendor": vendor,
        "defaults_applied": defaults_applied,
    }

# ==================== 备份管理 ====================

# 备份历史列表
@router.get("/", response_model=list[BackupResponse])
async def read_backups(
    page: PageParams = Depends(pagination()),
    device_id: int = None,
    status: str = None,
    trigger: str = None,
    has_change: bool = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    query = select(Backup, Device.name.label('device_name')).join(Device, Backup.device_id == Device.id, isouter=True)
    if device_id:
        query = query.where(Backup.device_id == device_id)
    if status:
        query = query.where(Backup.status == status)
    if trigger:
        query = query.where(Backup.trigger == trigger)
    if has_change is not None:
        query = query.where(Backup.has_change == has_change)
    query = query.order_by(desc(Backup.created_at))
    result = await db.execute(query.offset(page.skip).limit(page.limit))
    
    backups = []
    for row in result.all():
        backup = row[0]
        backup_dict = {c.name: getattr(backup, c.name) for c in backup.__table__.columns}
        backup_dict['device_name'] = row[1]
        # 将 UTC 时间转换为北京时间后返回
        if backup_dict.get('created_at'):
            dt = backup_dict['created_at']
            if dt:
                if dt.tzinfo is not None:
                    dt = dt.astimezone(BJT)
                backup_dict['created_at'] = dt.strftime("%Y-%m-%d %H:%M:%S")
        backups.append(backup_dict)
    
    return backups

# Diff对比（必须在 /{backup_id} 之前注册，否则会被吞掉）
@router.get("/diff")
async def get_backup_diff(
    backup_id_a: int = Query(...),
    backup_id_b: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result_a = await db.execute(select(Backup).where(Backup.id == backup_id_a))
    backup_a = result_a.scalar_one_or_none()
    
    result_b = await db.execute(select(Backup).where(Backup.id == backup_id_b))
    backup_b = result_b.scalar_one_or_none()
    
    if not backup_a:
        raise HTTPException(status_code=404, detail="Backup A not found")
    if not backup_b:
        raise HTTPException(status_code=404, detail="Backup B not found")
    
    # 获取配置内容
    content_a = backup_a.content
    if backup_a.file_path:
        content_a = load_config_from_file(backup_a.file_path)
    
    content_b = backup_b.content
    if backup_b.file_path:
        content_b = load_config_from_file(backup_b.file_path)
    
    # 计算diff
    change_result = detect_config_change(content_a, content_b)
    
    return {
        "backup_a_id": backup_id_a,
        "backup_b_id": backup_id_b,
        "has_change": change_result.has_change,
        "added_lines": change_result.added_lines,
        "removed_lines": change_result.removed_lines,
        "diff_text": change_result.diff_text,
        "change_summary": change_result.change_summary
    }

# 获取单个备份
@router.get("/{backup_id}", response_model=BackupResponse)
async def read_backup(
    backup_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(Backup).where(Backup.id == backup_id))
    backup = result.scalar_one_or_none()
    if backup is None:
        raise HTTPException(status_code=404, detail="Backup not found")
    return backup

# 获取备份配置内容
@router.get("/{backup_id}/content")
async def get_backup_content(
    backup_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(Backup).where(Backup.id == backup_id))
    backup = result.scalar_one_or_none()
    if backup is None:
        raise HTTPException(status_code=404, detail="Backup not found")
    
    # 从文件或数据库获取内容
    content = backup.content
    if backup.file_path:
        content = load_config_from_file(backup.file_path)
    
    return {"content": content}

# 更新备份标签
@router.patch("/{backup_id}/tag")
async def update_backup_tag(
    request: Request,
    backup_id: int,
    tag: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(Backup).where(Backup.id == backup_id))
    backup = result.scalar_one_or_none()
    if backup is None:
        raise HTTPException(status_code=404, detail="Backup not found")
    
    backup.tag = tag
    await db.commit()
    await db.refresh(backup)
    
    client_ip = get_client_ip_from_request(request)
    await audit_log(db, current_user.id, "backup", backup_id, "update", {"tag": tag}, client_ip)
    
    return backup

# 删除备份
@router.delete("/{backup_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_backup(
    request: Request,
    backup_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    result = await db.execute(select(Backup).where(Backup.id == backup_id))
    backup = result.scalar_one_or_none()
    if backup is None:
        raise HTTPException(status_code=404, detail="Backup not found")
    
    # 删除文件（如果存在）
    if backup.file_path:
        import os
        try:
            os.remove(backup.file_path)
        except:
            pass
    
    await db.execute(delete(BackupAnalysis).where(BackupAnalysis.backup_id == backup_id))
    await db.execute(delete(Backup).where(Backup.id == backup_id))
    await db.commit()
    
    client_ip = get_client_ip_from_request(request)
    await audit_log(db, current_user.id, "backup", backup_id, "delete", {}, client_ip)

# 手动触发单台设备备份
@router.post("/trigger")
async def trigger_backup(
    request: Request,
    device_id: int = Body(..., embed=True),
    tag: str = Body("", embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    # 获取设备
    result = await db.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    # 获取凭证（优先设备凭证，然后找共享凭证）
    result = await db.execute(select(Credential).where(Credential.device_id == device_id))
    credential = result.scalar_one_or_none()
    
    if not credential:
        result = await db.execute(select(Credential).where(Credential.device_id.is_(None)))
        credential = result.scalar_one_or_none()
    
    if not credential:
        raise HTTPException(status_code=400, detail="No credential found")
    
    # 解密凭证
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
    
    # 创建任务ID
    task_id = str(uuid.uuid4())
    active_connections[task_id] = []
    
    try:
        # 执行采集
        device_dict = {
            "id": device.id,
            "ip_address": device.ip_address,
            "vendor": device.vendor,
        }
        
        result = await collect_device_config(device_dict, credential_dict)
        
        # 获取当前版本号
        latest_backup = await db.execute(
            select(Backup).where(Backup.device_id == device_id).order_by(desc(Backup.version)).limit(1)
        )
        latest_backup = latest_backup.scalar_one_or_none()
        new_version = (latest_backup.version if latest_backup else 0) + 1
        
        # 计算哈希和检测变更
        content_hash = calculate_hash(result.config_content) if result.success else ""
        has_change = False
        change_summary = ""
        
        if result.success and latest_backup:
            old_content = latest_backup.content
            if latest_backup.file_path:
                old_content = load_config_from_file(latest_backup.file_path)
            
            if old_content:
                change_result = detect_config_change(old_content, result.config_content)
                has_change = change_result.has_change
                change_summary = change_result.change_summary
        
        # 决定存储方式
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
            trigger="manual",
            operator=current_user.username,
            status="success" if result.success else "failed",
            error_message=result.error_message,
            has_change=has_change,
            change_summary=change_summary,
            tag=tag,
            duration_ms=result.duration_ms,
            size=len(result.config_content) if result.success else 0,
        )
        db.add(backup)
        await db.commit()
        await db.refresh(backup)
        
        # 发送WebSocket消息
        message = {
            "type": "done",
            "total": 1,
            "success": 1 if result.success else 0,
            "failed": 1 if not result.success else 0,
            "device_id": device_id,
            "device_name": device.name,
            "success": result.success,
            "has_change": has_change,
            "change_summary": change_summary
        }
        
        for conn in active_connections.get(task_id, []):
            await conn.send_json(message)
        
        client_ip = get_client_ip_from_request(request)
        await audit_log(db, current_user.id, "backup", backup.id, "create", {"device_id": device_id}, client_ip)
        
        return {"task_id": task_id, "success": result.success, "message": result.error_message}
    
    finally:
        if task_id in active_connections:
            del active_connections[task_id]

# 批量触发备份
@router.post("/trigger-batch")
async def trigger_batch_backup(
    device_ids: list[int] = Body(...),
    tag: str = Body("", embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    task_id = str(uuid.uuid4())
    active_connections[task_id] = []
    
    try:
        total = len(device_ids)
        success_count = 0
        failed_count = 0
        
        for device_id in device_ids:
            # 获取设备
            result = await db.execute(select(Device).where(Device.id == device_id))
            device = result.scalar_one_or_none()
            if not device:
                continue
            
            # 获取凭证
            result = await db.execute(select(Credential).where(Credential.device_id == device_id))
            credential = result.scalar_one_or_none()
            
            if not credential:
                result = await db.execute(select(Credential).where(Credential.device_id.is_(None)))
                credential = result.scalar_one_or_none()
            
            if not credential:
                continue
            
            # 解密凭证
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
            
            # 发送进度消息
            for conn in active_connections.get(task_id, []):
                await conn.send_json({
                    "type": "progress",
                    "device_id": device_id,
                    "device_name": device.name,
                    "status": "connecting"
                })
            
            # 执行采集
            device_dict = {
                "id": device.id,
                "ip_address": device.ip_address,
                "vendor": device.vendor,
            }
            
            result = await collect_device_config(device_dict, credential_dict)
            
            # 创建备份记录（简化处理）
            if result.success:
                latest_backup = await db.execute(
                    select(Backup).where(Backup.device_id == device_id).order_by(desc(Backup.version)).limit(1)
                )
                latest_backup = latest_backup.scalar_one_or_none()
                new_version = (latest_backup.version if latest_backup else 0) + 1
                
                content_hash = calculate_hash(result.config_content)
                content = result.config_content
                file_path = ""
                if len(content) > 100 * 1024:
                    file_path = save_config_to_file(device_id, 0, content)
                    content = ""
                
                backup = Backup(
                    device_id=device_id,
                    version=new_version,
                    content=content,
                    content_hash=content_hash,
                    file_path=file_path,
                    trigger="manual",
                    operator=current_user.username,
                    status="success",
                    duration_ms=result.duration_ms,
                    size=len(result.config_content),
                    tag=tag,
                )
                db.add(backup)
                
                success_count += 1
            else:
                failed_count += 1
            
            # 发送结果消息
            for conn in active_connections.get(task_id, []):
                await conn.send_json({
                    "type": "result",
                    "device_id": device_id,
                    "device_name": device.name,
                    "success": result.success,
                    "error_message": result.error_message
                })
        
        await db.commit()
        
        # 发送完成消息
        for conn in active_connections.get(task_id, []):
            await conn.send_json({
                "type": "done",
                "total": total,
                "success": success_count,
                "failed": failed_count
            })
        
        return {"task_id": task_id, "total": total, "success": success_count, "failed": failed_count}
    
    finally:
        if task_id in active_connections:
            del active_connections[task_id]

# 还原配置到设备
@router.post("/{backup_id}/restore")
async def restore_backup(
    request: Request,
    backup_id: int,
    ip_address: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    """
    将指定备份版本的配置还原到设备
    """
    import logging
    logger = logging.getLogger("cornerstone")
    logger.info(f"========== 开始还原备份 {backup_id} ==========")
    
    # 获取备份记录
    result = await db.execute(select(Backup).where(Backup.id == backup_id))
    backup = result.scalar_one_or_none()
    
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")
    
    # 获取设备
    result = await db.execute(select(Device).where(Device.id == backup.device_id))
    device = result.scalar_one_or_none()
    
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    # 获取凭证（优先设备凭证，然后找共享凭证）
    result = await db.execute(select(Credential).where(Credential.device_id == backup.device_id))
    credential = result.scalar_one_or_none()
    
    if not credential:
        result = await db.execute(select(Credential).where(Credential.device_id.is_(None)))
        credential = result.scalars().first()
    
    if not credential:
        raise HTTPException(status_code=400, detail="No credential found")
    
    # 获取配置内容
    config_content = backup.content
    if backup.file_path:
        config_content = load_config_from_file(backup.file_path)
    
    if not config_content:
        raise HTTPException(status_code=400, detail="Backup content is empty")
    
    # 解密凭证
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
    
    # 构建设备信息
    device_dict = {
        "id": device.id,
        "ip_address": ip_address,
        "vendor": device.vendor or "huawei_vrp",
    }
    
    # 应用配置到设备
    result = await apply_config_to_device(device_dict, credential_dict, config_content)
    
    if result.success:
        client_ip = get_client_ip_from_request(request)
        await audit_log(db, current_user.id, "backup", backup_id, "restore", {"device_id": backup.device_id}, client_ip)
    
    return {
        "success": result.success,
        "message": result.error_message if not result.success else "配置还原成功",
        "durationMs": result.duration_ms
    }

# WebSocket实时推送
@router.websocket("/ws/{task_id}")
async def websocket_scan(
    websocket: WebSocket,
    task_id: str,
    db: AsyncSession = Depends(get_db)
):
    await websocket.accept()
    
    # 验证用户身份
    from .dependencies import get_ws_user
    try:
        await get_ws_user(websocket, db)
    except Exception as e:
        await websocket.close(code=1008, reason=str(e))
        return
    
    if task_id not in active_connections:
        active_connections[task_id] = []
    
    active_connections[task_id].append(websocket)
    
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if task_id in active_connections:
            active_connections[task_id].remove(websocket)
            if not active_connections[task_id]:
                del active_connections[task_id]