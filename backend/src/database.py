from sqlalchemy import DateTime, JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.types import TypeDecorator

from .config import settings
from .utils.timeutil import ensure_utc

# 判断是否为SQLite
is_sqlite = settings.database_url.startswith("sqlite")
is_postgresql = settings.database_url.startswith("postgresql")


class UTCDateTime(TypeDecorator):
    """统一 UTC 时间列：写入/读取都保证是 aware UTC。

    - PG：底层为 TIMESTAMP WITH TIME ZONE，写入 aware UTC，读取返回 aware UTC。
    - SQLite：无时区类型，写入前去掉 tzinfo 但保留 UTC 挂钟，读取时补回 UTC，
      从而与 PG 语义一致（naive 挂钟即 UTC，绝不再出现 naive 北京时间）。
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        value = ensure_utc(value)
        if value is not None and dialect.name == "sqlite":
            # SQLite 的 DATETIME 不保存时区，存 UTC 挂钟，避免 8 小时偏移
            return value.replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        return ensure_utc(value)


# 统一 JSON 类型：PG 用 JSONB（可索引、去重键、写入校验），SQLite 退回 JSON（TEXT）
JSONType = JSON().with_variant(JSONB(), "postgresql")


def _engine_kwargs(is_async: bool) -> dict:
    """按方言生成引擎参数：PG 启连接池 + 会话时区固定 UTC；SQLite 仅开发用。"""
    kwargs: dict = {"echo": settings.debug}
    if is_sqlite:
        # SQLite 单文件、单写锁，仅用于本地开发演示，不配置连接池参数
        kwargs["connect_args"] = {"check_same_thread": False}
        return kwargs
    if not is_postgresql:
        return kwargs

    kwargs.update(
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle_seconds,
        pool_pre_ping=settings.db_pool_pre_ping,
    )
    # 会话时区固定 UTC：避免服务端/客户端 TZ 不同导致 naive 绑定值被二次解释
    if is_async:
        kwargs["connect_args"] = {"server_settings": {"timezone": "UTC"}}
    else:
        kwargs["connect_args"] = {"options": "-c timezone=UTC"}
    return kwargs


# 异步引擎（业务请求）
async_engine = create_async_engine(settings.database_url, **_engine_kwargs(True))

async_session = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

# 同步引擎（用于Alembic迁移）
sync_engine = create_engine(settings.database_url_sync, **_engine_kwargs(False))

sync_session = sessionmaker(sync_engine, expire_on_commit=False)

Base = declarative_base()


async def get_db():
    async with async_session() as session:
        yield session


# 注册租户行级过滤与写入兜底事件（导入即生效，见 src/tenant/session.py）
from .tenant import session as _tenant_session  # noqa: E402,F401
