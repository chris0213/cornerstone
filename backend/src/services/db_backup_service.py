"""数据库 dump 备份的可执行核心：pg_dump 产出、文件列举、保留清理。

与设备配置备份（backup_scheduler/BackupTask）是两条独立线：这里只管整库 pg_dump。
安全要点：
- 文件名严格匹配 cornerstone_*.dump，realpath 必须落在 BACKUP_DIR 内（防穿越）；
- pg_dump 走 argv 列表 + PGPASSWORD env，绝不 shell=True、密码绝不进 argv；
- 同一时刻只允许一个 pg_dump（_dump_lock，手动与定时共用一把锁）。

来源标记（满足「手动备份永不被保留策略删除」）：
- 立即备份 → 文件名以 __manual.dump 结尾；定时 → __auto.dump；
- 无标记的历史文件保守视为 manual（受保护）。保留清理只作用于 __auto。
"""
import asyncio
import os
import re
import socket
import time

from sqlalchemy.engine import make_url

from ..config import settings as app_config
from ..utils.logger import get_logger

logger = get_logger()

# 容器内备份目录（compose 把宿主机 db_backups 读写挂到这里）；可用 env 覆盖
BACKUP_DIR = os.environ.get("DB_BACKUP_DIR", "/opt/cornerstone/db_backups")
# 仅允许该命名规则的 dump 文件
_FILENAME_RE = re.compile(r"^cornerstone_[A-Za-z0-9._-]{1,120}\.dump$")

# 同一时刻只允许一个 pg_dump，避免并发把库压垮
_dump_lock = asyncio.Lock()
_DUMP_TIMEOUT = 600

TRIGGER_AUTO = "auto"
TRIGGER_MANUAL = "manual"

# 恢复校验：固定隔离库名（非用户输入，防注入）；同一时刻只跑一个（手动与定时共用一把锁）
VERIFY_DB_NAME = "cornerstone_verify"
_verify_lock = asyncio.Lock()
_VERIFY_TIMEOUT = 600
# 校验时抽查的关键表（硬编码，非用户输入）
_VERIFY_TABLES = ("devices", "users", "backups", "audit_logs", "sites", "circuits")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


# 运行台账 db_backup_runs 只保留最近 N 条（默认 30，可用环境变量覆盖）
RUNS_RETENTION_KEEP = _env_int("DB_BACKUP_RUNS_KEEP", 30)


def _safe_resolve(filename: str) -> str:
    """把文件名解析为目录内的真实路径，越界/非法抛 ValueError。"""
    if not _FILENAME_RE.match(filename):
        raise ValueError("非法的备份文件名")
    base = os.path.realpath(BACKUP_DIR)
    target = os.path.realpath(os.path.join(base, filename))
    # 必须仍在 base 目录内（防符号链接/穿越）
    if target != base and not target.startswith(base + os.sep):
        raise ValueError("路径越界，已拒绝")
    if not os.path.isfile(target):
        raise FileNotFoundError("备份文件不存在")
    return target


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


def dump_trigger(name: str) -> str:
    """从文件名判断来源：含 __auto 为定时，否则（含 __manual 与历史无标记）为手动/受保护。"""
    return TRIGGER_AUTO if "__auto" in name else TRIGGER_MANUAL


def list_dump_files() -> list[dict]:
    """列出备份文件（名称/大小/修改时间/来源），按修改时间倒序。"""
    if not os.path.isdir(BACKUP_DIR):
        return []
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
            "trigger": dump_trigger(name),
        })
    items.sort(key=lambda x: x["modified_at"], reverse=True)
    return items


