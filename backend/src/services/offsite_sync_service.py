"""异地备份同步执行服务。

安全基线（本模块所有命令必须遵守）：
- 一律用 argv 列表 + asyncio.create_subprocess_exec，**绝不 shell=True、绝不字符串拼接命令**；
- 用户可控值（host/user/path/endpoint/bucket）先经 offsite_sync_store.validate_config 白名单/格式校验；
- SSH 私钥 / rclone 配置写入临时目录（0600），进程结束即删除，不进命令行 argv（防 ps 泄露）；
- 输出做长度截断，日志与返回均不回显任何密钥内容。

本版认证方式：rclone 用云 access/secret key；rsync/sftp 用 SSH 私钥（不支持口令，避免依赖 sshpass）。
"""
import asyncio
import os
import stat
import tempfile
import time

from src.utils.logger import get_logger

from .offsite_sync_store import validate_config, get_effective_config

logger = get_logger()

# 单次同步/测试的硬超时（秒）
_SYNC_TIMEOUT = 600
_TEST_TIMEOUT = 30


class SyncError(Exception):
    pass


def _mask(text: str) -> str:
    """截断长输出，避免把大段内容塞进日志/返回。"""
    text = text or ""
    return text if len(text) <= 2000 else text[:2000] + "...(截断)"


async def _run(argv: list[str], env: dict | None, timeout: int) -> tuple[int, str, str]:
    """执行 argv（无 shell），返回 (returncode, stdout, stderr)；超时抛 SyncError。"""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        raise SyncError(f"命令执行超时（>{timeout}s）")
    return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def _write_secret_file(tmpdir: str, name: str, content: str) -> str:
    """把敏感内容写入临时目录下的 0600 文件，返回路径。调用方负责清理 tmpdir。"""
    path = os.path.join(tmpdir, name)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content if content.endswith("\n") else content + "\n")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return path


def _normalize_source(config: dict) -> str:
    src = (config.get("source_dir") or "").strip()
    if not src:
        raise SyncError("源目录为空")
    if not os.path.isdir(src):
        raise SyncError(f"源目录不存在或不是目录: {src}")
    return src


def _build_rclone_argv(config: dict, tmpdir: str, *, test: bool) -> tuple[list[str], dict]:
    provider = config.get("rclone_provider") or "minio"
    endpoint = (config.get("rclone_endpoint") or "").strip()
    region = (config.get("rclone_region") or "").strip()
    bucket = (config.get("rclone_bucket") or "").strip()
    prefix = (config.get("rclone_prefix") or "").strip()

    # 用 env 传密钥，避免写入配置文件与 argv
    env = dict(os.environ)
    env["RCLONE_CONFIG_OFFSITE_TYPE"] = "s3"
    # provider 映射：s3→AWS，minio→Minio，oss→Alibaba，cos→TencentCos
    provider_map = {"s3": "AWS", "minio": "Minio", "oss": "Alibaba", "cos": "TencentCos"}
    env["RCLONE_CONFIG_OFFSITE_PROVIDER"] = provider_map.get(provider, "Minio")
    if endpoint:
        env["RCLONE_CONFIG_OFFSITE_ENDPOINT"] = endpoint
    if region:
        env["RCLONE_CONFIG_OFFSITE_REGION"] = region
    env["RCLONE_CONFIG_OFFSITE_ENV_AUTH"] = "false"
    env["RCLONE_CONFIG_OFFSITE_ACCESS_KEY_ID"] = config.get("rclone_access_key_id") or ""
    env["RCLONE_CONFIG_OFFSITE_SECRET_ACCESS_KEY"] = config.get("rclone_secret_access_key") or ""
    # 禁用 rclone 自身的配置搜索，纯靠 env
    env["RCLONE_CONFIG"] = "/dev/null"
    env["RCLONE_NO_STATS"] = "1"

    target = f"offsite:{bucket}" + (f"/{prefix}" if prefix and not test else "")
    if test:
        argv = ["rclone", "lsf", f"offsite:{bucket}", "--max-items", "1"]
    else:
        src = _normalize_source(config)
        argv = ["rclone", "copy", src, target,
                "--max-transfers", "4", "--timeout", "120s", "--contimeout", "30s"]
    return argv, env


def _ssh_common_opts(keyfile: str, port: int) -> list[str]:
    # accept-new：首次连接记录主机指纹（TOFU），后续防中间人；BatchMode 禁交互
    return [
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout=15",
        "-i", keyfile,
    ]


def _build_rsync_argv(config: dict, tmpdir: str, *, test: bool) -> tuple[list[str], dict]:
    host = config["rsync_host"]
    port = int(config.get("rsync_port") or 22)
    user = (config.get("rsync_user") or "").strip()
    remote_path = config["rsync_remote_path"]
    ssh_key = config.get("rsync_ssh_key") or ""
    if not ssh_key:
        raise SyncError("缺少 SSH 私钥")
    keyfile = _write_secret_file(tmpdir, "id_ed25519", ssh_key)

    if test:
        # 用 ssh 执行 true 验证连通与认证
        argv = ["ssh", *_ssh_common_opts(keyfile, port), "-p", str(port), f"{user}@{host}", "true"]
        return argv, dict(os.environ)

    src = _normalize_source(config)
    rsh = "ssh " + " ".join(_ssh_common_opts(keyfile, port)) + f" -p {port}"
    dest = f"{user}@{host}:{remote_path}/"
    argv = ["rsync", "-az", "--rsh", rsh, f"{src}/", dest]
    return argv, dict(os.environ)


