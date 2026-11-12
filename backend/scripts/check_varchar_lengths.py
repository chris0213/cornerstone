"""VARCHAR 长度体检：找出超过模型声明长度的存量数据。

SQLite 不强制 VARCHAR 长度，PostgreSQL 会强制；把 SQLite 数据导入/迁移到 PG 前
必须先找出并处理超长值，否则写入会被 PG 拒绝。

用法（在 backend 目录执行）：
    .venv/bin/python scripts/check_varchar_lengths.py            # 只体检
    .venv/bin/python scripts/check_varchar_lengths.py --fix      # 截断超长值到声明长度
    .venv/bin/python scripts/check_varchar_lengths.py --table devices

退出码：0 = 无超长数据；1 = 存在超长数据（可直接用作迁移前置检查）。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import String, inspect as sa_inspect, select

from src.database import Base, sync_engine
import src.models  # noqa: F401  # 注册全部模型


def varchar_columns(only_table: str | None):
    for table in Base.metadata.sorted_tables:
        if only_table and table.name != only_table:
            continue
        for col in table.columns:
            if isinstance(col.type, String) and col.type.length:
                yield table, col


def main() -> int:
    parser = argparse.ArgumentParser(description="VARCHAR 长度体检")
    parser.add_argument("--fix", action="store_true", help="把超长值截断到声明长度（会丢失尾部字符）")
    parser.add_argument("--table", default=None, help="只检查指定表")
    args = parser.parse_args()

    dialect = sync_engine.dialect.name
    print(f"连接方言: {dialect}")
    insp = sa_inspect(sync_engine)
    existing_tables = set(insp.get_table_names())

    total_issues = 0
    with sync_engine.begin() as conn:
        for table, col in varchar_columns(args.table):
            if table.name not in existing_tables:
                continue
            max_len = col.type.length
            pk = list(table.primary_key.columns)
            stmt = select(*pk, col).where(col.isnot(None))
            rows = conn.execute(stmt).all()
            over = [(tuple(r[: len(pk)]), r[-1]) for r in rows if len(r[-1]) > max_len]
            if not over:
                continue
            total_issues += len(over)
            print(f"\n[{table.name}.{col.name}] 声明长度 {max_len}，超长 {len(over)} 行")
            for key, value in over[:5]:
                print(f"  PK={key} 实际长度={len(value)} 值={value[:120]!r}")
            if len(over) > 5:
                print(f"  ... 其余 {len(over) - 5} 行省略")
            if args.fix:
                for key, value in over:
                    conn.execute(
                        table.update()
                        .where(*[c == k for c, k in zip(pk, key)])
                        .values({col.name: value[:max_len]})
                    )
                print(f"  已截断 {len(over)} 行到 {max_len} 字符")

    if total_issues == 0:
        print("\n体检结果: 未发现超长数据")
        return 0
    print(f"\n体检结果: 发现 {total_issues} 行超长数据" + ("（已截断）" if args.fix else "（未修改，可加 --fix）"))
    return 1 if not args.fix else 0


if __name__ == "__main__":
    raise SystemExit(main())