async def run_pg_dump(trigger: str = TRIGGER_MANUAL) -> dict:
    """执行一次整库 pg_dump 产出 custom 格式 dump，返回 {name, size_bytes}。

    抛错语义：
    - TimeoutError：超时（已清理半成品）；
    - FileNotFoundError：pg_dump 不可用（镜像未装 postgresql-client）；
    - RuntimeError：库名解析失败 / pg_dump 非 0 退出 / 产物缺失。
    """
    if trigger not in (TRIGGER_AUTO, TRIGGER_MANUAL):
        raise ValueError(f"非法 trigger: {trigger}")
    if not os.path.isdir(BACKUP_DIR):
        os.makedirs(BACKUP_DIR, exist_ok=True)

    parts = _db_conn_parts()
    if not parts["dbname"]:
        raise RuntimeError("数据库名解析失败")

    stamp = time.strftime("%Y%m%d_%H%M%S")
    host = re.sub(r"[^A-Za-z0-9._-]", "_", socket.gethostname())[:60]
    filename = f"cornerstone_{host}_{stamp}__{trigger}.dump"
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
                raise TimeoutError(f"pg_dump 超时（>{_DUMP_TIMEOUT}s）")
            if proc.returncode != 0 or not os.path.isfile(outpath):
                msg = err.decode("utf-8", "replace")[:500] if err else "pg_dump 失败"
                if os.path.exists(outpath):
                    os.remove(outpath)
                raise RuntimeError(msg)
            return {"name": filename, "size_bytes": os.path.getsize(outpath)}
        except FileNotFoundError:
            raise FileNotFoundError("pg_dump 不可用：后端镜像未安装 postgresql-client")


def apply_retention(retention_days: int, keep_last: int) -> dict:
    """保留策略：仅清理 __auto 文件。

    语义（满足「手动备份永不被删」）：
    - 先按修改时间倒序，把最近 keep_last 个 auto 文件设为保护（永不删）；
    - 其余 auto 文件中，修改时间早于 retention_days 天的删除；
    - retention_days<=0 表示不按时间清理；keep_last<=0 表示不强制保底（仅按天数）。
    返回 {deleted, auto_total, protected_manual}。
    """
    if not os.path.isdir(BACKUP_DIR):
        return {"deleted": [], "auto_total": 0, "protected_manual": 0}
    now = time.time()
    entries = []
    for name in os.listdir(BACKUP_DIR):
        if not _FILENAME_RE.match(name):
            continue
        full = os.path.join(BACKUP_DIR, name)
        if not os.path.isfile(full):
            continue
        entries.append((name, full, os.stat(full).st_mtime, dump_trigger(name)))

    autos = sorted((e for e in entries if e[3] == TRIGGER_AUTO), key=lambda x: x[2], reverse=True)
    rest = autos[keep_last:] if (keep_last and keep_last > 0) else autos

    cutoff = (now - retention_days * 86400) if (retention_days and retention_days > 0) else None
    deleted = []
    if cutoff is not None:
        for name, full, mtime, _ in rest:
            if mtime < cutoff:
                try:
                    os.remove(full)
                    deleted.append(name)
                except OSError:
                    pass

    return {
        "deleted": deleted,
        "auto_total": len(autos),
        "protected_manual": sum(1 for e in entries if e[3] != TRIGGER_AUTO),
    }


