import subprocess
import platform
import asyncio
from typing import Tuple, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.models.device import Device
from src.models.link_monitor import LinkMonitor
from src.models.ip_address import IPAddress


async def ping_host(target_ip: str, count: int = 4, timeout: int = 5) -> Tuple[Optional[float], Optional[float]]:
    """
    执行 ping 命令检测延迟和丢包率
    
    返回：(延迟(ms), 丢包率(0-100))
    """
    try:
        # 根据操作系统选择不同的 ping 参数
        if platform.system().lower() == 'windows':
            command = ['ping', '-n', str(count), '-w', str(timeout * 1000), target_ip]
        else:
            command = ['ping', '-c', str(count), '-W', str(timeout), target_ip]
        
        # 使用 subprocess 执行命令
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            return parse_ping_output(stdout.decode('utf-8'), count)
        else:
            # ping 命令返回非零值，可能是丢包或其他错误
            return parse_ping_output(stdout.decode('utf-8'), count)
    
    except Exception as e:
        print(f"Ping error: {e}")
        return (None, None)


def parse_ping_output(output: str, count: int) -> Tuple[Optional[float], Optional[float]]:
    """
    解析 ping 命令输出
    
    Linux/macOS 输出示例:
    --- 192.0.2.1 ping statistics ---
    4 packets transmitted, 4 received, 0% packet loss, time 3003ms
    rtt min/avg/max/mdev = 1.234/2.345/3.456/0.567 ms
    
    Windows 输出示例:
    Ping statistics for 192.0.2.1:
        Packets: Sent = 4, Received = 4, Lost = 0 (0% loss),
    Approximate round trip times in milli-seconds:
        Minimum = 1ms, Maximum = 3ms, Average = 2ms
    """
    latency = None
    packet_loss = None
    
    lines = output.strip().split('\n')
    
    for line in lines:
        # 解析丢包率
        if 'packet loss' in line.lower() or 'Lost' in line:
            try:
                # Linux/macOS: "0% packet loss"
                if '%' in line:
                    import re
                    match = re.search(r'(\d+)%.*loss', line)
                    if match:
                        packet_loss = float(match.group(1))
                # Windows: "Lost = 0 (0% loss)"
                else:
                    import re
                    match = re.search(r'Lost = (\d+)', line)
                    if match:
                        lost = int(match.group(1))
                        packet_loss = (lost / count) * 100
            except:
                pass
        
        # 解析延迟
        if 'avg' in line.lower() or 'Average' in line:
            try:
                import re
                # Linux/macOS: "rtt min/avg/max/mdev = 1.234/2.345/3.456/0.567 ms"
                if '=' in line and '/' in line:
                    parts = line.split('=')[-1].strip().split('/')
                    if len(parts) >= 2:
                        latency = float(parts[1])
                # Windows: "Average = 2ms"
                else:
                    match = re.search(r'Average = (\d+)ms', line)
                    if match:
                        latency = float(match.group(1))
            except:
                pass
    
    return (latency, packet_loss)


def determine_status(latency: float, packet_loss: float) -> str:
    """
    根据延迟和丢包率确定状态
    
    normal: 延迟 < 100ms, 丢包率 < 5%
    warning: 延迟 100-500ms, 丢包率 5-20%
    critical: 延迟 > 500ms, 丢包率 > 20% 或无法连接
    """
    if latency is None or packet_loss is None:
        return "critical"
    
    if latency > 500 or packet_loss >= 20:
        return "critical"
    elif latency >= 100 or packet_loss >= 5:
        return "warning"
    else:
        return "normal"


async def monitor_device(db: AsyncSession, device: Device) -> None:
    """监控单个设备"""
    try:
        # 获取设备的管理IP
        if device.mgmt_ip_id:
            ip_query = select(IPAddress).where(IPAddress.id == device.mgmt_ip_id)
            ip_result = await db.execute(ip_query)
            ip_addr = ip_result.scalar_one_or_none()

            if ip_addr:
                latency, packet_loss = await ping_host(ip_addr.address)
                status = determine_status(latency, packet_loss)

                # 保存监控数据（不在这里提交，由调用方统一提交）
                monitor_data = LinkMonitor(
                    device_id=device.id,
                    target_ip=ip_addr.address,
                    latency=latency,
                    packet_loss=packet_loss,
                    status=status
                )
                db.add(monitor_data)

                # 采集指标样本（仅当存在 detection_mode='anomaly' 的启用规则时才写入，
                # 默认 static 模式 → 零额外写入，升级后无副作用）
                try:
                    from src.services.alert_service import AlertService
                    await AlertService.collect_metric_samples(db, device.id, latency, packet_loss)
                except Exception as sample_err:
                    print(f"[monitor] 设备 {device.name} 指标采样失败: {sample_err}")

                # 评估告警规则，产生 AlertRecord（修复：接入预警链路）
                from src.services.alert_service import AlertService
                # ping 失败时 latency/packet_loss 可能为 None，规则评估需要数值
                eval_latency = latency if latency is not None else 0
                eval_packet_loss = packet_loss if packet_loss is not None else 100
                try:
                    triggered = await AlertService.evaluate_rules(
                        db,
                        device_id=device.id,
                        target_ip=ip_addr.address,
                        latency=eval_latency,
                        packet_loss=eval_packet_loss,
                        status=status,
                    )
                    if triggered:
                        print(f"[monitor] 设备 {device.name} 触发 {len(triggered)} 条告警")
                except Exception as alert_err:
                    # 告警评估失败不影响监控数据写入
                    print(f"[monitor] 设备 {device.name} 告警评估失败: {alert_err}")

                # 自动恢复：监控恢复正常时关闭该设备活动告警
                if status == "normal":
                    try:
                        await _auto_recover_alerts(db, device.id)
                    except Exception as recover_err:
                        print(f"[monitor] 设备 {device.name} 告警恢复失败: {recover_err}")
    except Exception as e:
        print(f"Error monitoring device {device.name}: {e}")


async def _auto_recover_alerts(db: AsyncSession, device_id: int) -> int:
    """
    自动恢复：设备监控状态恢复正常时，关闭该设备的活动告警。
    返回关闭的告警数量。需由调用方统一 commit。
    """
    from src.models.alert import AlertRecord
    from datetime import datetime

    query = select(AlertRecord).where(
        AlertRecord.device_id == device_id,
        AlertRecord.status == "active",
    )
    result = await db.execute(query)
    active_alerts = result.scalars().all()

    recovered = 0
    for alert in active_alerts:
        alert.status = "resolved"
        alert.resolved_at = datetime.now()
        recovered += 1

    if recovered:
        print(f"[monitor] 设备 {device_id} 自动恢复 {recovered} 条活动告警")
    return recovered


async def run_monitoring_task(db: AsyncSession) -> None:
    """运行监控任务"""
    # 获取所有正常状态的设备
    query = select(Device).where(Device.status != "offline")
    result = await db.execute(query)
    devices = result.scalars().all()
    
    # 并行监控所有设备
    tasks = [monitor_device(db, device) for device in devices]
    await asyncio.gather(*tasks)
    
    # 所有设备监控完成后统一提交事务
    await db.commit()
