import hashlib
import difflib
import os
import sys
import time
import asyncio
import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger("cornerstone")

# Netmiko设备类型映射
VENDOR_MAP = {
    "cisco_ios": "cisco_ios",
    "cisco_nxos": "cisco_nxos",
    "huawei_vrp": "huawei_vrp",
    "h3c": "hp_comware",
    "juniper": "juniper_junos",
    "fortinet": "fortinet",
    "linux": "linux",
    "ruijie": "ruijie_os",
    "ruijie_os": "ruijie_os",
    "hillstone": "hillstone_networks",
    "aruba": "aruba_os",
}

# telnet 凭证对应的 netmiko device_type（测试连接/采集/还原三条路径共用）。
# netmiko 4.x 未提供 telnet 驱动的厂商不在表内，保持原 SSH 类型。
TELNET_DEVICE_TYPE_MAP = {
    "cisco_ios": "cisco_ios_telnet",
    "cisco_nxos": "cisco_nxos_telnet",
    "huawei_vrp": "huawei_telnet",  # 注意：华为 VRP 的 telnet 驱动名为 huawei_telnet
    "hp_comware": "hp_comware_telnet",
    "juniper_junos": "juniper_junos_telnet",
    "ruijie_os": "ruijie_os_telnet",
}

# 每个厂商的采集命令
BACKUP_COMMANDS = {
    "cisco_ios": "show running-config",
    "cisco_nxos": "show running-config",
    "huawei_vrp": "display current-configuration",
    "h3c": "display current-configuration",
    "juniper": "show configuration",
    "fortinet": "show full-configuration",
    "linux": "ip addr show && ip route show && cat /etc/hostname && cat /etc/resolv.conf",
    "ruijie": "show running-config",
    "ruijie_os": "show running-config",
    "hillstone": "show configuration",
    "aruba": "show running-config",
}

# 每个厂商的测试命令（轻量级，仅用于连通性测试）
TEST_COMMANDS = {
    "cisco_ios": "show version | include Version",
    "cisco_nxos": "show version | include NXOS",
    "huawei_vrp": "display version | include Version",
    "h3c": "display version | include Version",
    "juniper": "show version | match JUNOS",
    "fortinet": "get system status | grep Version",
    "linux": "uname -a",
    "ruijie": "show version | include Version",
    "ruijie_os": "show version | include Version",
    "hillstone": "show version",
    "aruba": "show version",
}

# 默认忽略的变更模式
DEFAULT_IGNORE_PATTERNS = [
    "Last configuration change",
    "ntp clock-period",
    "!Time:",
    "Current configuration",
]

# 各厂商配置模式命令
CONFIG_COMMANDS = {
    "cisco_ios": {
        "enter_config": "configure terminal",
        "exit_config": "end",
        "save": "write memory",
        "confirm_save": "",
    },
    "cisco_nxos": {
        "enter_config": "configure terminal",
        "exit_config": "end",
        "save": "copy running-config startup-config",
        "confirm_save": "",
    },
    "huawei_vrp": {
        "enter_config": "system-view",
        "exit_config": "quit",
        "save": "save",
        "confirm_save": "y",
    },
    "h3c": {
        "enter_config": "system-view",
        "exit_config": "quit",
        "save": "save force",
        "confirm_save": "",
    },
    "juniper": {
        "enter_config": "configure",
        "exit_config": "exit configuration-mode",
        "save": "commit",
        "confirm_save": "",
    },
    "fortinet": {
        "enter_config": "config global",
        "exit_config": "end",
        "save": "execute save",
        "confirm_save": "",
    },
    "linux": {
        "enter_config": "",
        "exit_config": "",
        "save": "",
        "confirm_save": "",
    },
    "ruijie": {
        "enter_config": "configure terminal",
        "exit_config": "end",
        "save": "write memory",
        "confirm_save": "",
    },
    "ruijie_os": {
        "enter_config": "configure terminal",
        "exit_config": "end",
        "save": "write memory",
        "confirm_save": "",
    },
    "hillstone": {
        "enter_config": "configure terminal",
        "exit_config": "exit",
        "save": "write memory",
        "confirm_save": "",
    },
    "aruba": {
        "enter_config": "configure terminal",
        "exit_config": "end",
        "save": "write memory",
        "confirm_save": "",
    },
}

@dataclass
class CollectResult:
    success: bool
    config_content: str = ""
    error_message: Optional[str] = None
    duration_ms: int = 0

@dataclass
class ChangeResult:
    has_change: bool
    added_lines: int = 0
    removed_lines: int = 0
    diff_text: str = ""
    change_summary: str = ""

