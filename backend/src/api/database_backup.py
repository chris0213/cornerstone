"""数据库备份文件管理 API（仅 super_admin）。

列出宿主机 cron 产出的 pg_dump 文件（容器内只读挂载于 DB_BACKUP_DIR），
并提供安全下载。安全要点：
- 文件名必须匹配 cornerstone_*.dump，禁止任何路径分隔符/..，realpath 必须落在允许目录内（防目录穿越）；
- 仅 super_admin；下载写审计（属导出类敏感操作）。
"""
import asyncio
import os
import re
import socket
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings as app_config
from ..database import get_db
from ..models.audit_log import AuditLog
from ..api.dependencies import require_super_admin
from ..utils.ip_whitelist import get_client_ip_from_request
from ..utils.logger import get_logger

router = APIRouter()
logger = get_logger()

# 容器内备份目录（compose 把宿主机 db_backups 读写挂到这里）；可用 env 覆盖
BACKUP_DIR = os.environ.get("DB_BACKUP_DIR", "/opt/cornerstone/db_backups")
# 仅允许该命名规则的 dump 文件
_FILENAME_RE = re.compile(r"^cornerstone_[A-Za-z0-9._-]{1,120}\.dump$")

# 同一时刻只允许一个 pg_dump，避免并发把库压垮
_dump_lock = asyncio.Lock()
_create_last_ts: float = 0.0
_DUMP_TIMEOUT = 600


def _safe_resolve(filename: str) -> str:
    """把文件名解析为目录内的真实路径，越界/非法抛 400。"""
    if not _FILENAME_RE.match(filename):
        raise HTTPException(status_code=400, detail="非法的备份文件名")
    base = os.path.realpath(BACKUP_DIR)
    target = os.path.realpath(os.path.join(base, filename))
    # 必须仍在 base 目录内（防符号链接/穿越）
    if target != base and not target.startswith(base + os.sep):
        raise HTTPException(status_code=400, detail="路径越界，已拒绝")
    if not os.path.isfile(target):
        raise HTTPException(status_code=404, detail="备份文件不存在")
    return target


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
    """列出数据库备份文件（名称/大小/修改时间），按时间倒序。"""
    if not os.path.isdir(BACKUP_DIR):
        return {"dir": BACKUP_DIR, "exists": False, "files": []}
    items = []
    for name in os.listdir(BACKUP_DIR):
        if not _FILENAME_RE.match(name):
            continue
        full = os.path.join(BACKUP_DIR, name)
        if not os.path.isfile(full):
            continue
        st = os.stat(full)
        items.append({
            "name": name,
            "size_bytes": st.st_size,
            "size_mb": round(st.st_size / 1024 / 1024, 2),
            "modified_at": st.st_mtime,
        })
    items.sort(key=lambda x: x["modified_at"], reverse=True)
    return {"dir": BACKUP_DIR, "exists": True, "files": items}


@router.get("/files/{filename}/download")
async def download_file(
    filename: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_super_admin),
):
    """下载指定备份文件（仅 super_admin，写审计）。"""
    path = _safe_resolve(filename)
    await _audit(db, request, current_user, "database_backup_download",
                 f"下载数据库备份文件：{filename}")
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _db_conn_parts() -> dict:
    """从 database_url_sync 解析 pg_dump 所需连接参数（密码单独走 env）。"""
    u = make_url(app_config.database_url_sync)
    return {
        "host": u.host or "localhost",
        "port": str(u.port or 5432),
        "user": u.username or "",
        "dbname": u.database or "",
        "password": u.password or "",
    }


@router.post("/create")
async def create_backup(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_super_admin),
):
    """立即执行一次 pg_dump 生成备份（仅 super_admin，串行 + 限频 + 审计）。"""
    global _create_last_ts
    limit = app_config.credential_test_rate_limit_seconds or 10
    now = time.time()
    if limit > 0 and now - _create_last_ts < limit:
        raise HTTPException(status_code=429,
                            detail=f"操作过于频繁，请 {int(limit - (now - _create_last_ts)) + 1} 秒后再试")

    if _dump_lock.locked():
        raise HTTPException(status_code=409, detail="已有备份正在进行，请稍后再试")

    if not os.path.isdir(BACKUP_DIR):
        try:
            os.makedirs(BACKUP_DIR, exist_ok=True)
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"备份目录不可写：{e}")

    parts = _db_conn_parts()
    if not parts["dbname"]:
        raise HTTPException(status_code=500, detail="数据库名解析失败")

    stamp = time.strftime("%Y%m%d_%H%M%S")
    host = re.sub(r"[^A-Za-z0-9._-]", "_", socket.gethostname())[:60]
    filename = f"cornerstone_{host}_{stamp}.dump"
    outpath = os.path.join(BACKUP_DIR, filename)

    # argv 化执行 pg_dump，密码走 PGPASSWORD env，绝不进 argv、绝不 shell=True
    argv = [
        "pg_dump",
        "-h", parts["host"], "-p", parts["port"],
        "-U", parts["user"], "-d", parts["dbname"],
        "--format=custom", "--compress=6", "--file", outpath,
    ]
    env = {**os.environ, "PGPASSWORD": parts["password"]}

    async with _dump_lock:
        _create_last_ts = time.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
            try:
                _, err = await asyncio.wait_for(proc.communicate(), timeout=_DUMP_TIMEOUT)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                if os.path.exists(outpath):
                    os.remove(outpath)
                await _audit(db, request, current_user, "database_backup_create",
                             f"立即备份失败：超时（>{_DUMP_TIMEOUT}s）")
                raise HTTPException(status_code=504, detail="备份超时")
            if proc.returncode != 0 or not os.path.isfile(outpath):
                msg = err.decode("utf-8", "replace")[:500] if err else "pg_dump 失败"
                if os.path.exists(outpath):
                    os.remove(outpath)
                await _audit(db, request, current_user, "database_backup_create",
                             f"立即备份失败：{msg}")
                raise HTTPException(status_code=500, detail=f"备份失败：{msg}")
            size = os.path.getsize(outpath)
            await _audit(db, request, current_user, "database_backup_create",
                         f"立即备份成功：{filename}（{size} 字节）")
            return {"ok": True, "name": filename, "size_bytes": size}
        except FileNotFoundError:
            raise HTTPException(status_code=500, detail="pg_dump 不可用：后端镜像未安装 postgresql-client")


@router.delete("/files/{filename}")
async def delete_file(
    filename: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_super_admin),
):
    """删除指定备份文件（仅 super_admin，realpath 防穿越，写审计）。"""
    path = _safe_resolve(filename)
    try:
        os.remove(path)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"删除失败：{e}")
    await _audit(db, request, current_user, "database_backup_delete",
                 f"删除数据库备份文件：{filename}")
    return {"ok": True, "name": filename}
