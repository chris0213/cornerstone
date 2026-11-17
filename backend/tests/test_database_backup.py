"""数据库备份文件列表/下载 API 测试。"""
import os
import time

import pytest

import src.api.database_backup as dbmod


async def _login(client, username="admin", password="admin123"):
    resp = await client.post("/api/v1/auth/token",
                             data={"username": username, "password": password},
                             headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def backup_dir(tmp_path, monkeypatch):
    # 造一个合法 dump + 一个非法文件
    good = tmp_path / "cornerstone_www_20261117_033000.dump"
    good.write_bytes(b"DUMPDATA123")
    (tmp_path / "notes.txt").write_text("ignore me")
    monkeypatch.setattr(dbmod, "BACKUP_DIR", str(tmp_path))
    return str(tmp_path)


@pytest.mark.asyncio
async def test_list_files_only_dumps(client, backup_dir):
    h = await _login(client)
    r = await client.get("/api/v1/database-backups/files", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    names = [f["name"] for f in body["files"]]
    assert names == ["cornerstone_www_20261117_033000.dump"]
    assert body["files"][0]["size_bytes"] == len("DUMPDATA123")


@pytest.mark.asyncio
async def test_download_valid(client, backup_dir):
    h = await _login(client)
    r = await client.get("/api/v1/database-backups/files/cornerstone_www_20261117_033000.dump/download", headers=h)
    assert r.status_code == 200
    assert r.content == b"DUMPDATA123"
    assert "attachment" in r.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_download_rejects_traversal_and_badname(client, backup_dir):
    h = await _login(client)
    # ../ 穿越
    r = await client.get("/api/v1/database-backups/files/..%2F..%2Fetc%2Fpasswd/download", headers=h)
    assert r.status_code in (400, 404)
    # 非法文件名（非 dump 命名）
    r2 = await client.get("/api/v1/database-backups/files/notes.txt/download", headers=h)
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_list_missing_dir(client, monkeypatch, tmp_path):
    monkeypatch.setattr(dbmod, "BACKUP_DIR", str(tmp_path / "nope"))
    h = await _login(client)
    r = await client.get("/api/v1/database-backups/files", headers=h)
    assert r.status_code == 200
    assert r.json()["exists"] is False


@pytest.mark.asyncio
async def test_requires_super_admin(client, db_session, backup_dir):
    from src.models import User, Role
    from src.services.permission_service import pwd_context
    from sqlalchemy import select
    role = (await db_session.execute(select(Role).where(Role.name == "viewer"))).scalar_one()
    u = User(username="viewer_db", display_name="viewer_db", email="v@e.com",
             hashed_password=pwd_context.hash("Passw0rd!"), role_id=role.id, is_active=True)
    db_session.add(u)
    await db_session.commit()
    resp = await client.post("/api/v1/auth/token",
                             data={"username": "viewer_db", "password": "Passw0rd!"},
                             headers={"Content-Type": "application/x-www-form-urlencoded"})
    tok = resp.json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert (await client.get("/api/v1/database-backups/files", headers=h)).status_code == 403
