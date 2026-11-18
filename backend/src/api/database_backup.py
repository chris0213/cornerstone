"""数据库备份管理 API（仅 super_admin）。

两条能力：
1. 文件管理：列出/下载/删除宿主机挂载目录里的 pg_dump 文件，手动「立即备份」。
2. 调度配置：每日定时备份频率 + 保留策略（天数 + 至少 N 个），存 settings.db_backup_config，
   保存后重载应用内调度任务。安全要点：
- 文件名必须匹配 cornerstone_*.dump，禁止路径分隔符/..，realpath 必须落在允许目录内（防穿越）；
- 仅 super_admin；下载/备份/配置变更写审计；
- 手动备份（__manual 与历史无标记）永不被保留策略删除，仅 __auto 受清理。
"""
import os
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings as app_config
from ..database import get_db
from ..models.audit_log import AuditLog
from ..api.dependencies import require_super_admin
from ..utils.ip_whitelist import get_client_ip_from_request
from ..utils.logger import get_logger
from ..services import db_backup_service as dbsvc
from ..services.db_backup_service import (
    _safe_resolve, _dump_lock, _verify_lock,
    run_pg_dump, list_dump_files, apply_retention, verify_dump, TRIGGER_MANUAL,
)
from ..services.db_backup_store import (
    load_stored_config, save_stored_config, validate_config, get_effective_config, DEFAULTS,
)

router = APIRouter()
logger = get_logger()

_create_last_ts: float = 0.0


async def _audit(db, request, user, action, detail):
    db.add(AuditLog(
        user=user.username, action=action, resource="database_backup",
        detail=detail, ip_address=get_client_ip_from_request(request), success="true",
    ))
    await db.commit()


@router.get("/files")
async def list_files(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_super_admin),
):
    """列出数据库备份文件（名称/大小/修改时间/来源），按时间倒序。"""
    exists = os.path.isdir(dbsvc.BACKUP_DIR)
    return {"dir": dbsvc.BACKUP_DIR, "exists": exists, "files": list_dump_files()}


@router.get("/files/{filename}/download")
async def download_file(
    filename: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_super_admin),
):
    """下载指定备份文件（仅 super_admin，写审计）。"""
    try:
        path = _safe_resolve(filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="备份文件不存在")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await _audit(db, request, current_user, "database_backup_download",
                 f"下载数据库备份文件：{filename}")
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/create")
async def create_backup(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_super_admin),
):
    """立即执行一次 pg_dump 生成手动备份（仅 super_admin，串行 + 限频 + 审计）。

    产出的文件标记为 __manual，永不被保留策略删除；备份后按当前配置清理 __auto。
    """
    global _create_last_ts
    limit = app_config.credential_test_rate_limit_seconds or 10
    now = time.time()
    if limit > 0 and now - _create_last_ts < limit:
        raise HTTPException(status_code=429,
                            detail=f"操作过于频繁，请 {int(limit - (now - _create_last_ts)) + 1} 秒后再试")

    if _dump_lock.locked():
        raise HTTPException(status_code=409, detail="已有备份正在进行，请稍后再试")

    _create_last_ts = time.time()
    try:
        res = await run_pg_dump(TRIGGER_MANUAL)
    except TimeoutError:
        await _audit(db, request, current_user, "database_backup_create", "立即备份失败：超时")
        raise HTTPException(status_code=504, detail="备份超时")
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except (RuntimeError, ValueError) as e:
        await _audit(db, request, current_user, "database_backup_create", f"立即备份失败：{e}")
        raise HTTPException(status_code=500, detail=f"备份失败：{e}")

    cfg = get_effective_config(await load_stored_config(db))
    cleanup = apply_retention(cfg["retention_days"], cfg["keep_last"])
    await _audit(db, request, current_user, "database_backup_create",
                 f"立即备份成功：{res['name']}（{res['size_bytes']} 字节）；"
                 f"自动清理过期 {len(cleanup['deleted'])} 个")
    return {"ok": True, "name": res["name"], "size_bytes": res["size_bytes"],
            "retention_deleted": cleanup["deleted"]}