async def ping_host(host: str, timeout: float = 2.0) -> bool:
    """Ping检测设备可达性（兼容Windows和Linux/Mac）"""
    try:
        import os
        if os.name == 'nt':
            # Windows: ping -n 1 -w timeout_ms host
            proc = await asyncio.create_subprocess_exec(
                "ping", "-n", "1", "-w", str(int(timeout * 1000)), host,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
        else:
            # Linux/Mac: ping -c 1 -W timeout host
            # Linux 的 -W 单位为秒且要求正整数：小数超时 int() 取整为 0 会立即超时失败，
            # 故向上取整且至少 1 秒；macOS 的 -W 单位为毫秒
            if sys.platform == "darwin":
                wait_arg = str(max(1, int(timeout * 1000)))
            else:
                wait_arg = str(max(1, int(timeout) + (1 if timeout % 1 else 0)))
            proc = await asyncio.create_subprocess_exec(
                "ping", "-c", "1", "-W", wait_arg, host,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
        _, _ = await proc.communicate()
        return proc.returncode == 0
    except Exception:
        return False

async def test_device_connection(device: Dict, credential: Dict) -> CollectResult:
    """
    轻量级设备连接测试（仅测试连通性，不采集完整配置）
    device: {id, ip_address, vendor}
    credential: {username, password, port, protocol, enable_password,
                 jump_host, jump_port, jump_username, jump_password,
                 auth_type, private_key}

    稳定性：netmiko 为同步阻塞库，连接段放入 to_thread 执行，
    避免连接超时 10s + 读取超时 15s 卡死事件循环（与采集路径一致）。
    """
    import time
    start_time = time.time()
    ip_address = device.get("ip_address", "")

    try:
        # 1. Ping检测设备可达性（快速检测）
        if not await ping_host(device.get("ip_address", ""), timeout=0.5):
            return CollectResult(
                success=False,
                error_message="设备不可达",
                duration_ms=int((time.time() - start_time) * 1000)
            )

        # 2. 阻塞段放入线程执行
        return await asyncio.to_thread(_test_device_connection_sync, device, credential, start_time)
    except Exception as e:
        logger.error(f"设备 {ip_address} 连接测试发生错误: {str(e)}")
        return CollectResult(
            success=False,
            error_message=f"测试异常: {str(e)}",
            duration_ms=int((time.time() - start_time) * 1000)
        )


def _test_device_connection_sync(device: Dict, credential: Dict, start_time: float) -> CollectResult:
    """测试连接的同步实现（仅供 test_device_connection 在线程中调用）"""
    ip_address = device.get("ip_address", "")

    try:
        # 构造Netmiko连接参数
        vendor = device.get("vendor", "huawei_vrp").lower()
        device_type = VENDOR_MAP.get(vendor, "huawei_vrp")

        # telnet 凭证：按厂商切换到对应 telnet 驱动，并用纯 telnet 参数连接
        if credential.get("protocol") == "telnet":
            device_type = TELNET_DEVICE_TYPE_MAP.get(device_type, device_type)
            conn_params = _build_telnet_conn_params(device_type, device.get("ip_address"), credential)
            conn_params["conn_timeout"] = 10
            conn_params["read_timeout_override"] = 15
            ssh_config_path = None
        else:
            # SSH 协议：接入统一构造器（TOFU 主机密钥校验 + KEX 兼容 + enable/密钥认证处理）
            conn_params, ssh_config_path = _build_ssh_conn_params(device_type, device.get("ip_address"), credential)
            conn_params.setdefault("conn_timeout", 10)
            conn_params.setdefault("read_timeout_override", 15)

        def _cleanup() -> None:
            """清理临时文件（key_file + ssh_config），telnet 路径两者均为 None"""
            key_file = conn_params.get("key_file")
            if key_file:
                try:
                    os.unlink(key_file)
                except FileNotFoundError:
                    pass
            if ssh_config_path:
                try:
                    os.unlink(ssh_config_path)
                except FileNotFoundError:
                    pass

        # 使用Netmiko连接设备
        from netmiko import Netmiko
        from netmiko.exceptions import NetMikoAuthenticationException, NetMikoTimeoutException
        from paramiko.ssh_exception import BadHostKeyException

        try:
            with Netmiko(**conn_params) as ssh:
                # 进入enable模式（如果需要）
                if credential.get("enable_password"):
                    ssh.enable()

                _cleanup()
                return CollectResult(
                    success=True,
                    config_content="连接测试成功",
                    duration_ms=int((time.time() - start_time) * 1000)
                )
        except BadHostKeyException as e:
            logger.error(f"设备 {ip_address} SSH 主机密钥变更，拒绝连接: {e}")
            _cleanup()
            return CollectResult(
                success=False,
                error_message=(f"SSH主机密钥校验失败（{e.hostname}）：设备密钥与首次记录不一致。"
                               "若确认是设备重装/换钥属正常变更，请管理员删除 data/ssh_host_keys/known_hosts "
                               "中该设备的记录后重试"),
                duration_ms=int((time.time() - start_time) * 1000)
            )
        except NetMikoAuthenticationException:
            logger.error(f"设备 {ip_address} 认证失败")
            _cleanup()
            return CollectResult(
                success=False,
                error_message="认证失败",
                duration_ms=int((time.time() - start_time) * 1000)
            )
        except NetMikoTimeoutException:
            logger.error(f"设备 {ip_address} 连接超时")
            _cleanup()
            return CollectResult(
                success=False,
                error_message="连接超时",
                duration_ms=int((time.time() - start_time) * 1000)
            )
        except Exception as e:
            logger.error(f"设备 {ip_address} 连接测试失败: {str(e)}")
            _cleanup()
            return CollectResult(
                success=False,
                error_message=str(e),
                duration_ms=int((time.time() - start_time) * 1000)
            )

    except Exception as e:
        logger.error(f"设备 {ip_address} 连接测试发生错误: {str(e)}")
        return CollectResult(
            success=False,
            error_message=f"测试异常: {str(e)}",
            duration_ms=int((time.time() - start_time) * 1000)
        )

async def collect_device_config(device: Dict, credential: Dict) -> CollectResult:
    """
    使用Netmiko SSH连接设备采集配置
    device: {id, ip_address, vendor}
    credential: {username, password, port, protocol, enable_password,
                 jump_host, jump_port, jump_username, jump_password,
                 auth_type, private_key}

    稳定性：netmiko 为同步阻塞库，整段放入 to_thread 执行，
    避免慢设备（连接超时 30s + 读取超时 60s）卡死整个事件循环。
    """
    import time
    start_time = time.time()

    try:
        # 1. Ping检测设备可达性
        ip_address = device.get("ip_address", "")
        if not await ping_host(ip_address, timeout=3.0):
            return CollectResult(
                success=False,
                error_message="设备不可达",
                duration_ms=int((time.time() - start_time) * 1000)
            )

        # 2. 阻塞段放入线程执行
        return await asyncio.to_thread(_collect_device_config_sync, device, credential, start_time)
    except Exception as e:
        logger.error(f"设备 {device.get('ip_address', '')} 采集配置发生错误: {str(e)}")
        return CollectResult(
            success=False,
            error_message=f"采集异常: {str(e)}",
            duration_ms=int((time.time() - start_time) * 1000)
        )


def _build_telnet_conn_params(device_type: str, host: str, credential: Dict) -> Dict:
    """构造 telnet 凭证的纯 telnet 连接参数（测试连接/采集/还原三条路径共用）。

    telnet 不涉及 SSH 主机密钥：不执行 TOFU 探测，也不生成临时 ssh_config。
    """
    return {
        "device_type": device_type,
        "host": host,
        "username": credential.get("username"),
        "password": credential.get("password"),
        "port": credential.get("port") or 23,
    }


def _build_ssh_conn_params(device_type: str, host: str, credential: Dict) -> Tuple[Dict, str]:
    """构造统一的 Netmiko 连接参数（三处 SSH 路径共用）。

    - 主机密钥：TOFU 严格校验（ssh_strict=True + 项目级 known_hosts），
      首次连接先无凭证探测记录密钥，之后密钥不一致一律拒绝。
    - 旧设备 KEX 兼容：临时 ssh_config 仅保留 KexAlgorithms（paramiko 实际
      不读取该文件，KEX 兼容最终由 disabled_algorithms/paramiko 内建协商完成，
      保留文件是为了未来切换 OpenSSH 类后端时不丢失兼容配置）。
    - 返回 (conn_params, 临时ssh_config路径)；调用方负责清理该临时文件。
    """
    import tempfile

    port = int(credential.get("port", 22) or 22)

    # TOFU：首次连接先记录主机密钥（无凭证探测，失败按连接超时处理）
    record_ssh_host_key(host, port)

    ssh_config_content = f"""
Host {host}
    KexAlgorithms +diffie-hellman-group14-sha1,diffie-hellman-group-exchange-sha1
"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='_ssh_config', delete=False) as f:
        f.write(ssh_config_content)
        ssh_config_path = f.name

    conn_params: Dict = {
        "device_type": device_type,
        "host": host,
        "username": credential.get("username"),
        "password": credential.get("password"),
        "port": port,
        "allow_agent": False,
        "ssh_config_file": ssh_config_path,
        # 主机密钥严格校验：known_hosts 无记录 → RejectPolicy 拒绝；
        # 有记录但密钥不一致 → paramiko 抛 BadHostKeyException 拒绝。
        "ssh_strict": True,
        "alt_host_keys": True,
        "alt_key_file": _ssh_known_hosts_path(),
    }

    # 处理enable密码
    if credential.get("enable_password"):
        conn_params["secret"] = credential.get("enable_password")

    # 处理SSH密钥认证
    if credential.get("auth_type") == "key" and credential.get("private_key"):
        conn_params["use_keys"] = True
        conn_params["key_file"] = None
        conn_params["password"] = None
        # 将私钥写入临时文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pem', delete=False) as f:
            f.write(credential["private_key"])
            conn_params["key_file"] = f.name

    return conn_params, ssh_config_path


def _collect_device_config_sync(device: Dict, credential: Dict, start_time: float) -> CollectResult:
    """采集配置的同步实现（仅供 collect_device_config 在线程中调用）"""
    ssh_config_path = None
    key_file_path = None
    try:
        # 构造Netmiko连接参数
        vendor = device.get("vendor", "huawei_vrp").lower()
        device_type = VENDOR_MAP.get(vendor, "huawei_vrp")
        host = device.get("ip_address")

        # telnet 凭证：按厂商切换到对应 telnet 驱动，并用纯 telnet 参数连接
        if credential.get("protocol") == "telnet":
            device_type = TELNET_DEVICE_TYPE_MAP.get(device_type, device_type)
            conn_params = _build_telnet_conn_params(device_type, host, credential)
            conn_params["conn_timeout"] = 30
            conn_params["read_timeout_override"] = 60
        else:
            # SSH 协议：统一构造器（含 TOFU 主机密钥校验）
            conn_params, ssh_config_path = _build_ssh_conn_params(device_type, host, credential)
            key_file_path = conn_params.get("key_file")
            conn_params.setdefault("conn_timeout", 30)
            conn_params.setdefault("read_timeout_override", 60)

        # 使用Netmiko连接设备
        from netmiko import Netmiko
        from netmiko.exceptions import NetMikoAuthenticationException, NetMikoTimeoutException
        from paramiko.ssh_exception import BadHostKeyException

        with Netmiko(**conn_params) as ssh:
            # 进入enable模式（如果需要）
            if credential.get("enable_password"):
                ssh.enable()

            # 发送采集命令
            command = BACKUP_COMMANDS.get(vendor, "display current-configuration")
            output = ssh.send_command(command)

            return CollectResult(
                success=True,
                config_content=output,
                duration_ms=int((time.time() - start_time) * 1000)
            )
    except BadHostKeyException as e:
        logger.error(f"设备 {device.get('ip_address', '')} SSH 主机密钥变更，拒绝连接: {e}")
        return CollectResult(
            success=False,
            error_message=(f"SSH主机密钥校验失败（{e.hostname}）：设备密钥与首次记录不一致。"
                           "若确认是设备重装/换钥属正常变更，请管理员删除 data/ssh_host_keys/known_hosts "
                           "中该设备的记录后重试"),
            duration_ms=int((time.time() - start_time) * 1000)
        )
    except NetMikoAuthenticationException:
        logger.error(f"设备 {device.get('ip_address', '')} 认证失败")
        return CollectResult(
            success=False,
            error_message="认证失败",
            duration_ms=int((time.time() - start_time) * 1000)
        )
    except NetMikoTimeoutException:
        logger.error(f"设备 {device.get('ip_address', '')} 连接超时")
        return CollectResult(
            success=False,
            error_message="连接超时",
            duration_ms=int((time.time() - start_time) * 1000)
        )
    except Exception as e:
        logger.error(f"设备 {device.get('ip_address', '')} 采集失败: {str(e)}")
        return CollectResult(
            success=False,
            error_message=str(e),
            duration_ms=int((time.time() - start_time) * 1000)
        )
    finally:
        # 统一清理临时文件（finally 保证任何路径都不泄漏；容忍已删除）
        if key_file_path:
            try:
                os.unlink(key_file_path)
            except FileNotFoundError:
                pass
        if ssh_config_path:
            try:
                os.unlink(ssh_config_path)
            except FileNotFoundError:
                pass

def calculate_hash(content: str) -> str:
    """计算内容的SHA256哈希"""
    return hashlib.sha256(content.encode()).hexdigest()

def detect_config_change(old_content: str, new_content: str, 
                         ignore_patterns: List[str] = None) -> ChangeResult:
    """
    对比两次配置差异
    使用difflib.unified_diff实现
    """
    ignore_patterns = ignore_patterns or DEFAULT_IGNORE_PATTERNS
    
    # 过滤忽略的行
    def filter_lines(content: str) -> List[str]:
        lines = content.splitlines()
        return [line for line in lines if not any(pattern in line for pattern in ignore_patterns)]
    
    old_lines = filter_lines(old_content)
    new_lines = filter_lines(new_content)
    
    # 生成diff
    diff = list(difflib.unified_diff(old_lines, new_lines, n=3))
    
    if not diff:
        return ChangeResult(has_change=False)
    
    # 统计新增和删除行数
    added_lines = sum(1 for line in diff if line.startswith('+') and not line.startswith('+++'))
    removed_lines = sum(1 for line in diff if line.startswith('-') and not line.startswith('---'))
    
    return ChangeResult(
        has_change=True,
        added_lines=added_lines,
        removed_lines=removed_lines,
        diff_text='\n'.join(diff),
        change_summary=f"新增{added_lines}行，删除{removed_lines}行"
    )

def save_config_to_file(device_id: int, backup_id: int, content: str) -> str:
    """
    将配置内容保存到文件
    返回文件路径

    稳定性：backup_id<=0（尚无记录 ID）时用毫秒时间戳命名，
    避免同一设备的大备份都写 0.txt 互相覆盖、多条 DB 记录指向同一文件。
    """
    base_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'backups', str(device_id))
    os.makedirs(base_path, exist_ok=True)

    if backup_id and backup_id > 0:
        file_name = f"{backup_id}.txt"
    else:
        file_name = f"t{int(time.time() * 1000)}.txt"
    file_path = os.path.join(base_path, file_name)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    return file_path

def load_config_from_file(file_path: str) -> str:
    """从文件加载配置内容"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()


# ==================== SSH 主机密钥校验（TOFU：Trust On First Use） ====================
# 背景：此前三处 SSH 连接依赖临时 ssh_config 里的 StrictHostKeyChecking no，
# 但 netmiko 的 _use_ssh_config 只应用 port/username/hostname/sock 四个字段，
# 该指令对 paramiko 完全无效——真实行为是 netmiko 默认 AutoAddPolicy：
# 接受任意主机密钥，中间人可伪装生产设备窃取管理凭证。
#
# 现改为 TOFU 模式：
#   1. 首次连接前用「无凭证裸 Transport 探测」记录设备主机密钥到
#      data/ssh_host_keys/known_hosts（OpenSSH known_hosts 格式）；
#   2. 之后每次连接通过 netmiko 原生参数 ssh_strict=True + alt_host_keys 严格校验，
#      密钥不一致抛 BadHostKeyException 直接拒绝（不下发任何命令、不发送凭证）。
#   3. 设备重装/换钥匙后需管理员人工核实并删除 known_hosts 中对应行，防止误放行。
# 注：临时 ssh_config 中的指令仅对 OpenSSH 二进制生效（paramiko 忽略），
#     真正的强校验以 conn_params 中的 ssh_strict/alt_host_keys 为准。

def _ssh_known_hosts_path() -> str:
    base = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'ssh_host_keys')
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, 'known_hosts')


