"""登录限流/锁定（login_throttle）+ 验证码一次性回归。

覆盖：
- 用户名维度：5 次失败锁 15 分钟（423），成功登录重置
- IP 维度：10 分钟 20 次失败限流（429），换用户名同样拦截（密码喷洒防护）
- 验证码：一次性（校验通过即消费）、错误验证码不计入用户名锁定
- 恒时校验：用户不存在返回 401（不泄露存在性）

说明：限流存储优先 Redis、不可用回退进程内存；本文件统一钉在内存模式验证语义
（详见 _memory_only_mode fixture），验证码流程用 FakeRedis 隔离真实 Redis。
"""
import pytest

from src.api.auth import get_redis
from src.models import Role, User
from src.services.permission_service import pwd_context
from src.utils.login_throttle import reset_login_failures
import src.utils.login_throttle as lt

pytestmark = pytest.mark.asyncio

THROTTLE_USER = "qa_thr"
IP = "127.0.0.1"


@pytest.fixture(autouse=True)
def _memory_only_mode(monkeypatch):
    """强制限流走进程内存模式。

    全量回归时其他用例的并发会让测试机 Redis 连接抖动，触发熔断后计数
    分裂在 Redis 与内存两侧，导致阈值断言不稳定。本文件验证的是限流
    语义（阈值/维度/重置），与存储后端无关，故统一钉在内存模式。
    """
    monkeypatch.setattr(lt, "_get_redis", lambda: None)
    yield
    # 清理全局内存计数，避免影响其他用例
    lt._memory_user_failures.clear()
    lt._memory_ip_failures.clear()
    lt._redis_down_until = 0.0


class FakeRedis:
    """极简异步 Redis 假实现（get/setex/delete），供验证码流程测试。"""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.last_captcha: str | None = None  # 最近一次生成的验证码答案

    async def get(self, key):
        return self.store.get(key)

    async def setex(self, key, ttl, value):
        self.store[key] = str(value)
        if key.startswith("captcha:"):
            self.last_captcha = str(value)

    async def delete(self, *keys):
        for k in keys:
            self.store.pop(k, None)


async def _make_engineer(db, username: str):
    role = (await db.execute(select_role())).scalar_one()
    db.add(User(
        username=username, display_name=username, email=f"{username}@example.com",
        hashed_password=pwd_context.hash("RightPass123"), role_id=role.id, is_active=True,
    ))
    await db.commit()


def select_role():
    from sqlalchemy import select
    from src.models import Role
    return select(Role).where(Role.name == "engineer")


def _token_form(username: str, password: str):
    return {"username": username, "password": password}


async def _login(client, username: str, password: str):
    return await client.post(
        "/api/v1/auth/token",
        data=_token_form(username, password),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


async def test_username_lock_after_5_failures(client, db_session):
    """5 次失败后 423 锁定；提示不泄露账号存在性"""
    await _make_engineer(db_session, THROTTLE_USER)
    try:
        for _ in range(5):
            resp = await _login(client, THROTTLE_USER, "WrongPass999")
            assert resp.status_code == 401, resp.text

        resp = await _login(client, THROTTLE_USER, "WrongPass999")
        assert resp.status_code == 423, resp.text

        # 锁定优先于密码校验：即使密码正确也拒绝
        resp = await _login(client, THROTTLE_USER, "RightPass123")
        assert resp.status_code == 423, resp.text
    finally:
        await reset_login_failures(THROTTLE_USER, IP)


async def test_success_resets_failure_count(client, db_session):
    """成功登录重置计数：4 次失败 + 成功 + 4 次失败不应锁定"""
    await _make_engineer(db_session, THROTTLE_USER)
    try:
        for _ in range(4):
            assert (await _login(client, THROTTLE_USER, "WrongPass999")).status_code == 401
        assert (await _login(client, THROTTLE_USER, "RightPass123")).status_code == 200

        for _ in range(4):
            assert (await _login(client, THROTTLE_USER, "WrongPass999")).status_code == 401
        # 仍未达到新的 5 次，不应锁定
        resp = await _login(client, THROTTLE_USER, "WrongPass999")
        assert resp.status_code == 401, resp.text
    finally:
        await reset_login_failures(THROTTLE_USER, IP)


async def test_ip_rate_limit_blocks_password_spraying(client, db_session):
    """IP 维度：同一 IP 累计 20 次失败后 429，换用户名仍被拦（密码喷洒防护）"""
    await _make_engineer(db_session, THROTTLE_USER)
    try:
        # 用不存在的用户名刷失败（同时验证恒时路径 401）
        for i in range(20):
            resp = await _login(client, f"nosuch_user_{i}", "Whatever123")
            assert resp.status_code == 401, resp.text

        # 换真实用户名+正确密码也被 IP 限流拦截
        resp = await _login(client, THROTTLE_USER, "RightPass123")
        assert resp.status_code == 429, resp.text
    finally:
        # 清理 IP 与用户名计数，避免污染同进程其他用例
        await reset_login_failures(None, IP)
        await reset_login_failures(THROTTLE_USER, IP)


async def _captcha_login(client, fake: FakeRedis, username: str, password: str, code: str = None):
    """取验证码（走 fake redis，可直接读到答案）→ 登录"""
    resp = await client.get("/api/v1/auth/captcha")
    assert resp.status_code == 200, resp.text
    captcha_id = resp.headers["X-Captcha-ID"]
    return await client.post("/api/v1/auth/login-with-captcha", json={
        "username": username,
        "password": password,
        "captcha_id": captcha_id,
        "captcha_code": code if code is not None else (fake.last_captcha or "xxxx"),
    })


async def test_captcha_one_time_and_not_counting_username(client, db_session):
    """验证码一次性：校验通过即消费；错误验证码不计用户名锁定（防恶意锁人）"""
    fake = FakeRedis()
    from src.main import app
    app.dependency_overrides[get_redis] = lambda: fake
    try:
        await _make_engineer(db_session, THROTTLE_USER)

        # 错误验证码 ×6：始终 400，且不得锁定用户名（密码正确仍可登录）
        for _ in range(6):
            resp = await _captcha_login(client, fake, THROTTLE_USER, "RightPass123", code="wrong")
            assert resp.status_code == 400, resp.text

        resp = await _login(client, THROTTLE_USER, "RightPass123")
        assert resp.status_code == 200, f"错误验证码不应锁定用户名: {resp.text}"

        # 正确验证码登录成功后：同一 captcha_id 复用 → 400 已过期（一次性）
        resp = await client.get("/api/v1/auth/captcha")
        captcha_id = resp.headers["X-Captcha-ID"]
        assert fake.last_captcha, "验证码应已写入 redis"
        resp = await client.post("/api/v1/auth/login-with-captcha", json={
            "username": THROTTLE_USER, "password": "RightPass123",
            "captcha_id": captcha_id, "captcha_code": fake.last_captcha,
        })
        assert resp.status_code == 200, resp.text

        resp = await client.post("/api/v1/auth/login-with-captcha", json={
            "username": THROTTLE_USER, "password": "RightPass123",
            "captcha_id": captcha_id, "captcha_code": fake.last_captcha,
        })
        assert resp.status_code == 400, resp.text
        assert "过期" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await reset_login_failures(THROTTLE_USER, IP)


async def test_nonexistent_user_returns_401(client, db_session):
    """用户不存在与密码错误同文案 401，不泄露账号存在性"""
    resp = await _login(client, "no_such_user_xyz", "Whatever123")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "用户名或密码错误"
