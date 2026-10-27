import logging
from typing import Optional, Dict, Any
from netmiko import ConnectHandler
from paramiko.ssh_exception import AuthenticationException, SSHException
from socket import timeout as SocketTimeout
logger = logging.getLogger(__name__)


def connect_device(device_info: Dict[str, Any]) -> Optional[ConnectHandler]:
    """
    连接网络设备
    :param device_info: 设备信息字典，包含: ip, username, password, device_type, port
    :return: Netmiko连接对象
    """
    try:
        conn = ConnectHandler(
            ip=device_info.get("ip"),
            username=device_info.get("username"),
            password=device_info.get("password"),
            device_type=device_info.get("device_type", "cisco_ios"),
            port=device_info.get("port", 22),
            secret=device_info.get("secret"),
            timeout=10,
            banner_timeout=10,
        )
        return conn
    except AuthenticationException:
        logger.warning(f"认证失败: {device_info.get('ip')}")
        return None
    except SSHException:
        logger.warning(f"SSH错误: {device_info.get('ip')}")
        return None
    except SocketTimeout:
        logger.info(f"连接超时: {device_info.get('ip')}")
        return None
    except Exception as e:
        logger.warning(f"连接错误 {device_info.get('ip')}: {str(e)}")
        return None

def get_config(conn: ConnectHandler, config_type: str = "running") -> Optional[str]:
    """
    获取设备配置
    :param conn: Netmiko连接对象
    :param config_type: 配置类型: running, startup
    :return: 配置内容
    """
    try:
        if config_type == "running":
            output = conn.send_command("show running-config")
        elif config_type == "startup":
            output = conn.send_command("show startup-config")
        else:
            output = conn.send_command("show running-config")
        return output
    except Exception as e:
        logger.warning(f"获取配置失败: {str(e)}")
        return None

def backup_config(device_info: Dict[str, Any], config_type: str = "running") -> Optional[str]:
    """
    备份设备配置
    :param device_info: 设备信息字典
    :param config_type: 配置类型
    :return: 配置内容
    """
    conn = connect_device(device_info)
    if conn is None:
        return None
    
    try:
        config = get_config(conn, config_type)
        conn.disconnect()
        return config
    except Exception as e:
        logger.warning(f"备份配置失败: {str(e)}")
        if conn:
            conn.disconnect()
        return None

def get_device_info(conn: ConnectHandler) -> Optional[Dict[str, str]]:
    """
    获取设备基本信息
    :param conn: Netmiko连接对象
    :return: 设备信息字典
    """
    try:
        output = conn.send_command("show version")
        return {"version": output}
    except Exception as e:
        logger.warning(f"获取设备信息失败: {str(e)}")
        return None


def get_lldp_neighbors(conn: ConnectHandler) -> Optional[list]:
    """
    获取LLDP邻居信息，并把每个命令的输出写入调试日志 /tmp/lldp_debug.log
    :param conn: Netmiko连接对象
    :return: 邻居列表
    """
    try:
        # 尝试多种LLDP命令
        commands = [
            "show lldp neighbors detail",
            "show lldp neighbor detail",
            "display lldp neighbor",
            "display lldp neighbor brief",
            "display lldp neighbor-information",
            "show cdp neighbors detail",
            "show cdp neighbor detail",
            "display cdp neighbor",
            "show lldp neighbors",
            "display lldp neighbors"
        ]

        # 获取连接的主机信息（尽量兼容不同netmiko版本）
        host = getattr(conn, 'host', None) or getattr(conn, 'ip', None) or getattr(conn, 'remote_addr', 'unknown')

        for cmd in commands:
            try:
                output = conn.send_command(cmd)
                logger.debug(f"LLDP host={host} cmd={cmd} output_len={len(output)}")

                if output and output.strip():
                    # 检查是否为错误输出
                    lower_output = output.lower()
                    if "invalid" in lower_output or "error" in lower_output or "unrecognized" in lower_output:
                        continue
                    # 尝试解析
                    neighbors = parse_lldp_output(output)
                    if neighbors and len(neighbors) > 0:
                        logger.debug(f"LLDP host={host} cmd={cmd} parsed neighbors count={len(neighbors)}")
                        return neighbors
                    logger.debug(f"LLDP host={host} cmd={cmd} succeeded but no neighbors parsed")
            except Exception as cmd_e:
                logger.warning(f"LLDP host={host} cmd={cmd} failed: {cmd_e}")
                continue

        return None
    except Exception as e:
        logger.error(f"获取LLDP邻居失败 host={host}", exc_info=True)
        return None