def _host_key_entry_name(host: str, port: int) -> str:
    """known_hosts 条目名，与 paramiko 内部约定一致（非 22 端口用 [host]:port）"""
    host = (host or "").strip()
    if not host:
        raise ValueError("SSH 主机地址为空，无法进行主机密钥校验")
    return host if port == 22 else f"[{host}]:{port}"


def _host_key_recorded(entry_name: str) -> bool:
    import paramiko
    hk = paramiko.hostkeys.HostKeys()
    try:
        hk.load(_ssh_known_hosts_path())
    except (FileNotFoundError, IOError):
        return False
    return hk.lookup(entry_name) is not None


def record_ssh_host_key(host: str, port: int) -> None:
    """TOFU 首次记录设备主机密钥（幂等：已记录直接返回）。

    探测使用无凭证的裸 Transport——只协商密钥、不发送任何登录凭证，
    即使此时存在中间人也仅记录到攻击者的密钥（首次信任窗口，与 OpenSSH TOFU 一致），
    后续任何密钥不一致都会被严格校验拦截。
    探测失败（不可达/超时）统一转为 NetMikoTimeoutException，由调用方按「连接超时」处理。
    """
    import paramiko
    from netmiko.exceptions import NetMikoTimeoutException

    entry_name = _host_key_entry_name(host, int(port or 22))
    if _host_key_recorded(entry_name):
        return
    transport = None
    try:
        transport = paramiko.Transport((host, int(port or 22)))
        transport.start_client(timeout=15)
        server_key = transport.get_remote_server_key()
        hk = paramiko.hostkeys.HostKeys()
        try:
            hk.load(_ssh_known_hosts_path())
        except (FileNotFoundError, IOError):
            pass
        hk.add(entry_name, server_key.get_name(), server_key)
        hk.save(_ssh_known_hosts_path())
        logger.info(f"TOFU 首次记录 SSH 主机密钥: {entry_name} ({server_key.get_name()})")
    except Exception as e:
        logger.warning(f"SSH 主机密钥探测失败 {entry_name}: {e}")
        raise NetMikoTimeoutException(f"SSH 主机密钥获取失败（{entry_name}）: {e}")
    finally:
        if transport is not None:
            try:
                transport.close()
            except Exception:
                pass

