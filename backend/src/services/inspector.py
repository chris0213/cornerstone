import asyncio
import logging
import socket
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from ipaddress import IPv4Network, ip_address
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.models import (
    InspectionTask,
    InspectionResult,
    InspectionDeviceResult,
    DeviceFingerprint,
    Device,
    IPAddress,
    AlertRecord
)

logger = logging.getLogger("cornerstone")

# MIB-II 通用 OID（所有品牌）
MIB2_OIDS = {
    "sys_descr": "1.3.6.1.2.1.1.1.0",
    "sys_object_id": "1.3.6.1.2.1.1.2.0",
    "sys_up_time": "1.3.6.1.2.1.1.3.0",
    "sys_name": "1.3.6.1.2.1.1.5.0",
    "sys_location": "1.3.6.1.2.1.1.6.0",
}

# 厂商识别：sysObjectID 前缀 → 厂商名
VENDOR_OID_MAP = {
    "1.3.6.1.4.1.9": "cisco",
    "1.3.6.1.4.1.2011": "huawei",
    "1.3.6.1.4.1.25506": "h3c",
    "1.3.6.1.4.1.2636": "juniper",
    "1.3.6.1.4.1.12356": "fortinet",
}

# 厂商私有 OID（CPU/内存）
VENDOR_PERF_OIDS = {
    "cisco": {
        "cpu_usage": "1.3.6.1.4.1.9.2.1.56.0",
        "memory_usage": "1.3.6.1.4.1.9.9.48.1.1.1.5.1",
    },
    "huawei": {
        "cpu_usage": "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.5.1",
        "memory_usage": "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.7.1",
    },
    "h3c": {
        "cpu_usage": "1.3.6.1.4.1.25506.2.6.1.1.1.1.6.1",
        "memory_usage": "1.3.6.1.4.1.25506.2.6.1.1.1.1.8.1",
    },
    "juniper": {
        "cpu_usage": "1.3.6.1.4.1.2636.3.1.13.1.8.1.1.0",
        "memory_usage": "1.3.6.1.4.1.2636.3.1.13.1.11.1.1.0",
    },
    "fortinet": {
        "cpu_usage": "1.3.6.1.4.1.12356.101.4.1.3.0",
        "memory_usage": "1.3.6.1.4.1.12356.101.4.1.4.0",
    },
}


class ProbeResult:
    """探活结果"""
    def __init__(self):
        self.is_online: bool = False
        self.method: str = "none"
        self.open_ports: List[int] = []
        self.duration_ms: int = 0


class SNMPResult:
    """SNMP采集结果"""
    def __init__(self):
        self.sys_descr: Optional[str] = None
        self.sys_object_id: Optional[str] = None
        self.sys_up_time: Optional[int] = None
        self.sys_name: Optional[str] = None
        self.sys_location: Optional[str] = None
        self.vendor: str = "unknown"
        self.cpu_usage: Optional[float] = None
        self.memory_usage: Optional[float] = None


class ChangeDetail:
    """指纹变更详情"""
    def __init__(self):
        self.has_change: bool = False
        self.changed_fields: Dict[str, List[str]] = {}


