"""审计日志归档与清理。

等保要求审计记录至少留存 6 个月。清理流程固定为：
1. 查询到期记录；
2. 先导出 CSV 到归档目录并落盘（fsync + 原子 rename）；
3. 归档成功后才按主键删除；归档失败则整批中止，不删除任何记录。

数据库事务由调用方提交/回滚。
"""
from __future__ import annotations

import csv
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Iterable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.audit_log import AuditLog
from ..utils.timeutil import utc_now

logger = logging.getLogger(__name__)

# 等保 6 个月下限；配置小于该值时按该值执行，避免误配导致合规缺口
MIN_RETENTION_DAYS = 180
LOGIN_ACTIONS = ("login", "logout")
DELETE_CHUNK = 500

CSV_HEADER = ("id", "user", "action", "resource", "detail", "ip_address", "success", "created_at")


def normalize_retention_days(value, default: int = MIN_RETENTION_DAYS) -> int:
    """保留天数归一：非法值回落默认值，且不得低于 180 天。"""
    try:
        days = int(value)
    except (TypeError, ValueError):
        days = default
    return max(MIN_RETENTION_DAYS, days)


def resolve_archive_dir() -> Path:
    """归档目录：优先 AUDIT_ARCHIVE_DIR，否则放在备份目录下。"""
    configured = (settings.audit_archive_dir or "").strip()
    if configured:
        return Path(configured)
    return Path(settings.backup_dir) / "audit-logs"


def _write_csv(path: Path, rows: list[AuditLog]) -> None:
    """写 CSV 到临时文件并原子替换；任何异常都会向上抛出，阻止后续删除。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_HEADER)
        for row in rows:
            created_at = row.created_at.isoformat() if row.created_at else ""
            writer.writerow([
                row.id, row.user, row.action, row.resource, row.detail,
                row.ip_address or "", row.success or "", created_at,
            ])
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)


def _chunks(items: list[int], size: int = DELETE_CHUNK) -> Iterable[list[int]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


async def archive_and_delete_audit_logs(
    db: AsyncSession,
    audit_cutoff: datetime,
    login_cutoff: datetime,
) -> dict:
    """归档并删除到期审计日志；返回删除数量与归档文件路径。

    归档文件写成功之前不会执行任何 DELETE。
    """
    normal_rows = (await db.execute(
        select(AuditLog).where(
            AuditLog.created_at < audit_cutoff,
            AuditLog.action.notin_(LOGIN_ACTIONS),
        ).order_by(AuditLog.id)
    )).scalars().all()

    login_rows = (await db.execute(
        select(AuditLog).where(
            AuditLog.created_at < login_cutoff,
            AuditLog.action.in_(LOGIN_ACTIONS),
        ).order_by(AuditLog.id)
    )).scalars().all()

    if not normal_rows and not login_rows:
        return {"deleted_audit": 0, "deleted_login": 0, "archives": []}

    stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    archive_dir = resolve_archive_dir()
    archives: list[str] = []

    # 先全部落盘，再删除；任一文件失败都会抛异常，删除不会发生
    if normal_rows:
        path = archive_dir / f"audit_logs_{stamp}.csv"
        _write_csv(path, normal_rows)
        archives.append(str(path))
    if login_rows:
        path = archive_dir / f"login_logs_{stamp}.csv"
        _write_csv(path, login_rows)
        archives.append(str(path))

    for ids in _chunks([r.id for r in normal_rows]):
        await db.execute(delete(AuditLog).where(AuditLog.id.in_(ids)))
    for ids in _chunks([r.id for r in login_rows]):
        await db.execute(delete(AuditLog).where(AuditLog.id.in_(ids)))

    logger.info(
        "审计日志归档完成：审计 %s 条、登录 %s 条，文件 %s",
        len(normal_rows), len(login_rows), archives,
    )
    return {
        "deleted_audit": len(normal_rows),
        "deleted_login": len(login_rows),
        "archives": archives,
    }