@router.delete("/files/{filename}")
async def delete_file(
    filename: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_super_admin),
):
    """删除指定备份文件（仅 super_admin，realpath 防穿越，写审计）。"""
    try:
        path = _safe_resolve(filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="备份文件不存在")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        os.remove(path)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"删除失败：{e}")
    await _audit(db, request, current_user, "database_backup_delete",
                 f"删除数据库备份文件：{filename}")
    return {"ok": True, "name": filename}


class BackupConfigRequest(BaseModel):
    enabled: bool = False
    schedule_time: str = Field(default="03:30")
    retention_days: int = Field(default=30)
    keep_last: int = Field(default=7)
    auto_verify: bool = False


@router.get("/config")
async def get_config(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_super_admin),
):
    """读取数据库备份调度配置（含默认值合并 + 下次执行时间）。"""
    cfg = get_effective_config(await load_stored_config(db))
    next_run = None
    try:
        from ..tasks.backup_scheduler import scheduler
        from ..tasks.db_backup_scheduler import JOB_ID
        job = scheduler.get_job(JOB_ID)
        if job is not None and getattr(job, "next_run_time", None):
            next_run = job.next_run_time.isoformat()
    except Exception as e:
        logger.warning(f"[数据库备份] 读取下次执行时间失败: {e}")
    last_verify = None
    try:
        from ..tasks.db_backup_scheduler import get_last_verify
        last_verify = get_last_verify() or None
    except Exception:
        pass
    return {**cfg, "next_run": next_run, "last_verify": last_verify}


@router.put("/config")
async def update_config(
    req: BackupConfigRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_super_admin),
):
    """保存数据库备份调度配置：校验 + 落库 + 重载调度任务 + 审计。"""
    try:
        validated = validate_config(req.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    await save_stored_config(db, validated)

    try:
        from ..tasks.db_backup_scheduler import reload_db_backup_job
        await reload_db_backup_job(db)
    except Exception as e:
        logger.warning(f"[数据库备份] 调度重载失败（配置已保存）: {e}")

    await _audit(db, http_request, current_user, "database_backup_config_update",
                 f"更新数据库备份调度配置：启用={'是' if validated['enabled'] else '否'}，"
                 f"每日={validated['schedule_time']}，保留={validated['retention_days']}天，"
                 f"至少保留={validated['keep_last']}个，自动校验={'是' if validated['auto_verify'] else '否'}")
    return validated


# ===== 恢复校验（隔离临时库，绝不触碰生产库）=====

class VerifyRequest(BaseModel):
    filename: str


@router.post("/verify")
async def verify_backup(
    req: VerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_super_admin),
):
    """恢复校验：把选定 dump 恢复到隔离库 cornerstone_verify，跑健康检查后清理。

    全程不触碰生产库 cornerstone；仅 super_admin；串行 + 审计。
    返回 {ok, restored, checks:[{table,count}], error}。
    """
    try:
        path = _safe_resolve(req.filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="备份文件不存在")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if _verify_lock.locked():
        raise HTTPException(status_code=409, detail="已有恢复校验正在进行，请稍后再试")

    try:
        result = await verify_dump(path)
    except TimeoutError:
        await _audit(db, request, current_user, "database_backup_verify",
                     f"恢复校验超时：{req.filename}")
        raise HTTPException(status_code=504, detail="恢复校验超时")
    except RuntimeError as e:
        await _audit(db, request, current_user, "database_backup_verify",
                     f"恢复校验失败：{e}")
        raise HTTPException(status_code=500, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=500,
                            detail="psql/pg_restore 不可用：后端镜像未安装 postgresql-client")

    detail = (f"恢复校验 {'通过' if result['ok'] else '未通过'}：{req.filename}；"
              f"抽查 {result['checks']}")
    await _audit(db, request, current_user, "database_backup_verify", detail)
    return result
