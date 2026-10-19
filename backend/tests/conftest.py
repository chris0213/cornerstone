"""pytest 全局配置：隔离的测试数据库 + 免 lifespan 的 TestClient。

测试库使用临时 SQLite 文件，通过 Base.metadata.create_all 建表（与生产由 Alembic 建表分离），
不触发 app 的 startup_event，因此不会启动依赖 Redis/备份目录的调度器。
"""
import os
import tempfile

# 在导入 app 前注入测试所需环境变量（其余配置由 backend/.env 提供）
# 注意：CREDENTIAL_SECRET_KEY 必须用 .env 中的有效 Fernet key，不要覆盖
os.environ.setdefault("INITIAL_ADMIN_PASSWORD", "admin123")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import src.models  # noqa: F401  # 注册所有模型到 Base.metadata
from src.database import Base, get_db
from src.main import app
from src.services.permission_service import (
    init_default_admin,
    init_permissions,
    init_roles,
)


@pytest_asyncio.fixture
async def test_engine():
    """创建临时文件 SQLite 库并建表。"""
    fd, path = tempfile.mkstemp(suffix="_test.db")
    os.close(fd)
    async_engine = create_async_engine(
        f"sqlite+aiosqlite:///{path}",
        connect_args={"check_same_thread": False},
    )
    # 用同步引擎建表（测试专用，不经过 Alembic）
    sync_engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()

    yield async_engine

    await async_engine.dispose()
    if os.path.exists(path):
        os.unlink(path)


@pytest_asyncio.fixture
async def db_session(test_engine):
    """供测试用例直接造数据的独立会话（与 app 共享同一测试库）。"""
    TestSession = sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with TestSession() as session:
        yield session


@pytest_asyncio.fixture
async def client(test_engine):
    """注入测试库并初始化权限/角色/管理员，返回免 lifespan 的 AsyncClient。"""
    TestSession = sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_db():
        async with TestSession() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    # 初始化基础数据
    async with TestSession() as session:
        await init_permissions(session)
        await init_roles(session)
        await init_default_admin(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