def _build_sftp_argv(config: dict, tmpdir: str, *, test: bool) -> tuple[list[str], dict]:
    host = config["sftp_host"]
    port = int(config.get("sftp_port") or 22)
    user = (config.get("sftp_user") or "").strip()
    remote_path = config["sftp_remote_path"]
    ssh_key = config.get("sftp_ssh_key") or ""
    if not ssh_key:
        raise SyncError("缺少 SSH 私钥")
    keyfile = _write_secret_file(tmpdir, "id_ed25519", ssh_key)

    if test:
        argv = ["ssh", *_ssh_common_opts(keyfile, port), "-p", str(port), f"{user}@{host}", "true"]
        return argv, dict(os.environ)

    src = _normalize_source(config)
    # scp 显式枚举源目录内文件，避免 shell glob；目标用 user@host:path（scp 不经远端 shell 解析路径）
    files = [os.path.join(src, f) for f in sorted(os.listdir(src))]
    if not files:
        return [], dict(os.environ)  # 空目录，调用方按 0 文件处理
    dest = f"{user}@{host}:{remote_path}/"
    argv = ["scp", "-r", *_ssh_common_opts(keyfile, port), "-P", str(port), *files, dest]
    return argv, dict(os.environ)


def _build_command(config: dict, tmpdir: str, *, test: bool) -> tuple[list[str], dict]:
    ttype = config["target_type"]
    if ttype == "rclone":
        return _build_rclone_argv(config, tmpdir, test=test)
    if ttype == "rsync":
        return _build_rsync_argv(config, tmpdir, test=test)
    if ttype == "sftp":
        return _build_sftp_argv(config, tmpdir, test=test)
    raise SyncError(f"不支持的同步类型: {ttype}")


async def run_sync(db_config: dict) -> dict:
    """执行一次异地同步。返回 {ok, message, target_type, duration_ms, error}。"""
    start = time.monotonic()
    try:
        config = get_effective_config(db_config)
        config = validate_config(config)  # 执行前再校验一次（存量配置可能已不合规）
    except (ValueError, SyncError) as e:
        return {"ok": False, "message": str(e), "target_type": db_config.get("target_type"),
                "duration_ms": 0, "error": str(e)}

    if not config.get("enabled"):
        return {"ok": False, "message": "异地同步未启用", "target_type": config.get("target_type"),
                "duration_ms": 0, "error": "disabled"}

    tmpdir = tempfile.mkdtemp(prefix="offsite_sync_")
    try:
        argv, env = _build_command(config, tmpdir, test=False)
        if not argv:
            return {"ok": True, "message": "源目录无文件可同步（跳过）",
                    "target_type": config["target_type"],
                    "duration_ms": int((time.monotonic() - start) * 1000), "error": None}
        rc, out, err = await _run(argv, env, _SYNC_TIMEOUT)
        dur = int((time.monotonic() - start) * 1000)
        if rc == 0:
            logger.info(f"[异地同步] 成功 type={config['target_type']} 耗时={dur}ms")
            return {"ok": True, "message": "同步成功", "target_type": config["target_type"],
                    "duration_ms": dur, "error": None}
        msg = _mask(err or out)
        logger.warning(f"[异地同步] 失败 type={config['target_type']} rc={rc}: {msg}")
        return {"ok": False, "message": f"同步失败（rc={rc}）", "target_type": config["target_type"],
                "duration_ms": dur, "error": msg}
    except SyncError as e:
        return {"ok": False, "message": str(e), "target_type": config.get("target_type"),
                "duration_ms": int((time.monotonic() - start) * 1000), "error": str(e)}
    except Exception as e:
        logger.error(f"[异地同步] 异常: {e}", exc_info=True)
        return {"ok": False, "message": "同步异常", "target_type": config.get("target_type"),
                "duration_ms": int((time.monotonic() - start) * 1000), "error": _mask(str(e))}
    finally:
        # 清理临时密钥/配置文件
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


async def test_connection(db_config: dict) -> dict:
    """连通+认证测试（不传输文件）。返回 {ok, message, error}。"""
    try:
        config = get_effective_config(db_config)
        config = validate_config(config)
    except (ValueError, SyncError) as e:
        return {"ok": False, "message": str(e), "error": str(e)}

    tmpdir = tempfile.mkdtemp(prefix="offsite_test_")
    try:
        argv, env = _build_command(config, tmpdir, test=True)
        rc, out, err = await _run(argv, env, _TEST_TIMEOUT)
        if rc == 0:
            return {"ok": True, "message": f"{config['target_type']} 连通且认证成功", "error": None}
        return {"ok": False, "message": "连接或认证失败", "error": _mask(err or out)}
    except SyncError as e:
        return {"ok": False, "message": str(e), "error": str(e)}
    except Exception as e:
        return {"ok": False, "message": "测试异常", "error": _mask(str(e))}
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
