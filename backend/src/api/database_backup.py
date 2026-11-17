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
from pydantic import BaseModel
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

# 恢复校验：固定隔离库名（非用户输入，防注入）；同一时刻只跑一个
VERIFY_DB_NAME = "cornerstone_verify"
_verify_lock = asyncio.Lock()
_VERIFY_TIMEOUT = 600
# 校验时抽查的关键表（硬编码，非用户输入）
_VERIFY_TABLES = ("devices", "users", "backups", "audit_logs", "sites", "circuits")


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


async def _run_cmd(argv: list[str], env: dict, timeout: int) -> tuple[int, str, str]:
    """无 shell 执行 argv，返回 (rc, stdout, stderr)；超时抛 TimeoutError。"""
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        raise
    return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


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
    path = _safe_resolve(req.filename)
    parts = _db_conn_parts()
    base = ["-h", parts["host"], "-p", parts["port"], "-U", parts["user"]]
    env = {**os.environ, "PGPASSWORD": parts["password"]}
    # 维护库用 postgres（连它来做 CREATE/DROP，避免连到目标库自身）
    psql_admin = ["psql", *base, "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-tAc"]

    if _verify_lock.locked():
        raise HTTPException(status_code=409, detail="已有恢复校验正在进行，请稍后再试")

    async with _verify_lock:
        checks: list[dict] = []
        try:
            # 1) 重建隔离库（FORCE 断开残留连接）
            await _run_cmd([*psql_admin,
                            f"DROP DATABASE IF EXISTS {VERIFY_DB_NAME} WITH (FORCE);"],
                           env, 60)
            rc, out, err = await _run_cmd([*psql_admin,
                                           f"CREATE DATABASE {VERIFY_DB_NAME} OWNER {parts['user']};"],
                                          env, 60)
            if rc != 0:
                raise RuntimeError(f"创建隔离库失败：{err[:300]}")

            # 2) 把 dump 恢复到隔离库（pg_restore 连隔离库）
            prc, pout, perr = await _run_cmd(
                ["pg_restore", *base, "-d", VERIFY_DB_NAME, "--no-owner", "--quiet", path],
                env, _VERIFY_TIMEOUT)
            # pg_restore 对某些对象可能返回非 0 但数据可用；记录但据此判断
            restored = (prc == 0)
            if prc != 0:
                logger.warning(f"[恢复校验] pg_restore rc={prc}: {perr[:500]}")

            # 3) 抽查关键表行数（逐表，缺表记 N/A 不影响其它）
            for t in _VERIFY_TABLES:
                crc, cout, cerr = await _run_cmd(
                    [*psql_admin, f"SELECT count(*) FROM {t};"], env, 60)
                if crc == 0 and cout.strip().isdigit():
                    checks.append({"table": t, "count": int(cout.strip())})
                else:
                    checks.append({"table": t, "count": None})

            ok = restored and any(c["count"] and c["count"] > 0 for c in checks)
            detail = (f"恢复校验 {'通过' if ok else '未通过'}：{req.filename}；"
                      f"抽查 {checks}")
            await _audit(db, request, current_user, "database_backup_verify", detail)
            return {"ok": ok, "restored": restored, "checks": checks,
                    "error": None if restored else (perr[:300] or None)}
        except asyncio.TimeoutError:
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
        finally:
            # 4) 无论成败，清理隔离库
            try:
                await _run_cmd([*psql_admin,
                                f"DROP DATABASE IF EXISTS {VERIFY_DB_NAME} WITH (FORCE);"],
                               env, 60)
            except Exception as e:
                logger.warning(f"[恢复校验] 清理隔离库失败（请手动 DROP {VERIFY_DB_NAME}）：{e}")
