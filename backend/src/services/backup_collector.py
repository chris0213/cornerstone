import hashlib
import difflib
import os
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

# telnet 凭证对应的 netmiko device_type（仅 test_device_connection 的测试连接路径使用）。
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
            proc = await asyncio.create_subprocess_exec(
                "ping", "-c", "1", "-W", str(int(timeout)), host,
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
        
        # 2. 构造Netmiko连接参数
        vendor = device.get("vendor", "huawei_vrp").lower()
        device_type = VENDOR_MAP.get(vendor, "huawei_vrp")

        # telnet 凭证：按厂商切换到对应 telnet 驱动（仅影响本测试连接函数，备份采集路径不受影响）
        if credential.get("protocol") == "telnet":
            device_type = TELNET_DEVICE_TYPE_MAP.get(device_type, device_type)
        
        # 创建临时SSH配置文件以支持旧设备的密钥交换算法
        import tempfile
        ssh_config_content = f"""
Host {device.get("ip_address")}
    KexAlgorithms +diffie-hellman-group14-sha1,diffie-hellman-group-exchange-sha1
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='_ssh_config', delete=False) as f:
            f.write(ssh_config_content)
            ssh_config_path = f.name
        
        # 构建基础连接参数
        conn_params: Dict = {
            "device_type": device_type,
            "host": device.get("ip_address"),
            "username": credential.get("username"),
            "password": credential.get("password"),
            "port": credential.get("port", 22),
            "conn_timeout": 10,  # 连接超时
            "read_timeout_override": 15,  # 读取超时
            "allow_agent": False,
            "ssh_config_file": ssh_config_path,
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
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.pem', delete=False) as f:
                f.write(credential["private_key"])
                conn_params["key_file"] = f.name
        
        # 3. 使用Netmiko连接设备
        from netmiko import Netmiko
        from netmiko.exceptions import NetMikoAuthenticationException, NetMikoTimeoutException
        
        try:
            with Netmiko(**conn_params) as ssh:
                # 进入enable模式（如果需要）
                if credential.get("enable_password"):
                    ssh.enable()
                
                # 清理临时文件
                if "key_file" in conn_params and conn_params["key_file"]:
                    os.unlink(conn_params["key_file"])
                os.unlink(ssh_config_path)
                
                return CollectResult(
                    success=True,
                    config_content="连接测试成功",
                    duration_ms=int((time.time() - start_time) * 1000)
                )
        except NetMikoAuthenticationException:
            logger.error(f"设备 {ip_address} 认证失败")
            if "key_file" in conn_params and conn_params.get("key_file"):
                os.unlink(conn_params["key_file"])
            os.unlink(ssh_config_path)
            return CollectResult(
                success=False,
                error_message="认证失败",
                duration_ms=int((time.time() - start_time) * 1000)
            )
        except NetMikoTimeoutException:
            logger.error(f"设备 {ip_address} 连接超时")
            if "key_file" in conn_params and conn_params.get("key_file"):
                os.unlink(conn_params["key_file"])
            os.unlink(ssh_config_path)
            return CollectResult(
                success=False,
                error_message="连接超时",
                duration_ms=int((time.time() - start_time) * 1000)
            )
        except Exception as e:
            logger.error(f"设备 {ip_address} 配置应用失败: {str(e)}")
            if "key_file" in conn_params and conn_params.get("key_file"):
                os.unlink(conn_params["key_file"])
            os.unlink(ssh_config_path)
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
        
        # 2. 构造Netmiko连接参数
        vendor = device.get("vendor", "huawei_vrp").lower()
        device_type = VENDOR_MAP.get(vendor, "huawei_vrp")
        
        # 创建临时SSH配置文件以支持旧设备的密钥交换算法
        import tempfile
        ssh_config_content = f"""
Host {device.get("ip_address")}
    KexAlgorithms +diffie-hellman-group14-sha1,diffie-hellman-group-exchange-sha1
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='_ssh_config', delete=False) as f:
            f.write(ssh_config_content)
            ssh_config_path = f.name
        
        # 构建基础连接参数
        conn_params: Dict = {
            "device_type": device_type,
            "host": device.get("ip_address"),
            "username": credential.get("username"),
            "password": credential.get("password"),
            "port": credential.get("port", 22),
            "conn_timeout": 30,
            "read_timeout_override": 60,
            "allow_agent": False,
            "ssh_config_file": ssh_config_path,
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
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.pem', delete=False) as f:
                f.write(credential["private_key"])
                conn_params["key_file"] = f.name
        
        # 3. 使用Netmiko连接设备
        from netmiko import Netmiko
        from netmiko.exceptions import NetMikoAuthenticationException, NetMikoTimeoutException
        
        try:
            with Netmiko(**conn_params) as ssh:
                # 进入enable模式（如果需要）
                if credential.get("enable_password"):
                    ssh.enable()
                
                # 发送采集命令
                command = BACKUP_COMMANDS.get(vendor, "display current-configuration")
                output = ssh.send_command(command)
                
                # 清理临时文件
                if "key_file" in conn_params and conn_params["key_file"]:
                    os.unlink(conn_params["key_file"])
                os.unlink(ssh_config_path)
                
                return CollectResult(
                    success=True,
                    config_content=output,
                    duration_ms=int((time.time() - start_time) * 1000)
                )
        except NetMikoAuthenticationException:
            logger.error(f"设备 {ip_address} 认证失败")
            if "key_file" in conn_params and conn_params.get("key_file"):
                os.unlink(conn_params["key_file"])
            os.unlink(ssh_config_path)
            return CollectResult(
                success=False,
                error_message="认证失败",
                duration_ms=int((time.time() - start_time) * 1000)
            )
        except NetMikoTimeoutException:
            logger.error(f"设备 {ip_address} 连接超时")
            if "key_file" in conn_params and conn_params.get("key_file"):
                os.unlink(conn_params["key_file"])
            os.unlink(ssh_config_path)
            return CollectResult(
                success=False,
                error_message="连接超时",
                duration_ms=int((time.time() - start_time) * 1000)
            )
        except Exception as e:
            logger.error(f"设备 {ip_address} 配置应用失败: {str(e)}")
            if "key_file" in conn_params and conn_params.get("key_file"):
                os.unlink(conn_params["key_file"])
            os.unlink(ssh_config_path)
            return CollectResult(
                success=False,
                error_message=str(e),
                duration_ms=int((time.time() - start_time) * 1000)
            )
    
    except Exception as e:
        logger.error(f"设备 {ip_address} 还原配置发生错误: {str(e)}")
        os.unlink(ssh_config_path)
        return CollectResult(
            success=False,
            error_message=f"采集异常: {str(e)}",
            duration_ms=int((time.time() - start_time) * 1000)
        )

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
    """
    base_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'backups', str(device_id))
    os.makedirs(base_path, exist_ok=True)
    
    file_path = os.path.join(base_path, f"{backup_id}.txt")
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    return file_path

def load_config_from_file(file_path: str) -> str:
    """从文件加载配置内容"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()

async def apply_config_to_device(device: Dict, credential: Dict, config_content: str) -> CollectResult:
    """
    使用Netmiko SSH连接设备并应用配置
    device: {id, ip_address, vendor}
    credential: {username, password, port, protocol, enable_password, 
                 jump_host, jump_port, jump_username, jump_password,
                 auth_type, private_key}
    config_content: 要应用的配置内容
    """
    import time
    
    start_time = time.time()
    ip_address = device.get("ip_address", "")
    vendor = device.get("vendor", "huawei_vrp").lower()
    
    logger.info(f"开始还原配置到设备 {ip_address}, 厂商: {vendor}")
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
        
        # 2. 构造Netmiko连接参数
        vendor = device.get("vendor", "huawei_vrp").lower()
        device_type = VENDOR_MAP.get(vendor, "huawei_vrp")
        
        # 创建临时SSH配置文件以支持旧设备的密钥交换算法
        import tempfile
        ssh_config_content = f"""
Host {device.get("ip_address")}
    KexAlgorithms +diffie-hellman-group14-sha1,diffie-hellman-group-exchange-sha1
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='_ssh_config', delete=False) as f:
            f.write(ssh_config_content)
            ssh_config_path = f.name
        
        # 构建基础连接参数
        conn_params: Dict = {
            "device_type": device_type,
            "host": device.get("ip_address"),
            "username": credential.get("username"),
            "password": credential.get("password"),
            "port": credential.get("port", 22),
            "conn_timeout": 30,
            "read_timeout_override": 120,
            "allow_agent": False,
            "ssh_config_file": ssh_config_path,
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
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.pem', delete=False) as f:
                f.write(credential["private_key"])
                conn_params["key_file"] = f.name
        
        # 3. 获取厂商配置命令
        config_cmds = CONFIG_COMMANDS.get(vendor, CONFIG_COMMANDS["huawei_vrp"])
        logger.info(f"厂商配置命令: enter_config={config_cmds['enter_config']}, save={config_cmds['save']}, exit_config={config_cmds['exit_config']}")
        
        # 4. 使用Netmiko连接设备
        from netmiko import Netmiko
        from netmiko.exceptions import NetMikoAuthenticationException, NetMikoTimeoutException
        
        logger.info(f"正在使用Netmiko连接设备 {ip_address}...")
        try:
            with Netmiko(**conn_params) as ssh:
                logger.info(f"成功连接到设备 {ip_address}")
                
                # 进入 enable 模式（如果需要）
                if credential.get("enable_password"):
                    logger.info("进入 enable 模式...")
                    ssh.enable()
                    logger.info("已进入 enable 模式")
                
                # 进入配置模式
                if config_cmds["enter_config"]:
                    logger.info(f"进入配置模式：{config_cmds['enter_config']}")
                    # 使用更宽松的提示符匹配
                    output = ssh.send_command(config_cmds["enter_config"], expect_string=r"[\[~\]].*")
                    logger.info(f"进入配置模式输出：{output.strip()[:100]}")
                    logger.info("已进入配置模式")
                
                # 批量发送配置（使用 send_config_set 方法）
                config_lines = [line.strip() for line in config_content.splitlines() 
                               if line.strip() and not line.startswith('!') and not line.startswith('#')]
                logger.info(f"开始发送配置，共 {len(config_lines)} 行")
                
                try:
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
                except Exception as e:
                    logger.error(f"批量发送配置失败：{str(e)}")
                    raise
                
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
                
                # 清理临时文件
                if "key_file" in conn_params and conn_params["key_file"]:
                    os.unlink(conn_params["key_file"])
                os.unlink(ssh_config_path)
                
                return CollectResult(
                    success=True,
                    config_content="配置应用成功",
                    duration_ms=int((time.time() - start_time) * 1000)
                )
        except NetMikoAuthenticationException:
            logger.error(f"设备 {ip_address} 认证失败")
            if "key_file" in conn_params and conn_params.get("key_file"):
                os.unlink(conn_params["key_file"])
            os.unlink(ssh_config_path)
            return CollectResult(
                success=False,
                error_message="认证失败",
                duration_ms=int((time.time() - start_time) * 1000)
            )
        except NetMikoTimeoutException:
            logger.error(f"设备 {ip_address} 连接超时")
            if "key_file" in conn_params and conn_params.get("key_file"):
                os.unlink(conn_params["key_file"])
            os.unlink(ssh_config_path)
            return CollectResult(
                success=False,
                error_message="连接超时",
                duration_ms=int((time.time() - start_time) * 1000)
            )
        except Exception as e:
            logger.error(f"设备 {ip_address} 配置应用失败: {str(e)}")
            if "key_file" in conn_params and conn_params.get("key_file"):
                os.unlink(conn_params["key_file"])
            os.unlink(ssh_config_path)
            return CollectResult(
                success=False,
                error_message=str(e),
                duration_ms=int((time.time() - start_time) * 1000)
            )
    
    except Exception as e:
        logger.error(f"设备 {ip_address} 还原配置发生错误: {str(e)}")
        os.unlink(ssh_config_path)
        return CollectResult(
            success=False,
            error_message=f"应用配置异常: {str(e)}",
            duration_ms=int((time.time() - start_time) * 1000)
        )