# 还原前危险命令黑名单（不区分大小写）。
# 目的：即使备份文件被人工篡改或粘入越权内容，也杜绝 reload/reboot/擦除类操作，
# 这是防止"还原导致设备重启/清配置"的最后防线。
#
# 匹配规则：对每行提取"有效命令首词序列"后再匹配，从而拦截厂商前缀变体：
#   - Cisco 配置模式：  do reload / do write erase
#   - FortiGate：       execute reboot / execute restore default
#   - Juniper：         request system reboot / request system zeroize
#   - 华为 VRP：        reboot / reset saved-configuration / factory-reset
# 注意：接口级 shutdown（管理性关闭接口）是正常配置内容，不在此列——
# 若拦截会导致含禁用接口的正常备份永远无法还原。
# 纯文本描述行（如注释）在过滤前已剔除，不受影响。
DANGEROUS_CONFIG_PATTERNS = (
    "reload", "reboot", "erase", "write erase", "format",
    "delete flash", "delete /force", "boot system", "factory-reset",
    "restore default", "reset saved-configuration", "zeroize",
)

# 厂商 CLI 中常见的"上下文前缀"：拦截时先剥离这些词再匹配真实命令动词，
# 使 "do reload" / "execute reboot" / "request system reboot" 与裸命令同等对待。
_DANGEROUS_PREFIX_WORDS = (
    "do", "execute", "request", "run", "undo", "no", "system",
)


