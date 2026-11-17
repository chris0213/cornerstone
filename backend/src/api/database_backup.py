"""数据库备份文件管理 API（仅 super_admin）。

列出宿主机 cron 产出的 pg_dump 文件（容器内只读挂载于 DB_BACKUP_DIR），
并提供安全下载。安全要点：
- 文件名必须匹配 cornerstone_*.dump，禁止任何路径分隔符/..，realpath 必须落在允许目录内（防目录穿越）；
- 仅 super_admin；下载写审计（属导出类敏感操作）。
"""
import os
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.audit_log import AuditLog
from ..api.dependencies import require_super_admin
from ..utils.ip_whitelist import get_client_ip_from_request
from ..utils.logger import get_logger

router = APIRouter()
logger = get_logger()

# 容器内备份目录（compose 把宿主机 db_backups 只读挂到这里）；可用 env 覆盖
BACKUP_DIR = os.environ.get("DB_BACKUP_DIR", "/opt/cornerstone/db_backups")
# 仅允许该命名规则的 dump 文件
_FILENAME_RE = re.compile(r"^cornerstone_[A-Za-z0-9._-]{1,120}\.dump$")


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
