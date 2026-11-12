from logging.config import fileConfig

from sqlalchemy import create_engine, engine_from_config
from sqlalchemy import pool

from alembic import context

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from src.database import Base
from src.config import settings
import src.models  # noqa: F401  # 注册所有模型到 Base.metadata，供 autogenerate 检测

config = context.config
# 连接串统一来自 Settings（DATABASE_URL_SYNC），alembic.ini 不再写死任何方言地址
config.set_main_option("sqlalchemy.url", settings.database_url_sync)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

is_sqlite = settings.database_url_sync.startswith("sqlite")


def _connect_args() -> dict:
    """PG 迁移会话固定 UTC，避免 timestamptz 读写受服务器/客户端 TZ 影响。"""
    if settings.database_url_sync.startswith("postgresql"):
        return {"options": "-c timezone=UTC"}
    return {}


def _configure_kwargs() -> dict:
    return dict(
        target_metadata=target_metadata,
        # 开启类型比较：autogenerate 能识别 VARCHAR 长度、JSON→JSONB 等类型变更
        compare_type=True,
        # SQLite 不支持大部分 ALTER COLUMN，alter 时用 batch 模式重建表
        render_as_batch=is_sqlite,
    )


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_configure_kwargs(),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=_connect_args(),
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, **_configure_kwargs())

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
