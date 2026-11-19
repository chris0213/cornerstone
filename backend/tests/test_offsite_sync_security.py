"""异地备份同步安全测试。

覆盖：源目录白名单（防任意目录外泄）、远程路径/主机/类型校验（防命令注入与非法参数）、
敏感字段加密与脱敏（GET 不回明文）、命令构造为 argv 列表（无 shell）、API 校验与状态。
不实际执行 rclone/rsync/scp（本机无二进制），只验证构造与拦截逻辑。
"""
import json

import pytest
from sqlalchemy import select

from src.models.setting import Setting
from src.services.offsite_sync_store import (
    validate_config, mask_config_for_display, encrypt_config, decrypt_config,
    OFFSITE_SYNC_KEY,
)
from src.services.offsite_sync_service import _build_command, run_sync, SyncError
import src.services.offsite_sync_service as o


# ==================== 校验层：拒绝外泄与注入 ====================

def test_validate_rejects_arbitrary_source_dir():
    """源目录必须落在白名单内，否则等于把任意目录外传到攻击者主机。"""
    for bad in ["/etc", "/root/.ssh", "/opt/cornerstone/backups/../../..", "/"]:
        with pytest.raises(ValueError):
            validate_config({"target_type": "rclone", "enabled": True, "source_dir": bad,
                             "rclone_bucket": "b", "rclone_access_key_id": "k",
                             "rclone_secret_access_key": "s"})


def test_validate_rejects_path_traversal_in_remote_path():
    with pytest.raises(ValueError):
        validate_config({"target_type": "rsync", "enabled": True,
                         "source_dir": "/opt/cornerstone/db_backups",
                         "rsync_host": "backup.example.com", "rsync_port": 22,
                         "rsync_user": "u", "rsync_remote_path": "../etc",
                         "rsync_ssh_key": "key"})


def test_validate_rejects_shell_metachars_in_remote_path():
    """含 ; | & $ ` 空格 等 shell 元字符的路径必须被拒（即便走 argv 也应拒绝异常输入）。"""
    for bad in ["a; rm -rf /", "a|nc evil", "a && evil", "a$(id)", "a`x`", "a b"]:
        with pytest.raises(ValueError):
            validate_config({"target_type": "rsync", "enabled": True,
                             "source_dir": "/opt/cornerstone/db_backups",
                             "rsync_host": "backup.example.com", "rsync_port": 22,
                             "rsync_user": "u", "rsync_remote_path": bad,
                             "rsync_ssh_key": "key"})


def test_validate_rejects_bad_host_and_port_and_type():
    with pytest.raises(ValueError):
        validate_config({"target_type": "rsync", "enabled": True,
                         "source_dir": "/opt/cornerstone/db_backups",
                         "rsync_host": "bad host;evil", "rsync_port": 22,
                         "rsync_user": "u", "rsync_remote_path": "backup",
                         "rsync_ssh_key": "key"})
    with pytest.raises(ValueError):
        validate_config({"target_type": "rsync", "enabled": True,
                         "source_dir": "/opt/cornerstone/db_backups",
                         "rsync_host": "backup.example.com", "rsync_port": 99999,
                         "rsync_user": "u", "rsync_remote_path": "backup",
                         "rsync_ssh_key": "key"})
    with pytest.raises(ValueError):
        validate_config({"target_type": "ftp", "enabled": False,
                         "source_dir": "/opt/cornerstone/db_backups"})


def test_validate_requires_fields_when_enabled():
    """启用时缺必填项要报错；关闭时允许草稿保存。"""
    with pytest.raises(ValueError):
        validate_config({"target_type": "rclone", "enabled": True,
                         "source_dir": "/opt/cornerstone/db_backups"})  # 缺 bucket/key
    # 关闭时不校验目标细节
    ok = validate_config({"target_type": "rclone", "enabled": False,
                          "source_dir": "/opt/cornerstone/db_backups"})
    assert ok["target_type"] == "rclone"


# ==================== 加密与脱敏 ====================