def _effective_dangerous_key(line: str) -> str:
    """提取一行配置的有效匹配键：剥离厂商上下文前缀词后的命令串（小写）。

    例：
      "do reload"             -> "reload"
      "execute reboot"        -> "reboot"
      "request system reboot" -> "reboot"（request、system 均为前缀词）
      "write erase"           -> "write erase"
      "interface GigabitEthernet0/0" -> 原样返回（无危险词，不命中）
    """
    tokens = line.strip().lower().split()
    # 最多剥离 3 层前缀（request system reboot 这类两层已覆盖，留余量防嵌套）
    for _ in range(3):
        if len(tokens) > 1 and tokens[0] in _DANGEROUS_PREFIX_WORDS:
            tokens = tokens[1:]
        else:
            break
    return " ".join(tokens)


def filter_dangerous_config_lines(config_content: str) -> tuple[List[str], List[str]]:
    """过滤还原内容中的危险命令行。

    返回 (安全配置行列表, 被拦截的行列表)。注释/空行在过滤前已剔除。
    匹配采用"前缀词剥离后的行首匹配"：既覆盖裸命令，也覆盖 do/execute/request 等变体；
    不会误伤行中间恰好包含敏感词的普通配置（如描述文本）。
    """
    kept: List[str] = []
    blocked: List[str] = []
    for line in config_content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('!') or stripped.startswith('#'):
            continue
        key = _effective_dangerous_key(stripped)
        if key and any(key.startswith(p) for p in DANGEROUS_CONFIG_PATTERNS):
            blocked.append(stripped)
            continue
        kept.append(stripped)
    return kept, blocked