class InspectorService:
    """智能巡检核心服务"""

    @staticmethod
    async def probe_online(ip: str, tcp_ports: List[int], timeout_ms: int) -> ProbeResult:
        """
        多维度探活：ICMP + TCP
        返回：{ is_online, method, open_ports, duration_ms }
        
        执行顺序：
        1. ICMP Ping（ping3，超时1秒）
        2. 若ICMP失败，并发探测所有TCP端口（asyncio + socket）
        3. 任意方式成功 → is_online=True
        
        注意：
        - ICMP 和 TCP 并发执行（不串行），取最快响应
        - Windows禁Ping时依靠TCP 445/3389判定在线
        - 所有异常静默捕获，不抛出，保证单IP失败不影响整体
        """
        result = ProbeResult()
        start_time = datetime.now()
        
        async def icmp_ping():
            try:
                proc = await asyncio.create_subprocess_exec(
                    "ping", "-c", "1", "-W", "1", ip,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                _, _ = await proc.communicate()
                if proc.returncode == 0:
                    result.is_online = True
                    result.method = "icmp"
            except Exception:
                pass
        
        async def tcp_probe(port: int):
            try:
                timeout = timeout_ms / 1000
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip, port),
                    timeout=timeout
                )
                writer.close()
                await writer.wait_closed()
                if port not in result.open_ports:
                    result.open_ports.append(port)
                if not result.is_online:
                    result.is_online = True
                    result.method = "tcp"
            except Exception:
                pass
        
        # 并发执行ICMP和TCP探测
        tasks = [icmp_ping()]
        for port in tcp_ports:
            tasks.append(tcp_probe(port))
        
        await asyncio.gather(*tasks)
        
        duration = datetime.now() - start_time
        result.duration_ms = int(duration.total_seconds() * 1000)
        
        return result

    @staticmethod
    async def snmp_get(ip: str, oids: Dict[str, str], community: str,
                      version: str, timeout: int, retries: int) -> Dict[str, Any]:
        """
        SNMP GET 查询，使用 snmpget 命令
        返回：{ oid_key: value, ... }，查询失败的 OID 值为 None
        不抛出异常，所有错误返回空字典
        
        注意：
        - 使用系统 snmpget 命令（可以一次查询多个 OID）
        - -On 参数输出数字 OID
        - v2c 使用 CommunityData
        - OID 解析：sysUpTime 转换为秒数（原始值为 1/100 秒）
        """
        result = {}
        
        # 转换版本号：前端传 "v2c"，snmpget 需要 "2c"
        snmp_version = version.lstrip('v') if version.startswith('v') else version
        
        try:
            oid_list = list(oids.values())
            # 使用 snmpget 而不是 snmpwalk，可以一次获取多个指定 OID
            # -On 参数强制输出数字 OID
            cmd = [
                "snmpget", "-On", "-v", snmp_version, "-c", community,
                "-t", str(timeout), "-r", str(retries),
                ip
            ] + oid_list
            
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            # 调试日志
            import logging
            logger = logging.getLogger("cornerstone")
            logger.info(f"SNMP GET {ip}: 版本={snmp_version}, 返回码={proc.returncode}")
            if stdout:
                logger.info(f"SNMP GET {ip}: stdout={stdout.decode('utf-8', errors='ignore')[:200]}")
            if stderr:
                logger.warning(f"SNMP GET {ip}: stderr={stderr.decode('utf-8', errors='ignore')[:200]}")
            
            if stdout:
                lines = stdout.decode('utf-8', errors='ignore').split('\n')
                oid_key_map = {v: k for k, v in oids.items()}
                
                # 合并多行输出（sysDescr 可能跨多行）
                merged_lines = []
                current_line = ""
                for line in lines:
                    if line.strip().startswith('.1.') and '=' in line:
                        # 新的 OID 行
                        if current_line:
                            merged_lines.append(current_line)
                        current_line = line
                    elif line.strip() and current_line:
                        #  continuation line
                        current_line += " " + line.strip()
                if current_line:
                    merged_lines.append(current_line)
                
                for line in merged_lines:
                    if '=' in line:
                        parts = line.split('=', 1)
                        if len(parts) == 2:
                            oid_part = parts[0].strip()
                            value = parts[1].strip()
                            
                            # 移除 SNMP 类型前缀（STRING:, OID:, Timeticks:, INTEGER: 等）
                            if ':' in value:
                                value = value.split(':', 1)[1].strip()
                            
                            # 移除值的引号
                            value = value.strip('"')
                            
                            # 查找匹配的 OID（使用完整 OID 匹配）
                            # 注意：snmpget -On 输出 OID 前面可能有点（.1.3.6.1.2.1.1.1.0）
                            for oid, key in oid_key_map.items():
                                # 匹配完整 OID 或带前导点的 OID
                                if oid in oid_part or oid_part.lstrip('.') == oid.lstrip('.'):
                                    if key == "sys_up_time" and "Timeticks" in parts[1]:
                                        # 解析 Timeticks: (75273004) 8 days, 17:05:30.04
                                        try:
                                            time_value = value.split('(')[1].split(')')[0]
                                            result[key] = int(time_value) // 100
                                        except:
                                            pass
                                    elif key == "sys_up_time" and value.isdigit():
                                        result[key] = int(value) // 100  # 转换为秒
                                    elif key == "sys_object_id":
                                        # 移除 OID 值前面的点
                                        result[key] = value.lstrip('.')
                                    else:
                                        result[key] = value
                                    break
        except Exception as e:
            import logging
            logger = logging.getLogger("cornerstone")
            logger.error(f"SNMP GET {ip}: 异常={str(e)}")
            pass
        
        return result

    @staticmethod
    def identify_vendor(sys_object_id: str) -> str:
        """
        根据 sysObjectID 识别厂商
        遍历 VENDOR_OID_MAP，匹配前缀
        未匹配返回 "unknown"
        """
        for oid_prefix, vendor in VENDOR_OID_MAP.items():
            if sys_object_id.startswith(oid_prefix):
                return vendor
        return "unknown"

    @staticmethod
    async def collect_device_snmp(ip: str, community: str, version: str,
                                  timeout: int, retries: int) -> SNMPResult:
        """
        全量扫描的SNMP采集主函数：
        1. 采集 MIB2_OIDS（通用，必须）
        2. 解析 sysObjectID 识别厂商
        3. 若厂商已知，尝试采集 VENDOR_PERF_OIDS（失败不报错，cpu/memory置None）
        4. 返回完整结果
        """
        result = SNMPResult()
        
        # 第一步：采集 MIB2_OIDS
        mib2_result = await InspectorService.snmp_get(
            ip, MIB2_OIDS, community, version, timeout, retries
        )
        
        result.sys_descr = mib2_result.get("sys_descr")
        result.sys_object_id = mib2_result.get("sys_object_id")
        result.sys_up_time = mib2_result.get("sys_up_time")
        result.sys_name = mib2_result.get("sys_name")
        result.sys_location = mib2_result.get("sys_location")
        
        # 第二步：识别厂商
        if result.sys_object_id:
            result.vendor = InspectorService.identify_vendor(result.sys_object_id)
        
        # 第三步：尝试采集厂商私有OID
        if result.vendor in VENDOR_PERF_OIDS:
            perf_oids = VENDOR_PERF_OIDS[result.vendor]
            perf_result = await InspectorService.snmp_get(
                ip, perf_oids, community, version, timeout, retries
            )
            
            # 处理CPU使用率
            if perf_result.get("cpu_usage"):
                try:
                    value = float(perf_result["cpu_usage"])
                    # 不同厂商返回值类型不同，统一转换为百分比
                    if value > 100:
                        value = value / 100 if value < 10000 else value / 1000
                    result.cpu_usage = min(value, 100.0)
                except ValueError:
                    pass
            
            # 处理内存使用率
            if perf_result.get("memory_usage"):
                try:
                    value = float(perf_result["memory_usage"])
                    if value > 100:
                        value = value / 100 if value < 10000 else value / 1000
                    result.memory_usage = min(value, 100.0)
                except ValueError:
                    pass
        
        return result

    @staticmethod
    async def detect_fingerprint_change(ip: str, new_result: SNMPResult,
                                        db: AsyncSession) -> ChangeDetail:
        """
        与 device_fingerprints 表中上次记录对比：
        对比字段：sys_descr / sys_name / sys_object_id / sys_location / vendor
        返回：{ has_change: bool, changed_fields: { field: [old_val, new_val] } }
        """
        result = ChangeDetail()
        
        # 查询现有指纹
        existing_result = await db.execute(
            select(DeviceFingerprint).where(DeviceFingerprint.ip_address == ip)
        )
        existing = existing_result.scalar_one_or_none()
        
        if not existing:
            return result
        
        # 对比各字段
        compare_fields = [
            ("sys_descr", existing.sys_descr, new_result.sys_descr),
            ("sys_name", existing.sys_name, new_result.sys_name),
            ("sys_object_id", existing.sys_object_id, new_result.sys_object_id),
            ("sys_location", existing.sys_location, new_result.sys_location),
            ("vendor", existing.vendor, new_result.vendor),
        ]
        
        for field_name, old_val, new_val in compare_fields:
            if old_val != new_val:
                result.has_change = True
                result.changed_fields[field_name] = [str(old_val) if old_val else None, str(new_val) if new_val else None]
        
        return result

    @staticmethod
    def parse_ip_target(target: str) -> List[str]:
        """解析IP目标，支持单个IP、CIDR网段"""
        ips = []
        
        # 尝试解析为CIDR网段（如 192.0.2.0/24）
        try:
            network = IPv4Network(target, strict=False)
            for ip in network.hosts():
                ips.append(str(ip))
            return ips
        except ValueError:
            pass
        
        # 默认作为单个IP处理
        try:
            ip_address(target)
            ips.append(target)
        except ValueError:
            pass
        
        return ips

    @staticmethod
    async def build_target_ips(task: InspectionTask, db: AsyncSession) -> List[str]:
        """根据任务配置生成目标IP列表"""
        target_ips = []
        
        if task.target_type == "all_devices":
            # 获取所有设备的管理IP
            result = await db.execute(
                select(IPAddress.address)
                .join(Device, Device.mgmt_ip_id == IPAddress.id)
                .where(Device.status.in_(["active", "在线", "Online", "online"]))
            )
            target_ips = [ip for ip in result.scalars().all() if ip]
        
        elif task.target_type == "site":
            # 获取指定站点下所有设备的管理IP
            if task.site_id:
                result = await db.execute(
                    select(IPAddress.address)
                    .join(Device, Device.mgmt_ip_id == IPAddress.id)
                    .where(Device.site_id == task.site_id)
                    .where(Device.status.in_(["active", "在线", "Online", "online"]))
                )
                target_ips = [ip for ip in result.scalars().all() if ip]
        
        elif task.target_type == "ip_range":
            # 解析指定的IP范围
            if task.ip_range:
                target_ips = InspectorService.parse_ip_target(task.ip_range)
        
        return target_ips

    @staticmethod
    async def process_alerts(device_result: InspectionDeviceResult,
                             task: InspectionTask, db: AsyncSession):
        """
        每台设备扫描完后的告警处理：
        1. 设备离线告警（alert_on_offline=True）：
            - 查 device_fingerprints，上次在线但本次离线 → 写告警
            - 告警级别：warning
            - 告警内容：「设备 {device_name}（{ip}）已离线，上次在线：{last_seen}」
        2. 新设备发现告警（alert_on_new_device=True）：
            - 该IP不在 devices 表也不在 device_fingerprints 表 → 写告警
            - 告警级别：info
            - 告警内容：「发现未登记设备，IP：{ip}，系统描述：{sys_descr}」
        3. 指纹变更告警（alert_on_fingerprint_change=True）：
            - has_fingerprint_change=True → 写告警
            - 告警级别：warning
            - 告警内容：「设备 {device_name}（{ip}）指纹变更：{changed_fields}」
        """
        alerts = []
        
        if not device_result.is_online and task.alert_on_offline:
            # 检查是否是已知在线设备
            fp_result = await db.execute(
                select(DeviceFingerprint)
                .where(DeviceFingerprint.ip_address == device_result.ip_address)
            )
            fingerprint = fp_result.scalar_one_or_none()
            
            if fingerprint and fingerprint.last_seen_online:
                device_name = fingerprint.sys_name or "未知设备"
                alerts.append(AlertRecord(
                    rule_id=None,
                    device_id=device_result.device_id,
                    target_ip=device_result.ip_address,
                    alert_type="inspection_offline",
                    severity="warning",
                    message=f"设备 {device_name}（{device_result.ip_address}）已离线，上次在线：{fingerprint.last_seen_online}",
                    status="active",
                    created_at=datetime.now()
                ))
        
        if device_result.is_new_device and task.alert_on_new_device:
            sys_descr = device_result.sys_descr or "未知"
            alerts.append(AlertRecord(
                rule_id=None,
                device_id=device_result.device_id,
                target_ip=device_result.ip_address,
                alert_type="inspection_new_device",
                severity="info",
                message=f"发现未登记设备，IP：{device_result.ip_address}，系统描述：{sys_descr}",
                status="active",
                created_at=datetime.now()
            ))
        
        if device_result.has_fingerprint_change and task.alert_on_fingerprint_change:
            changed_fields = device_result.change_detail or {}
            field_names = ", ".join(changed_fields.keys())
            device_name = device_result.sys_name or "未知设备"
            alerts.append(AlertRecord(
                rule_id=None,
                device_id=device_result.device_id,
                target_ip=device_result.ip_address,
                alert_type="inspection_fingerprint_change",
                severity="warning",
                message=f"设备 {device_name}（{device_result.ip_address}）指纹变更：{field_names}",
                status="active",
                created_at=datetime.now()
            ))
        
        if alerts:
            db.add_all(alerts)

    @staticmethod
    async def run_inspection(task: InspectionTask, trigger: str,
                             operator: str, db: AsyncSession,
                             ws_callback=None) -> InspectionResult:
        """
        巡检执行主函数：
        1. 根据 target_type 生成目标IP列表：
            all_devices → 查 devices 表所有 mgmt_ip
            site        → 查指定站点下所有设备的 mgmt_ip
            ip_range    → 枚举网段内所有IP（ipaddress.ip_network）
        2. 创建 InspectionResult 记录（status=running）
        3. 使用 asyncio.Semaphore(max_concurrent) 并发扫描
        4. 每扫描完一台设备：
            - 写入 InspectionDeviceResult
            - 若 ws_callback 不为空，推送实时进度
            - 处理告警逻辑
        5. 全量扫描时更新 device_fingerprints 表
        6. 更新 InspectionResult 为最终状态
        """
        start_time = datetime.now()
        
        # 生成目标IP列表
        target_ips = await InspectorService.build_target_ips(task, db)
        
        if not target_ips:
            raise ValueError("未找到扫描目标")
        
        # 创建巡检记录
        inspection_result = InspectionResult(
            task_id=task.id,
            scan_type=task.scan_type,
            trigger=trigger,
            operator=operator,
            status="running",
            total_targets=len(target_ips),
            started_at=start_time
        )
        db.add(inspection_result)
        await db.commit()
        await db.refresh(inspection_result)
        
        # 并发控制
        semaphore = asyncio.Semaphore(task.max_concurrent)
        
        # 统计变量
        online_count = 0
        offline_count = 0
        new_device_count = 0
        change_count = 0
        scanned_count = 0
        
        # 用于存储全量扫描的 SNMP 结果，扫描完成后统一更新指纹
        snmp_results_cache = {}
        
        tcp_ports = task.tcp_ports if isinstance(task.tcp_ports, list) else [22, 80, 443, 445, 3389]
        
        async def scan_device(ip: str):
            nonlocal online_count, offline_count, new_device_count, change_count, scanned_count
            
            async with semaphore:
                start = datetime.now()
                device_result = InspectionDeviceResult(
                    result_id=inspection_result.id,
                    ip_address=ip,
                    is_online=False,
                    detection_method="none",
                    scanned_at=datetime.now()
                )
                
                try:
                    # 第一步：探活检测
                    probe_result = await InspectorService.probe_online(ip, tcp_ports, task.tcp_timeout_ms)
                    
                    if probe_result.is_online:
                        device_result.is_online = True
                        device_result.detection_method = probe_result.method
                        device_result.open_ports = probe_result.open_ports
                        online_count += 1
                        
                        if task.scan_type == "full":
                            # 第二步：全量扫描 - SNMP 采集
                            snmp_result = await InspectorService.collect_device_snmp(
                                ip, task.snmp_community, task.snmp_version,
                                task.snmp_timeout, task.snmp_retries
                            )
                            
                            device_result.sys_descr = snmp_result.sys_descr
                            device_result.sys_name = snmp_result.sys_name
                            device_result.sys_object_id = snmp_result.sys_object_id
                            device_result.sys_up_time = snmp_result.sys_up_time
                            device_result.sys_location = snmp_result.sys_location
                            device_result.vendor = snmp_result.vendor
                            device_result.cpu_usage = snmp_result.cpu_usage
                            device_result.memory_usage = snmp_result.memory_usage
                            
                            # 缓存 SNMP 结果，稍后统一更新指纹
                            snmp_results_cache[ip] = snmp_result
                        else:
                            # 快速扫描：只记录在线状态
                            pass
                    else:
                        offline_count += 1
                    
                except Exception as e:
                    device_result.error_message = str(e)
                
                # 计算扫描耗时
                duration = datetime.now() - start
                device_result.scan_duration_ms = int(duration.total_seconds() * 1000)
                
                # 写入设备扫描结果
                db.add(device_result)
                scanned_count += 1
                
                # 推送实时进度
                if ws_callback:
                    progress_data = {
                        "type": "progress",
                        "total": len(target_ips),
                        "scanned": scanned_count,
                        "online": online_count,
                        "offline": offline_count,
                        "percent": (scanned_count / len(target_ips)) * 100,
                        "current_ip": ip
                    }
                    await ws_callback(progress_data)
        
        # 并发扫描所有设备
        tasks = [scan_device(ip) for ip in target_ips]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        # 批量提交所有设备扫描结果
        try:
            await db.commit()
        except Exception as e:
            # 如果提交失败，回滚并记录错误
            await db.rollback()
            inspection_result.status = "failed"
            inspection_result.error_message = f"批量提交失败：{str(e)}"
            await db.commit()
            return inspection_result
        
        # 全量扫描：在扫描完成后统一处理指纹更新和变更检测
        if task.scan_type == "full" and snmp_results_cache:
            for ip, snmp_result in snmp_results_cache.items():
                try:
                    # 检测指纹变更
                    change_detail = await InspectorService.detect_fingerprint_change(ip, snmp_result, db)
                    if change_detail.has_change:
                        change_count += 1
                    
                    # 检查是否是新设备
                    fp_result = await db.execute(
                        select(DeviceFingerprint)
                        .where(DeviceFingerprint.ip_address == ip)
                    )
                    if not fp_result.scalar_one_or_none():
                        new_device_count += 1
                    
                    # 更新或创建设备指纹
                    await InspectorService._update_fingerprint(db, ip, snmp_result)
                except Exception as e:
                    # 记录错误但不影响整体流程
                    pass
            
            # 提交指纹更新
            await db.commit()
        
        # 处理告警（在指纹更新后）
        if task.scan_type == "full":
            # 重新查询设备结果以处理告警
            device_results = await db.execute(
                select(InspectionDeviceResult)
                .where(InspectionDeviceResult.result_id == inspection_result.id)
            )
            for device_result in device_results.scalars().all():
                try:
                    await InspectorService.process_alerts(device_result, task, db)
                except Exception as e:
                    logger.warning(
                        f"[巡检告警] device={device_result.ip_address} process_alerts 失败，"
                        f"跳过该设备（不影响巡检主流程）: {e}"
                    )
            await db.commit()
        
        # AI 二次研判（默认关闭，需在 settings.ai_inspection_settings 开启；快速与全量扫描均执行，不影响主流程）
        await InspectorService.run_ai_secondary_analysis(inspection_result, db)

        # 更新巡检记录最终状态
        end_time = datetime.now()
        duration_seconds = (end_time - start_time).total_seconds()
        
        if offline_count == 0:
            status = "success"
        elif online_count > 0:
            status = "partial_fail"
        else:
            status = "failed"
        
        inspection_result.status = status
        inspection_result.online_count = online_count
        inspection_result.offline_count = offline_count
        inspection_result.new_device_count = new_device_count
        inspection_result.change_count = change_count
        inspection_result.finished_at = end_time
        inspection_result.duration_seconds = duration_seconds
        
        await db.commit()
        
        # 推送完成消息
        if ws_callback:
            await ws_callback({
                "type": "done",
                "total": len(target_ips),
                "online": online_count,
                "offline": offline_count,
                "new_devices": new_device_count,
                "changes": change_count,
                "duration_seconds": duration_seconds
            })
        
        return inspection_result

    @staticmethod
    async def run_ai_secondary_analysis(inspection_result: InspectionResult, db: AsyncSession):
        """巡检 AI 二次研判（可选能力，默认关闭）

        仅当 settings 表 key='ai_inspection_settings' 且 {"enabled": true} 时执行；
        且需要 AI 配置已就绪（api_key 与 api_base 均非空）。任何缺失或异常均直接返回，
        绝不抛出、绝不写入 ai_summary、绝不影响巡检主流程。
        """
        try:
            import json
            from src.models.setting import Setting
            from src.services.ai_client import get_ai_config, call_ai
            from src.services.ai_outbound_guard import is_external_blocked, mask_outbound_text

            # 1. 读取开关，默认关闭（缺记录/解析失败均视为关闭，不调用任何 AI）
            switch_result = await db.execute(
                select(Setting).filter(Setting.key == "ai_inspection_settings")
            )
            switch_setting = switch_result.scalars().first()
            enabled = False
            if switch_setting:
                try:
                    cfg = json.loads(switch_setting.value)
                    enabled = bool(cfg.get("enabled", False))
                except (json.JSONDecodeError, AttributeError, TypeError):
                    enabled = False
            if not enabled:
                return

            # 2. AI 配置缺失或未就绪则直接返回（不报错）
            ai_config = await get_ai_config(db)
            if not ai_config or not ai_config.is_configured():
                return

            # 2.5 禁止外发开关开启时跳过二次研判（巡检明细不外发）
            if await is_external_blocked(db):
                logger.info("[巡检AI二次研判] 禁止外发开关已开启，跳过")
                return

            # 3. 构造异常明细快照（对条数做上限截断，避免 prompt 过大）
            device_rows = await db.execute(
                select(InspectionDeviceResult)
                .where(InspectionDeviceResult.result_id == inspection_result.id)
            )
            anomaly_details = []
            for dr in device_rows.scalars().all():
                if dr.is_online is False:
                    anomaly_details.append(f"离线设备 {dr.ip_address}（{dr.sys_name or ''}）")
                elif dr.is_new_device:
                    anomaly_details.append(f"新发现设备 {dr.ip_address}（{dr.sys_name or ''}）")
                elif dr.has_fingerprint_change:
                    anomaly_details.append(f"指纹变更 {dr.ip_address}")
                elif (dr.cpu_usage is not None and dr.cpu_usage >= 80) or (
                    dr.memory_usage is not None and dr.memory_usage >= 80
                ):
                    anomaly_details.append(
                        f"资源偏高 {dr.ip_address} CPU={dr.cpu_usage} 内存={dr.memory_usage}"
                    )
                elif dr.error_message:
                    anomaly_details.append(f"扫描报错 {dr.ip_address}: {dr.error_message}")
            if len(anomaly_details) > 30:
                anomaly_details = anomaly_details[:30]

            stats = (
                f"在线: {inspection_result.online_count} 台, "
                f"离线: {inspection_result.offline_count} 台, "
                f"新发现设备: {inspection_result.new_device_count} 台, "
                f"指纹变更: {inspection_result.change_count} 台"
            )
            # 明细发 LLM 前脱敏（IP 为巡检主体保留明文，其余值如邮箱/MAC/SN 脱敏）
            detail_text = "\n".join(
                f"{i + 1}. {mask_outbound_text(d)}" for i, d in enumerate(anomaly_details)
            ) or "无异常明细"

            prompt = (
                f"以下是一次网络设备巡检的执行结果，请进行二次研判。\n\n"
                f"巡检统计：\n{stats}\n\n"
                f"异常明细（最多 30 条）：\n{detail_text}\n\n"
                f"请输出：\n1. 整体健康评估\n2. 重点风险点\n3. 处置建议"
            )
            system = (
                "你是一位资深的 IT 基础设施运维专家，擅长网络设备、服务器、存储等基础设施的巡检研判。"
                "请基于巡检数据给出专业、准确、简洁的二次研判结论。"
            )

            # 4. 调用 AI
            analysis_text = await call_ai(prompt, system, ai_config, max_tokens=1500, timeout=20)

            # 5. 写入 ai_summary（仅取 AIConfig 真实存在的模型字段名）
            summary = {
                "analysis": analysis_text,
                "generated_at": datetime.now().isoformat(),
            }
            model = getattr(ai_config, "model", None)
            if model:
                summary["model"] = model
            inspection_result.ai_summary = summary
            await db.flush()

            logger.info(
                f"[巡检AI二次研判] result_id={inspection_result.id} 完成，结果已写入 ai_summary"
            )
        except Exception as e:
            import traceback
            logger.warning(
                f"[巡检AI二次研判] result_id={inspection_result.id} 失败（不影响巡检主流程）: {e}\n"
                f"{traceback.format_exc()}"
            )

    @staticmethod
    async def _update_fingerprint(db: AsyncSession, ip: str, snmp_result: SNMPResult):
        """更新或创建设备指纹"""
        result = await db.execute(
            select(DeviceFingerprint).where(DeviceFingerprint.ip_address == ip)
        )
        existing = result.scalar_one_or_none()
        
        fingerprint_data = {
            "ip_address": ip,
            "sys_descr": snmp_result.sys_descr or "",
            "sys_name": snmp_result.sys_name or "",
            "sys_object_id": snmp_result.sys_object_id or "",
            "sys_location": snmp_result.sys_location or "",
            "vendor": snmp_result.vendor or "unknown",
            "last_seen_online": datetime.now(),
            "last_full_scan_at": datetime.now()
        }
        
        if existing:
            # 更新现有记录
            for key, value in fingerprint_data.items():
                setattr(existing, key, value)
            # 刷新对象，确保状态同步
            await db.flush()
        else:
            # 创建新记录
            db.add(DeviceFingerprint(**fingerprint_data))
            # 刷新对象，确保状态同步
            await db.flush()