def test_encrypt_decrypt_roundtrip():
    cfg = {"rclone_access_key_id": "AKID1234567890", "rclone_secret_access_key": "SECRETVALUE",
           "rsync_ssh_key": "-----BEGIN KEY-----"}
    enc = encrypt_config(cfg)
    assert not enc["rclone_access_key_id"].startswith("AKID")
    assert enc["rclone_access_key_id"].startswith("enc:")
    dec = decrypt_config(enc)
    assert dec["rclone_access_key_id"] == "AKID1234567890"
    assert dec["rsync_ssh_key"] == "-----BEGIN KEY-----"


def test_mask_never_leaks_plaintext():
    enc = encrypt_config({"rclone_access_key_id": "AKIDABCDEFGHIJKLMNOP",
                          "rclone_secret_access_key": "SECRETABCDEFGHIJKLMNOP"})
    enc["target_type"] = "rclone"
    enc["enabled"] = True
    masked = mask_config_for_display(enc)
    blob = json.dumps(masked)
    assert "AKIDABCDEFGHIJKLMNOP" not in blob
    assert "SECRETABCDEFGHIJKLMNOP" not in blob
    assert "enc:" not in blob
    # 只回 has_xxx + 尾号
    assert masked["has_rclone_access_key_id"] is True
    assert masked["rclone_access_key_id_tail"] == "JKLMNOP"[-8:] or len(masked["rclone_access_key_id_tail"]) <= 8


# ==================== 命令构造：argv 列表、无 shell ====================

def test_build_command_returns_argv_list_rclone(monkeypatch, tmp_path):
    import tempfile
    src = str(tmp_path)
    monkeypatch.setenv("OFFSITE_SYNC_ALLOWED_DIRS", src)
    cfg = validate_config({"target_type": "rclone", "enabled": True,
                           "source_dir": src,
                           "rclone_provider": "minio", "rclone_endpoint": "https://minio.local",
                           "rclone_bucket": "bk", "rclone_prefix": "cornerstone-db",
                           "rclone_access_key_id": "k", "rclone_secret_access_key": "s"})
    with tempfile.TemporaryDirectory() as td:
        argv, env = _build_command(cfg, td, test=False)
    assert isinstance(argv, list)
    assert argv[0] == "rclone"
    # 密钥不在 argv（走 env）
    assert "k" not in argv and "s" not in argv
    assert env["RCLONE_CONFIG_OFFSITE_ACCESS_KEY_ID"] == "k"
    # 没有任何元素含 shell 元字符拼接
    assert not any(any(c in str(a) for c in [";", "&&", "|"]) for a in argv)


def test_build_command_rsync_keyfile_not_in_argv_value(monkeypatch, tmp_path):
    import tempfile
    src = str(tmp_path)
    monkeypatch.setenv("OFFSITE_SYNC_ALLOWED_DIRS", src)
    cfg = validate_config({"target_type": "rsync", "enabled": True,
                           "source_dir": src,
                           "rsync_host": "backup.example.com", "rsync_port": 22,
                           "rsync_user": "op", "rsync_remote_path": "db_backups",
                           "rsync_ssh_key": "PRIVKEYDATA"})
    with tempfile.TemporaryDirectory() as td:
        argv, env = _build_command(cfg, td, test=False)
    assert argv[0] == "rsync"
    # 私钥内容绝不出现在 argv
    assert "PRIVKEYDATA" not in " ".join(argv)
    # 主机/路径作为独立 argv 元素，且不含 shell 元字符
    dest = [a for a in argv if "backup.example.com" in a]
    assert dest and not any(c in dest[0] for c in [";", "&&", "$", "`"])


@pytest.mark.asyncio
async def test_run_sync_disabled_short_circuits():
    """未启用时直接返回，不执行任何命令。"""
    res = await run_sync({"enabled": False, "target_type": "rclone",
                          "source_dir": "/opt/cornerstone/db_backups"})
    assert res["ok"] is False
    assert res["error"] == "disabled"