async def apply_config_to_device(device: Dict, credential: Dict, config_content: str) -> CollectResult:
    """
    使用Netmiko SSH连接设备并应用配置
    device: {id, ip_address, vendor}
    credential: {username, password, port, protocol, enable_password,
                 jump_host, jump_port, jump_username, jump_password,
                 auth_type, private_key}
    config_content: 要应用的配置内容

    稳定性：netmiko 为同步阻塞库，SSH 交互段放入 to_thread 执行，
    还原最长可能持续数分钟，绝不能阻塞事件循环。
    """
    import time

    start_time = time.time()
    ip_address = device.get("ip_address", "")

    logger.info(f"开始还原配置到设备 {ip_address}, 厂商: {device.get('vendor', 'huawei_vrp')}")
    logger.info(f"配置内容长度: {len(config_content)} 字符")

    try:
        # 1. Ping检测设备可达性
        logger.info(f"正在Ping设备 {ip_address}...")
        if not await ping_host(ip_address, timeout=3.0):
            logger.error(f"设备 {ip_address} 不可达")
            return CollectResult(
                success=False,
                error_message="设备不可达",
                duration_ms=int((time.time() - start_time) * 1000)
            )
        logger.info(f"设备 {ip_address} Ping成功")

        # 2. 危险命令过滤（防重启/擦除的最后防线）
        config_lines, blocked_lines = filter_dangerous_config_lines(config_content)
        if blocked_lines:
            logger.warning(
                f"还原内容包含 {len(blocked_lines)} 条危险命令已拦截，不做任何下发: {blocked_lines}"
            )
            return CollectResult(
                success=False,
                error_message=f"还原内容包含危险命令已拦截: {'; '.join(blocked_lines[:5])}",
                duration_ms=int((time.time() - start_time) * 1000)
            )
        if not config_lines:
            return CollectResult(
                success=False,
                error_message="还原内容没有有效配置行",
                duration_ms=int((time.time() - start_time) * 1000)
            )
        logger.info(f"危险命令过滤完成，待下发 {len(config_lines)} 行")

        # 3. SSH 交互段放入线程执行
        return await asyncio.to_thread(_apply_config_to_device_sync, device, credential, config_lines, start_time)
    except Exception as e:
        logger.error(f"设备 {ip_address} 还原配置发生错误: {str(e)}")
        return CollectResult(
            success=False,
            error_message=f"应用配置异常: {str(e)}",
            duration_ms=int((time.time() - start_time) * 1000)
        )


