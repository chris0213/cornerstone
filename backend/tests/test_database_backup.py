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


@pytest.fixture(autouse=True)
def _reset_create_limiter():
    dbmod._create_last_ts = 0.0
    yield


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


# ==================== B：立即备份（pg_dump）====================

class _FakeProc:
    def __init__(self, outpath, rc=0, err=b""):
        self._out = outpath
        self.returncode = rc
        self._err = err

    async def communicate(self):
        if self.returncode == 0 and self._out:
            with open(self._out, "wb") as f:
                f.write(b"FAKEPGDUMP")
        return (b"", self._err)

    def kill(self):
        pass


def _fake_exec_factory(rc=0, err=b"boom", write_file=True):
    async def _factory(*argv, **kwargs):
        outpath = None
        if "--file" in argv:
            outpath = argv[argv.index("--file") + 1]
        if rc != 0:
            return _FakeProc(None, rc, err)
        return _FakeProc(outpath if write_file else None, 0, err)
    return _factory


@pytest.mark.asyncio
async def test_create_backup_success(client, backup_dir, monkeypatch):
    import asyncio
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec_factory(rc=0))
    h = await _login(client)
    r = await client.post("/api/v1/database-backups/create", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["name"].endswith(".dump")
    assert os.path.isfile(os.path.join(backup_dir, body["name"]))
    # 列表中应出现新文件
    lst = (await client.get("/api/v1/database-backups/files", headers=h)).json()
    assert body["name"] in [f["name"] for f in lst["files"]]


@pytest.mark.asyncio
async def test_create_backup_pgdump_failure(client, backup_dir, monkeypatch):
    import asyncio
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec_factory(rc=1, err=b"auth failed"))
    h = await _login(client)
    r = await client.post("/api/v1/database-backups/create", headers=h)
    assert r.status_code == 500
    assert "auth failed" in r.json()["detail"]


@pytest.mark.asyncio
async def test_create_backup_pgdump_missing(client, backup_dir, monkeypatch):
    async def _raise(*a, **k):
        raise FileNotFoundError("pg_dump")
    monkeypatch.setattr("src.api.database_backup.asyncio.create_subprocess_exec", _raise)
    h = await _login(client)
    r = await client.post("/api/v1/database-backups/create", headers=h)
    assert r.status_code == 500
    assert "postgresql-client" in r.json()["detail"]


# ==================== C：删除旧备份 ====================

@pytest.mark.asyncio
async def test_delete_backup_success(client, backup_dir):
    h = await _login(client)
    name = "cornerstone_www_20261117_033000.dump"
    assert os.path.isfile(os.path.join(backup_dir, name))
    r = await client.delete(f"/api/v1/database-backups/files/{name}", headers=h)
    assert r.status_code == 200
    assert not os.path.exists(os.path.join(backup_dir, name))


@pytest.mark.asyncio
async def test_delete_rejects_badname_and_missing(client, backup_dir):
    h = await _login(client)
    assert (await client.delete("/api/v1/database-backups/files/notes.txt", headers=h)).status_code == 400
    assert (await client.delete("/api/v1/database-backups/files/cornerstone_nope.dump", headers=h)).status_code == 404