@pytest.mark.asyncio
async def test_run_sync_missing_source_dir_is_error_not_shell():
    """源目录不在白名单 → 校验兜底返回 ok=False，不抛未捕获异常、不执行命令。"""
    res = await run_sync({"enabled": True, "target_type": "rsync",
                          "source_dir": "/opt/cornerstone/db_backups_nonexist",
                          "rsync_host": "backup.example.com", "rsync_port": 22,
                          "rsync_user": "op", "rsync_remote_path": "db",
                          "rsync_ssh_key": "PRIVKEY"})
    assert res["ok"] is False
    assert res["error"] is not None  # 被校验/兜底捕获，返回结构化失败而非抛异常


# ==================== API 层 ====================

async def _login(client, username="admin", password="admin123"):
    resp = await client.post("/api/v1/auth/token",
                             data={"username": username, "password": password},
                             headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture(autouse=True)
async def clean_offsite(db_session):
    yield
    from sqlalchemy import delete
    await db_session.execute(delete(Setting).where(Setting.key == OFFSITE_SYNC_KEY))
    await db_session.commit()


@pytest.mark.asyncio
async def test_api_put_rejects_bad_source_dir(client, db_session):
    h = await _login(client)
    resp = await client.put("/api/v1/offsite-sync/config", json={
        "enabled": True, "target_type": "rclone", "source_dir": "/etc",
        "rclone_bucket": "b", "rclone_access_key_id": "k", "rclone_secret_access_key": "s",
    }, headers=h)
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_api_put_then_get_masks_secret(client, db_session):
    h = await _login(client)
    resp = await client.put("/api/v1/offsite-sync/config", json={
        "enabled": True, "target_type": "rclone",
        "source_dir": "/opt/cornerstone/db_backups",
        "rclone_provider": "minio", "rclone_endpoint": "https://minio.local",
        "rclone_bucket": "bk", "rclone_prefix": "cornerstone-db",
        "rclone_access_key_id": "AKIDTOPSECRET", "rclone_secret_access_key": "SECRETTOPSECRET",
    }, headers=h)
    assert resp.status_code == 200, resp.text
    body = resp.text
    assert "AKIDTOPSECRET" not in body and "SECRETTOPSECRET" not in body and "enc:" not in body

    got = await client.get("/api/v1/offsite-sync/config", headers=h)
    assert got.status_code == 200
    g = got.json()
    assert g["has_rclone_access_key_id"] is True
    assert "AKIDTOPSECRET" not in got.text

    # 库中确为密文
    setting = (await db_session.execute(select(Setting).where(Setting.key == OFFSITE_SYNC_KEY))).scalars().first()
    assert setting is not None
    assert "AKIDTOPSECRET" not in setting.value


@pytest.mark.asyncio
async def test_api_status_reports_tools(client, db_session):
    h = await _login(client)
    resp = await client.get("/api/v1/offsite-sync/status", headers=h)
    assert resp.status_code == 200
    body = resp.json()
    assert "tools" in body and "last_sync" in body


# ==================== 落地完整性校验（B） ====================

@pytest.mark.asyncio
async def test_rclone_landing_check_pass(monkeypatch, tmp_path):
    """rclone 传输成功后追加 rclone check，一致则 verify=passed。"""
    src = tmp_path / "bk"; src.mkdir()
    (src / "cornerstone_h_1__auto.dump").write_bytes(b"abc")
    monkeypatch.setenv("OFFSITE_SYNC_ALLOWED_DIRS", str(src))
    calls = []
    async def fake_run(argv, env, timeout):
        calls.append(argv[:2]); return (0, "", "")
    monkeypatch.setattr(o, "_run", fake_run)
    res = await o.run_sync({"enabled": True, "target_type": "rclone", "source_dir": str(src),
                            "rclone_bucket": "bk", "rclone_access_key_id": "k",
                            "rclone_secret_access_key": "s"})
    assert res["ok"] is True and res["verify"] == "passed"
    assert ["rclone", "check"] in calls


@pytest.mark.asyncio
async def test_rclone_landing_check_mismatch(monkeypatch, tmp_path):
    """rclone check 不一致 → 整体判失败、verify=mismatch。"""
    src = tmp_path / "bk"; src.mkdir()
    (src / "cornerstone_h_1__auto.dump").write_bytes(b"abc")
    monkeypatch.setenv("OFFSITE_SYNC_ALLOWED_DIRS", str(src))
    async def fake_run(argv, env, timeout):
        if argv[:2] == ["rclone", "check"]:
            return (1, "", "ERROR : cornerstone_h_1__auto.dump: sizes differ")
        return (0, "", "")
    monkeypatch.setattr(o, "_run", fake_run)
    res = await o.run_sync({"enabled": True, "target_type": "rclone", "source_dir": str(src),
                            "rclone_bucket": "bk", "rclone_access_key_id": "k",
                            "rclone_secret_access_key": "s"})
    assert res["ok"] is False and res["verify"] == "mismatch"


@pytest.mark.asyncio
async def test_rsync_landing_relies_on_protocol_single_call(monkeypatch, tmp_path):
    """rsync 依赖协议内置一致性，不额外发起校验命令（仅一次 rsync）。"""
    src = tmp_path / "bk"; src.mkdir()
    (src / "cornerstone_h_1__auto.dump").write_bytes(b"abc")
    monkeypatch.setenv("OFFSITE_SYNC_ALLOWED_DIRS", str(src))
    seen = []
    async def fake_run(argv, env, timeout):
        seen.append(argv[0]); return (0, "", "")
    monkeypatch.setattr(o, "_run", fake_run)
    res = await o.run_sync({"enabled": True, "target_type": "rsync", "source_dir": str(src),
                            "rsync_host": "b.example.com", "rsync_port": 22, "rsync_user": "op",
                            "rsync_remote_path": "db", "rsync_ssh_key": "PRIVKEY"})
    assert res["ok"] is True and res["verify"] == "passed"
    assert seen == ["rsync"]


@pytest.mark.asyncio
async def test_sftp_landing_size_match_pass(monkeypatch, tmp_path):
    """scp 无内置校验：ssh stat 比对本地/远端 size 一致则通过。"""
    src = tmp_path / "bk"; src.mkdir()
    (src / "a.dump").write_bytes(b"123")
    (src / "b.dump").write_bytes(b"45678")
    monkeypatch.setenv("OFFSITE_SYNC_ALLOWED_DIRS", str(src))
    async def fake_run(argv, env, timeout):
        if argv[0] == "ssh" and "stat" in argv:
            return (0, "3 /remote/a.dump\n5 /remote/b.dump\n", "")
        return (0, "", "")
    monkeypatch.setattr(o, "_run", fake_run)
    res = await o.run_sync({"enabled": True, "target_type": "sftp", "source_dir": str(src),
                            "sftp_host": "b.example.com", "sftp_port": 22, "sftp_user": "op",
                            "sftp_remote_path": "remote", "sftp_ssh_key": "PRIVKEY"})
    assert res["ok"] is True and res["verify"] == "passed"


@pytest.mark.asyncio
async def test_sftp_landing_size_mismatch_fail(monkeypatch, tmp_path):
    """远端 size 与本地不符 → 落地校验失败。"""
    src = tmp_path / "bk"; src.mkdir()
    (src / "a.dump").write_bytes(b"123")
    (src / "b.dump").write_bytes(b"45678")
    monkeypatch.setenv("OFFSITE_SYNC_ALLOWED_DIRS", str(src))
    async def fake_run(argv, env, timeout):
        if argv[0] == "ssh" and "stat" in argv:
            return (0, "3 /remote/a.dump\n4 /remote/b.dump\n", "")
        return (0, "", "")
    monkeypatch.setattr(o, "_run", fake_run)
    res = await o.run_sync({"enabled": True, "target_type": "sftp", "source_dir": str(src),
                            "sftp_host": "b.example.com", "sftp_port": 22, "sftp_user": "op",
                            "sftp_remote_path": "remote", "sftp_ssh_key": "PRIVKEY"})
    assert res["ok"] is False and res["verify"] == "mismatch"