async def verify_dump(path: str) -> dict:
    """把已解析好的 dump 绝对路径恢复到隔离库 cornerstone_verify，抽查关键表行数后清理。

    绝不触碰生产库 cornerstone；与手动校验共用 _verify_lock 串行。
    返回 {ok, restored, checks:[{table,count}], error}；
    抛错语义：TimeoutError（超时）/ RuntimeError（建库失败）/ FileNotFoundError（psql/pg_restore 不可用）。
    """
    parts = _db_conn_parts()
    base = ["-h", parts["host"], "-p", parts["port"], "-U", parts["user"]]
    env = {**os.environ, "PGPASSWORD": parts["password"]}
    # 维护库用 postgres（连它来做 CREATE/DROP，避免连到目标库自身）
    psql_admin = ["psql", *base, "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-tAc"]
    # 抽查计数必须连隔离库本身（cornerstone_verify），不能连 postgres 维护库
    psql_verify = ["psql", *base, "-d", VERIFY_DB_NAME, "-v", "ON_ERROR_STOP=1", "-tAc"]

    async with _verify_lock:
        checks: list[dict] = []
        perr = ""
        try:
            # 1) 重建隔离库（FORCE 断开残留连接）
            await _run_cmd([*psql_admin,
                            f"DROP DATABASE IF EXISTS {VERIFY_DB_NAME} WITH (FORCE);"], env, 60)
            rc, out, err = await _run_cmd([*psql_admin,
                                           f"CREATE DATABASE {VERIFY_DB_NAME} OWNER {parts['user']};"], env, 60)
            if rc != 0:
                raise RuntimeError(f"创建隔离库失败：{err[:300]}")

            # 2) 把 dump 恢复到隔离库（pg_restore 连隔离库）
            prc, pout, perr = await _run_cmd(
                ["pg_restore", *base, "-d", VERIFY_DB_NAME, "--no-owner", path], env, _VERIFY_TIMEOUT)
            restored = (prc == 0)
            if prc != 0:
                logger.warning(f"[恢复校验] pg_restore rc={prc}: {perr[:500]}")

            # 3) 抽查关键表行数（逐表，连隔离库；缺表记 N/A 不影响其它）
            for t in _VERIFY_TABLES:
                crc, cout, cerr = await _run_cmd([*psql_verify, f"SELECT count(*) FROM {t};"], env, 60)
                if crc == 0 and cout.strip().isdigit():
                    checks.append({"table": t, "count": int(cout.strip())})
                else:
                    checks.append({"table": t, "count": None})

            ok = restored and any(c["count"] and c["count"] > 0 for c in checks)
            return {"ok": ok, "restored": restored, "checks": checks,
                    "error": None if restored else (perr[:300] or None)}
        finally:
            # 4) 无论成败，清理隔离库
            try:
                await _run_cmd([*psql_admin,
                                f"DROP DATABASE IF EXISTS {VERIFY_DB_NAME} WITH (FORCE);"], env, 60)
            except Exception as e:
                logger.warning(f"[恢复校验] 清理隔离库失败（请手动 DROP {VERIFY_DB_NAME}）：{e}")


async def record_run(db, *, trigger: str, status: str, operator: str | None = None,
                     filename: str | None = None, size_bytes: int | None = None,
                     duration_ms: int | None = None, error: str | None = None,
                     retention_deleted: int | None = None, verify_status: str | None = None,
                     verify_error: str | None = None, verify_checks: list | None = None) -> None:
    """写一行数据库备份运行台账（系统级，不挂租户），随后裁剪只保留最近 RUNS_RETENTION_KEEP 条。

    失败不抛出，仅记日志，避免影响备份主流程。
    """
    from ..models.db_backup_run import DbBackupRun
    try:
        db.add(DbBackupRun(
            trigger=trigger, status=status, operator=operator, filename=filename,
            size_bytes=size_bytes, duration_ms=duration_ms, error=error,
            retention_deleted=retention_deleted, verify_status=verify_status,
            verify_error=verify_error, verify_checks=verify_checks,
        ))
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"[数据库备份] 写入运行台账失败（不影响备份主流程）: {e}")
        return
    await prune_runs(db)


async def prune_runs(db, keep: int | None = None) -> int:
    """裁剪 db_backup_runs 只保留最近 keep 条（默认 RUNS_RETENTION_KEEP）。keep<=0 不裁剪。

    返回删除条数；失败只记日志不外抛。
    """
    from sqlalchemy import delete, select
    from ..models.db_backup_run import DbBackupRun
    if keep is None:
        keep = RUNS_RETENTION_KEEP
    if keep <= 0:
        return 0
    try:
        keep_ids = select(DbBackupRun.id).order_by(
            DbBackupRun.created_at.desc(), DbBackupRun.id.desc()).limit(keep)
        result = await db.execute(delete(DbBackupRun).where(DbBackupRun.id.notin_(keep_ids)))
        await db.commit()
        deleted = result.rowcount or 0
        if deleted:
            logger.info(f"[数据库备份] 运行台账裁剪：删除 {deleted} 条，保留最近 {keep} 条")
        return deleted
    except Exception as e:
        await db.rollback()
        logger.error(f"[数据库备份] 裁剪运行台账失败（不影响主流程）: {e}")
        return 0