def parse_lldp_output(output: str) -> list:
    """
    解析LLDP/CDP输出
    :param output: 命令输出
    :return: 解析后的邻居列表
    """
    neighbors = []
    lines = output.strip().split('\n')
    
    # 检测是否为表格格式（华为brief格式）
    if len(lines) >= 2 and "Local Intf" in lines[0] and "Neighbor Dev" in lines[0]:
        return parse_lldp_table_format(lines)
    
    current_neighbor = {}
    interface = None
    current_port = None
    
    for line in lines:
        line = line.strip()
        
        # 匹配本地接口 - 多种格式
        if "Local Intf" in line or "Local Interface" in line or "本地接口" in line:
            parts = line.split(':', 1)
            if len(parts) > 1:
                interface = parts[1].strip()
        elif line.startswith("Interface"):
            parts = line.split(':', 1)
            if len(parts) > 1:
                interface = parts[1].strip()
        # H3C格式："LLDP neighbor-information of port 48[GigabitEthernet1/0/48]:"
        elif "neighbor-information of port" in line:
            # 提取接口名
            start = line.find('[')
            end = line.find(']')
            if start != -1 and end != -1:
                interface = line[start+1:end]
        # 华为/H3C格式："GigabitEthernet0/0/23 has 1 neighbor(s):"
        elif "has 1 neighbor" in line or "has neighbor" in line:
            interface = line.split()[0]
        
        # 匹配邻居设备名 - 多种格式
        if "Chassis ID" in line or "System Name" in line or "Device ID" in line or "系统名称" in line:
            parts = line.split(':', 1)
            if len(parts) > 1:
                current_neighbor['remote_device'] = parts[1].strip()
        elif "Peer Device ID" in line or "Neighbor Device" in line:
            parts = line.split(':', 1)
            if len(parts) > 1:
                current_neighbor['remote_device'] = parts[1].strip()
        # H3C格式："System name         :PEK-SW-POE-2-4.34"（冒号后可能没有空格）
        elif line.startswith("System name"):
            parts = line.split(':', 1)
            if len(parts) > 1:
                current_neighbor['remote_device'] = parts[1].strip()
        
        # 匹配邻居接口 - 多种格式
        if "Port ID" in line or "Remote Port" in line or "远端端口" in line:
            parts = line.split(':', 1)
            if len(parts) > 1:
                current_neighbor['remote_port'] = parts[1].strip()
        elif "Peer Port" in line or "Neighbor Port" in line:
            parts = line.split(':', 1)
            if len(parts) > 1:
                current_neighbor['remote_port'] = parts[1].strip()
        elif "Port Description" in line and not current_neighbor.get('remote_port'):
            parts = line.split(':', 1)
            if len(parts) > 1:
                current_neighbor['remote_port'] = parts[1].strip()
        # H3C格式："PortID/subtype      : GigabitEthernet0/0/24/Interface name"
        elif line.startswith("PortID/"):
            parts = line.split(':', 1)
            if len(parts) > 1:
                port_info = parts[1].strip()
                # 提取接口名（可能包含 "/Interface name" 后缀）
                if "/Interface name" in port_info:
                    current_neighbor['remote_port'] = port_info.replace("/Interface name", "").strip()
                else:
                    current_neighbor['remote_port'] = port_info
        # H3C格式："Port ID type   :Interface name" 或 "Port ID        :GigabitEthernet1/0/48"
        elif line.startswith("Port ID") and not line.startswith("Port ID type"):
            parts = line.split(':', 1)
            if len(parts) > 1:
                current_neighbor['remote_port'] = parts[1].strip()
        
        # 检测是否完成一个邻居的解析（分隔线或空行）
        if line.startswith("----") or line.startswith("=====") or (line == "" and interface and current_neighbor.get('remote_device')):
            if interface and current_neighbor.get('remote_device'):
                neighbors.append({
                    'local_interface': interface,
                    'remote_device': current_neighbor.get('remote_device'),
                    'remote_port': current_neighbor.get('remote_port')
                })
                current_neighbor = {}
                interface = None
    
    # 处理最后一个邻居
    if interface and current_neighbor.get('remote_device'):
        neighbors.append({
            'local_interface': interface,
            'remote_device': current_neighbor.get('remote_device'),
            'remote_port': current_neighbor.get('remote_port')
        })
    
    return neighbors


def parse_lldp_table_format(lines: list) -> list:
    """
    解析表格格式的LLDP输出（如华为的 display lldp neighbor brief）
    :param lines: 输出行列表
    :return: 解析后的邻居列表
    """
    neighbors = []
    
    # 找到表头位置，确定各列的起始位置
    header = lines[0]
    
    # 查找各列的位置
    local_intf_start = 0
    neighbor_dev_start = header.find("Neighbor Dev")
    neighbor_intf_start = header.find("Neighbor Intf")
    exptime_start = header.find("Exptime")
    
    # 从第二行开始解析数据
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        
        # 提取本地接口
        if neighbor_dev_start > 0:
            local_intf = line[:neighbor_dev_start].strip()
        else:
            local_intf = ""
        
        # 提取邻居设备名
        if neighbor_dev_start > 0 and neighbor_intf_start > 0:
            remote_device = line[neighbor_dev_start:neighbor_intf_start].strip()
        elif neighbor_dev_start > 0:
            remote_device = line[neighbor_dev_start:].strip()
        else:
            remote_device = ""
        
        # 提取邻居接口
        if neighbor_intf_start > 0 and exptime_start > 0:
            remote_port = line[neighbor_intf_start:exptime_start].strip()
        elif neighbor_intf_start > 0:
            remote_port = line[neighbor_intf_start:].strip()
        else:
            remote_port = ""
        
        if local_intf and remote_device:
            neighbors.append({
                'local_interface': local_intf,
                'remote_device': remote_device,
                'remote_port': remote_port
            })
    
    return neighbors
