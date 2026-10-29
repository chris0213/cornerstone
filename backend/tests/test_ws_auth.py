# -*- coding: utf-8 -*-
"""WS 扫描进度鉴权回归测试。

背景：安全加固二期在 get_ws_user 中引入了错误的相对导入
（`from .utils.ip_whitelist` 解析为不存在的 src.api.utils），
由于是函数内局部导入，所有 WS 连接在鉴权第一步即抛 ModuleNotFoundError，
前端收到「认证失败」后扫描进度全部丢失，且 HTTP 侧测试无法覆盖。
"""
from types import SimpleNamespace

import pytest
from fastapi import WebSocketException

from src.api.dependencies import get_ws_user

pytestmark = pytest.mark.asyncio


async def _login(client):
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": "admin", "password": "admin123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _fake_ws(token):
    """仅实现 get_ws_user 用到的属性：query_params / client.host / headers。"""
    return SimpleNamespace(
        query_params={"token": token} if token else {},
        client=SimpleNamespace(host="127.0.0.1"),
        headers={},
    )


async def test_get_ws_user_valid_token(client, db_session):
    """有效 token（含未撤销会话）应通过 WS 鉴权并返回 admin 用户。"""
    token = await _login(client)
    user = await get_ws_user(_fake_ws(token), db_session)
    assert user.username == "admin"


async def test_get_ws_user_missing_token(client, db_session):
    """缺少 token 应抛 WebSocketException，而非静默放行。"""
    with pytest.raises(WebSocketException):
        await get_ws_user(_fake_ws(None), db_session)