def _apply_config_to_device_sync(device: Dict, credential: Dict,
                                 config_lines: List[str], start_time: float) -> CollectResult:
    """还原配置的同步实现（仅供 apply_config_to_device 在线程中调用）。

    config_lines 已经过危险命令过滤，这里直接逐行合并下发。
    """
    ip_address = device.get("ip_address", "")
    vendor = device.get("vendor", "huawei_vrp").lower()

    ssh_config_path = None
    key_file_path = None
    try:
        # 构造Netmiko连接参数
        device_type = VENDOR_MAP.get(vendor, "huawei_vrp")

        # telnet 凭证：按厂商切换到对应 telnet 驱动，并用纯 telnet 参数连接
        if credential.get("protocol") == "telnet":
            device_type = TELNET_DEVICE_TYPE_MAP.get(device_type, device_type)
            conn_params = _build_telnet_conn_params(device_type, device.get("ip_address"), credential)
            conn_params["conn_timeout"] = 30
            conn_params["read_timeout_override"] = 120
        else:
            # SSH 协议：统一构造器（含 TOFU 主机密钥校验）
            conn_params, ssh_config_path = _build_ssh_conn_params(device_type, device.get("ip_address"), credential)
            key_file_path = conn_params.get("key_file")
            conn_params.setdefault("conn_timeout", 30)
            conn_params.setdefault("read_timeout_override", 120)

        # 获取厂商配置命令
        config_cmds = CONFIG_COMMANDS.get(vendor, CONFIG_COMMANDS["huawei_vrp"])
        logger.info(f"厂商配置命令: enter_config={config_cmds['enter_config']}, save={config_cmds['save']}, exit_config={config_cmds['exit_config']}")

        # 使用Netmiko连接设备
        from netmiko import Netmiko
        from netmiko.exceptions import NetMikoAuthenticationException, NetMikoTimeoutException
        from paramiko.ssh_exception import BadHostKeyException

        logger.info(f"正在使用Netmiko连接设备 {ip_address}...")
        with Netmiko(**conn_params) as ssh:
            logger.info(f"成功连接到设备 {ip_address}")

            # 进入 enable 模式（如果需要）
            if credential.get("enable_password"):
                logger.info("进入 enable 模式...")
                ssh.enable()
                logger.info("已进入 enable 模式")

            # 进入配置模式（使用 netmiko 默认提示符检测，原 expect_string
            # r"[\[~\]].*" 无法匹配 Cisco "(config)#" 提示符，会一直卡到超时）
            if config_cmds["enter_config"]:
                logger.info(f"进入配置模式：{config_cmds['enter_config']}")
                output = ssh.send_command(config_cmds["enter_config"])
                logger.info(f"进入配置模式输出：{output.strip()[:100]}")
                logger.info("已进入配置模式")

            # 批量发送配置（使用 send_config_set 方法）
            logger.info(f"开始发送配置，共 {len(config_lines)} 行")

            # 使用 send_config_set 批量发送配置，禁用自动进入/退出配置模式
            output = ssh.send_config_set(
                config_lines,
                delay_factor=0.1,
                max_loops=1000,
                strip_prompt=False,
                strip_command=False,
                enter_config_mode=False,   # 我们已经手动进入了配置模式
                exit_config_mode=False     # 暂时不退出，保存后再退出
            )
            logger.info(f"配置发送完成，共 {len(config_lines)} 行")

            # 保存配置
            if config_cmds["save"]:
                logger.info(f"保存配置：{config_cmds['save']}")
                # 使用 send_command_timing 处理交互式命令（更可靠）
                output = ssh.send_command_timing(config_cmds["save"])
                logger.info(f"保存命令输出：{output.strip()[:500]}")

                # 发送确认 'y'
                if config_cmds["confirm_save"]:
                    logger.info(f"发送确认：{config_cmds['confirm_save']}")
                    # 使用 send_command_timing，不等待特定提示符
                    output2 = ssh.send_command_timing(config_cmds["confirm_save"], delay_factor=2)
                    logger.info(f"确认输出：{output2.strip()[:500]}")

                    # 处理文件名输入提示（H3C 设备会提示输入文件名）
                    if "input the file name" in output2.lower() or "press the enter key" in output2.lower():
                        logger.info("检测到文件名输入提示，按回车使用默认文件名")
                        output3 = ssh.send_command_timing("\n", delay_factor=3)
                        logger.info(f"文件名确认输出：{output3.strip()[:300]}")

                        # 处理覆盖确认（H3C 设备会提示是否覆盖现有文件）
                        if "overwrite" in output3.lower() and "[y/n]" in output3.lower():
                            logger.info("检测到覆盖确认提示，发送确认：y")
                            output4 = ssh.send_command_timing("y", delay_factor=3)
                            logger.info(f"覆盖确认输出：{output4.strip()[:300]}")

                    elif ".cfg" in output2.lower():
                        # 如果包含 .cfg 但不包含输入提示，也发送回车
                        logger.info("检测到文件名提示，按回车使用默认文件名")
                        output3 = ssh.send_command_timing("\n", delay_factor=3)
                        logger.info(f"文件名确认输出：{output3.strip()[:300]}")

                        # 处理覆盖确认
                        if "overwrite" in output3.lower() and "[y/n]" in output3.lower():
                            logger.info("检测到覆盖确认提示，发送确认：y")
                            output4 = ssh.send_command_timing("y", delay_factor=3)
                            logger.info(f"覆盖确认输出：{output4.strip()[:300]}")

                    logger.info("保存确认完成")

            # 退出配置模式
            if config_cmds["exit_config"]:
                logger.info(f"退出配置模式: {config_cmds['exit_config']}")
                ssh.send_command(config_cmds["exit_config"])
                logger.info("已退出配置模式")

            return CollectResult(
                success=True,
                config_content="配置应用成功",
                duration_ms=int((time.time() - start_time) * 1000)
            )
    except NetMikoAuthenticationException:
        logger.error(f"设备 {ip_address} 认证失败")
        return CollectResult(
            success=False,
            error_message="认证失败",
            duration_ms=int((time.time() - start_time) * 1000)
        )
    except NetMikoTimeoutException:
        logger.error(f"设备 {ip_address} 连接超时")
        return CollectResult(
            success=False,
            error_message="连接超时",
            duration_ms=int((time.time() - start_time) * 1000)
        )
    except BadHostKeyException as e:
        logger.error(f"设备 {ip_address} SSH 主机密钥变更，拒绝还原: {e}")
        return CollectResult(
            success=False,
            error_message=(f"SSH主机密钥校验失败（{e.hostname}）：设备密钥与首次记录不一致，已中止还原。"
                           "若确认是设备重装/换钥属正常变更，请管理员删除 data/ssh_host_keys/known_hosts "
                           "中该设备的记录后重试"),
            duration_ms=int((time.time() - start_time) * 1000)
        )
    except Exception as e:
        logger.error(f"设备 {ip_address} 配置应用失败: {str(e)}")
        return CollectResult(
            success=False,
            error_message=str(e),
            duration_ms=int((time.time() - start_time) * 1000)
        )
    finally:
        # 统一清理临时文件（finally 保证任何路径都不泄漏；容忍已删除）
        if key_file_path:
            try:
                os.unlink(key_file_path)
            except FileNotFoundError:
                pass
        if ssh_config_path:
            try:
                os.unlink(ssh_config_path)
            except FileNotFoundError:
                pass