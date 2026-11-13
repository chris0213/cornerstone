"""头像上传/读取回归测试。

覆盖：
- 上传权限：本人 200、有 users:write 可改他人、其他 403、未登录 401
- 入参校验：超过 200KB → 413，非图片 → 400
- 服务端缩放：输出 256x256 WEBP
- 读取：ETag / Last-Modified / If-None-Match 304
- 版本递增与 /auth/me 返回带版本号的 URL
"""
import io

import pytest
from PIL import Image

pytestmark = pytest.mark.asyncio


async def login(client, username="admin", password="admin123") -> dict:
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _role_id(client, admin_auth, name: str) -> int:
    resp = await client.get("/api/v1/users/roles/", headers=admin_auth)
    assert resp.status_code == 200, resp.text
    for role in resp.json():
        if role["name"] == name:
            return role["id"]
    raise AssertionError(f"role {name} not found")


async def _create_user(client, admin_auth, username: str, role_name: str) -> tuple[int, dict]:
    role_id = await _role_id(client, admin_auth, role_name)
    resp = await client.post(
        "/api/v1/users",
        json={
            "username": username,
            "email": f"{username}@test.com",
            "password": "Passw0rd123",
            "role_id": role_id,
        },
        headers=admin_auth,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"], await login(client, username, "Passw0rd123")


async def _me_id(client, auth) -> int:
    resp = await client.get("/api/v1/auth/me", headers=auth)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _png(width=64, height=64, color=(120, 80, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, "PNG")
    return buf.getvalue()


async def test_upload_own_avatar_and_read(client):
    admin = await login(client)
    admin_id = await _me_id(client, admin)

    resp = await client.post(
        f"/api/v1/users/{admin_id}/avatar",
        files={"avatar": ("me.png", _png(), "image/png")},
        headers=admin,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["version"] == 1
    assert body["avatar_url"] == f"/api/v1/users/{admin_id}/avatar?v=1"

    # 读取：输出被缩放为 256x256 WEBP
    got = await client.get(f"/api/v1/users/{admin_id}/avatar")
    assert got.status_code == 200
    assert got.headers["content-type"].startswith("image/webp")
    assert got.headers["etag"]
    assert got.headers["last-modified"]
    image = Image.open(io.BytesIO(got.content))
    assert image.size == (256, 256)

    # /auth/me 返回带版本号的 URL
    me = await client.get("/api/v1/auth/me", headers=admin)
    assert me.json()["avatar"] == f"/api/v1/users/{admin_id}/avatar?v=1"


async def test_get_avatar_supports_304(client):
    admin = await login(client)
    admin_id = await _me_id(client, admin)
    await client.post(
        f"/api/v1/users/{admin_id}/avatar",
        files={"avatar": ("me.png", _png(), "image/png")},
        headers=admin,
    )

    first = await client.get(f"/api/v1/users/{admin_id}/avatar")
    etag = first.headers["etag"]
    last_modified = first.headers["last-modified"]

    by_etag = await client.get(
        f"/api/v1/users/{admin_id}/avatar", headers={"If-None-Match": etag}
    )
    assert by_etag.status_code == 304
    assert by_etag.content == b""

    by_weak_etag = await client.get(
        f"/api/v1/users/{admin_id}/avatar", headers={"If-None-Match": f"W/{etag}"}
    )
    assert by_weak_etag.status_code == 304

    by_time = await client.get(
        f"/api/v1/users/{admin_id}/avatar", headers={"If-Modified-Since": last_modified}
    )
    assert by_time.status_code == 304


async def test_avatar_version_increments(client):
    admin = await login(client)
    admin_id = await _me_id(client, admin)

    first = await client.post(
        f"/api/v1/users/{admin_id}/avatar",
        files={"avatar": ("a.png", _png(color=(10, 20, 30)), "image/png")},
        headers=admin,
    )
    second = await client.post(
        f"/api/v1/users/{admin_id}/avatar",
        files={"avatar": ("b.png", _png(color=(200, 30, 40)), "image/png")},
        headers=admin,
    )
    assert first.json()["version"] == 1
    assert second.json()["version"] == 2
    assert second.json()["avatar_url"].endswith("?v=2")
    assert first.json()["avatar_url"] != second.json()["avatar_url"]


async def test_upload_permissions(client):
    admin = await login(client)
    admin_id = await _me_id(client, admin)
    engineer_id, engineer = await _create_user(client, admin, "eng_avatar", "engineer")
    viewer_id, viewer = await _create_user(client, admin, "view_avatar", "viewer")

    # 未登录 401
    anon = await client.post(
        f"/api/v1/users/{engineer_id}/avatar",
        files={"avatar": ("a.png", _png(), "image/png")},
    )
    assert anon.status_code == 401

    # 非本人且无 users:write → 403
    denied_eng = await client.post(
        f"/api/v1/users/{viewer_id}/avatar",
        files={"avatar": ("a.png", _png(), "image/png")},
        headers=engineer,
    )
    assert denied_eng.status_code == 403
    denied_view = await client.post(
        f"/api/v1/users/{admin_id}/avatar",
        files={"avatar": ("a.png", _png(), "image/png")},
        headers=viewer,
    )
    assert denied_view.status_code == 403

    # viewer 本人可改自己
    own_view = await client.post(
        f"/api/v1/users/{viewer_id}/avatar",
        files={"avatar": ("a.png", _png(), "image/png")},
        headers=viewer,
    )
    assert own_view.status_code == 200

    # admin（users:write）可改他人
    by_admin = await client.post(
        f"/api/v1/users/{engineer_id}/avatar",
        files={"avatar": ("a.png", _png(), "image/png")},
        headers=admin,
    )
    assert by_admin.status_code == 200


async def test_upload_rejects_bad_input(client):
    admin = await login(client)
    admin_id = await _me_id(client, admin)

    too_big = await client.post(
        f"/api/v1/users/{admin_id}/avatar",
        files={"avatar": ("big.png", b"a" * (200 * 1024 + 1), "image/png")},
        headers=admin,
    )
    assert too_big.status_code == 413

    not_image = await client.post(
        f"/api/v1/users/{admin_id}/avatar",
        files={"avatar": ("x.png", b"not an image", "image/png")},
        headers=admin,
    )
    assert not_image.status_code == 400
