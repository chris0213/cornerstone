# -*- coding: utf-8 -*-
"""Prefix 录入校验回归：CIDR 规范化（缩写补零 / host bits 归零 / 非法 422）。"""
import pytest

from src.schemas.prefix import normalize_cidr

pytestmark = pytest.mark.asyncio


def test_normalize_cidr_semantics():
    """规范化语义：缩写补零、host bits 归零、非法抛 ValueError。"""
    assert normalize_cidr("192.168.16/23") == "192.168.16.0/23"      # 缩写补零（生产脏数据形态）
    assert normalize_cidr("192.168/16") == "192.168.0.0/16"
    assert normalize_cidr(" 192.168.1.5/24 ") == "192.168.1.0/24"    # host bits 归零
    assert normalize_cidr("10.0.0.0/8") == "10.0.0.0/8"
    for bad in ["10.0.0.0", "10.0.0.0/33", "10.0.0.0/23.0", "abc/24", ""]:
        try:
            normalize_cidr(bad)
            raise AssertionError(f"{bad!r} 应抛 ValueError")
        except ValueError:
            pass


async def _login(client):
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": "admin", "password": "admin123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_create_prefix_normalizes_abbreviated_network(client, db_session):
    """创建：缩写 network 自动规范化为标准 4 段格式。"""
    headers = await _login(client)
    resp = await client.post(
        "/api/v1/ipam/prefixes/",
        json={"network": "192.168.16/23"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["network"] == "192.168.16.0/23"

    # 清理（验证数据用完即删）
    pid = resp.json()["id"]
    await client.delete(f"/api/v1/ipam/prefixes/{pid}", headers=headers)


@pytest.mark.asyncio
async def test_create_prefix_rejects_invalid_network(client):
    """创建：非法 CIDR → 422，不入库。"""
    headers = await _login(client)
    resp = await client.post(
        "/api/v1/ipam/prefixes/",
        json={"network": "10.0.0.0/40"},
        headers=headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_prefix_normalizes_network(client, db_session):
    """编辑：network 传缩写同样规范化。"""
    headers = await _login(client)
    created = await client.post(
        "/api/v1/ipam/prefixes/",
        json={"network": "10.20.0.0/24"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    pid = created.json()["id"]

    updated = await client.put(
        f"/api/v1/ipam/prefixes/{pid}",
        json={"network": "10.20.1/24"},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["network"] == "10.20.1.0/24"

    await client.delete(f"/api/v1/ipam/prefixes/{pid}", headers=headers)
