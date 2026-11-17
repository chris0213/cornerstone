"""异地备份同步管理 API（仅 super_admin）。

- GET  /offsite-sync/config   读取（敏感字段脱敏）
- PUT  /offsite-sync/config   保存（校验+加密落库+重载调度+审计）
- POST /offsite-sync/test     连通/认证测试（限频+审计）
- POST /offsite-sync/run      立即同步（限频+审计，结果记录）
- GET  /offsite-sync/status   最近一次同步结果 + 工具可用性
"""
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings as app_config
from ..database import get_db
from ..models.audit_log import AuditLog
from ..api.dependencies import require_super_admin
from ..utils.ip_whitelist import get_client_ip_from_request
from ..utils.logger import get_logger
from ..services.offsite_sync_store import (
    load_stored_config, save_stored_config, validate_config,
    mask_config_for_display, TARGET_TYPES,
)
from ..services.offsite_sync_service import run_sync, test_connection

router = APIRouter()
logger = get_logger()

# 进程内限频与最近结果（重启即清，足够 v1 使用）
_test_last_ts: float = 0.0
_run_last_ts: float = 0.0
_last_sync_result: dict = {}


class OffsiteSyncRequest(BaseModel):
    enabled: bool = False
    target_type: str = Field(default="rclone")
    schedule_time: str = Field(default="04:00")
    source_dir: str = Field(default="")
    # rclone
    rclone_provider: str = Field(default="minio")
    rclone_endpoint: str = Field(default="")
    rclone_bucket: str = Field(default="")
    rclone_region: str = Field(default="")
    rclone_prefix: str = Field(default="cornerstone-db")
    rclone_access_key_id: str | None = Field(default=None)   # None/空=留空不修改
    rclone_secret_access_key: str | None = Field(default=None)
    # rsync
    rsync_host: str = Field(default="")
    rsync_port: int = Field(default=22)
    rsync_user: str = Field(default="")
    rsync_remote_path: str = Field(default="")
    rsync_ssh_key: str | None = Field(default=None)
    # sftp
    sftp_host: str = Field(default="")
    sftp_port: int = Field(default=22)
    sftp_user: str = Field(default="")
    sftp_remote_path: str = Field(default="")
    sftp_ssh_key: str | None = Field(default=None)


async def _audit(db, request, user, action, detail):
    db.add(AuditLog(
        user=user.username, action=action, resource="system_settings",
        detail=detail, ip_address=get_client_ip_from_request(request), success="true",
    ))
    await db.commit()


def _check_rate_limit(kind: str, last_key: str) -> None:
    global _test_last_ts, _run_last_ts
    limit = app_config.credential_test_rate_limit_seconds or 10
    now = time.time()
    last = _test_last_ts if kind == "test" else _run_last_ts
    if limit > 0 and now - last < limit:
        raise HTTPException(
            status_code=429,
            detail=f"操作过于频繁，请 {int(limit - (now - last)) + 1} 秒后再试",
        )
    if kind == "test":
        _test_last_ts = now
    else:
        _run_last_ts = now


@router.get("/config")
async def get_config(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_super_admin),
):
    """读取异地同步配置（敏感字段只回 has_xxx + 尾号）。"""
    stored = await load_stored_config(db)
    return mask_config_for_display(stored)


@router.put("/config")
async def update_config(
    request: OffsiteSyncRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_super_admin),
):
    """保存配置：敏感字段留空=不修改；校验+加密落库+重载调度+审计。"""
    if request.target_type not in TARGET_TYPES:
        raise HTTPException(status_code=422, detail=f"不支持的同步类型: {request.target_type}")

    old = await load_stored_config(db)

    def _keep(new_val, field):
        # 敏感字段：None 或空串 → 保留旧值（旧值可能是密文，validate 会解密比较）
        if new_val is None:
            return old.get(field)
        if isinstance(new_val, str) and not new_val.strip():
            return old.get(field)
        return new_val

    merged = {
        "enabled": request.enabled,
        "target_type": request.target_type,
        "schedule_time": request.schedule_time,
        "source_dir": request.source_dir or old.get("source_dir") or "",
        "rclone_provider": request.rclone_provider,
        "rclone_endpoint": request.rclone_endpoint,
        "rclone_bucket": request.rclone_bucket,
        "rclone_region": request.rclone_region,
        "rclone_prefix": request.rclone_prefix,
        "rclone_access_key_id": _keep(request.rclone_access_key_id, "rclone_access_key_id"),
        "rclone_secret_access_key": _keep(request.rclone_secret_access_key, "rclone_secret_access_key"),
        "rsync_host": request.rsync_host,
        "rsync_port": request.rsync_port,
        "rsync_user": request.rsync_user,
        "rsync_remote_path": request.rsync_remote_path,
        "rsync_ssh_key": _keep(request.rsync_ssh_key, "rsync_ssh_key"),
        "sftp_host": request.sftp_host,
        "sftp_port": request.sftp_port,
        "sftp_user": request.sftp_user,
        "sftp_remote_path": request.sftp_remote_path,
        "sftp_ssh_key": _keep(request.sftp_ssh_key, "sftp_ssh_key"),
    }

    try:
        validated = validate_config(merged)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    await save_stored_config(db, validated)

    # 重载调度任务（失败不影响配置保存）
    try:
        from ..tasks.offsite_sync_scheduler import reload_offsite_sync_job
        await reload_offsite_sync_job(db)
    except Exception as e:
        logger.warning(f"[异地同步] 调度重载失败（配置已保存）: {e}")

    await _audit(db, http_request, current_user, "offsite_sync_update",
                 f"更新异地同步配置：type={validated['target_type']}，"
                 f"启用={'是' if validated.get('enabled') else '否'}，"
                 f"定时={validated.get('schedule_time')}，源目录={validated.get('source_dir')}")

    return mask_config_for_display(validated)


@router.post("/test")
async def test_cfg(
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_super_admin),
):
    """测试已存配置的连通与认证（限频+审计）。"""
    _check_rate_limit("test", "test")
    stored = await load_stored_config(db)
    if not stored:
        raise HTTPException(status_code=400, detail="尚未配置异地同步")
    result = await test_connection(stored)
    await _audit(db, http_request, current_user, "offsite_sync_test",
                 f"测试异地同步（type={stored.get('target_type')}）：{'成功' if result.get('ok') else '失败'}"
                 + (f"（{result.get('error')}）" if result.get("error") else ""))
    return result


@router.post("/run")
async def run_now(
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_super_admin),
):
    """立即执行一次同步（限频+审计，结果记录到进程内状态）。"""
    _check_rate_limit("run", "run")
    stored = await load_stored_config(db)
    if not stored:
        raise HTTPException(status_code=400, detail="尚未配置异地同步")
    global _last_sync_result
    result = await run_sync(stored)
    _last_sync_result = {**result, "at": time.time(), "trigger": "manual",
                        "operator": current_user.username}
    await _audit(db, http_request, current_user, "offsite_sync_run",
                 f"手动触发异地同步（type={stored.get('target_type')}）："
                 f"{'成功' if result.get('ok') else '失败'}"
                 + (f"（{result.get('error')}）" if result.get("error") else ""))
    return _last_sync_result


@router.get("/status")
async def status(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_super_admin),
):
    """最近一次同步结果 + 工具可用性 + 调度状态。"""
    import shutil
    return {
        "last_sync": _last_sync_result or None,
        "tools": {
            "rclone": bool(shutil.which("rclone")),
            "rsync": bool(shutil.which("rsync")),
            "scp": bool(shutil.which("scp")),
        },
    }
