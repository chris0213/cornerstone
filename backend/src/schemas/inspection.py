from pydantic import BaseModel
from datetime import datetime
from typing import List, Dict, Optional, Any


class InspectionTaskCreate(BaseModel):
    """创建巡检任务"""
    name: str
    scan_type: Optional[str] = "full"
    is_enabled: Optional[bool] = True
    cron_expr: Optional[str] = "0 */4 * * *"
    
    # 扫描目标（三选一）
    target_type: Optional[str] = "all_devices"
    site_id: Optional[int] = None
    ip_range: Optional[str] = None
    
    # SNMP配置
    snmp_community: Optional[str] = "public"
    snmp_version: Optional[str] = "v2c"
    snmp_timeout: Optional[int] = 3
    snmp_retries: Optional[int] = 1
    
    # TCP探测配置
    tcp_ports: Optional[List[int]] = [22, 80, 443, 445, 3389]
    tcp_timeout_ms: Optional[int] = 2000
    
    # 并发控制
    max_concurrent: Optional[int] = 50
    
    # 告警配置
    alert_on_offline: Optional[bool] = True
    alert_on_new_device: Optional[bool] = True
    alert_on_fingerprint_change: Optional[bool] = True


class InspectionTaskUpdate(BaseModel):
    """更新巡检任务"""
    name: Optional[str] = None
    scan_type: Optional[str] = None
    is_enabled: Optional[bool] = None
    cron_expr: Optional[str] = None
    
    # 扫描目标
    target_type: Optional[str] = None
    site_id: Optional[int] = None
    ip_range: Optional[str] = None
    
    # SNMP配置
    snmp_community: Optional[str] = None
    snmp_version: Optional[str] = None
    snmp_timeout: Optional[int] = None
    snmp_retries: Optional[int] = None
    
    # TCP探测配置
    tcp_ports: Optional[List[int]] = None
    tcp_timeout_ms: Optional[int] = None
    
    # 并发控制
    max_concurrent: Optional[int] = None
    
    # 告警配置
    alert_on_offline: Optional[bool] = None
    alert_on_new_device: Optional[bool] = None
    alert_on_fingerprint_change: Optional[bool] = None


class InspectionTaskResponse(BaseModel):
    """巡检任务响应"""
    id: int
    name: str
    scan_type: str
    is_enabled: bool
    cron_expr: str
    
    # 扫描目标
    target_type: str
    site_id: Optional[int]
    ip_range: Optional[str]
    
    # SNMP配置
    snmp_community: str
    snmp_version: str
    snmp_timeout: int
    snmp_retries: int
    
    # TCP探测配置
    tcp_ports: List[int]
    tcp_timeout_ms: int
    
    # 并发控制
    max_concurrent: int
    
    # 告警配置
    alert_on_offline: bool
    alert_on_new_device: bool
    alert_on_fingerprint_change: bool
    
    # 执行记录
    last_run_at: Optional[datetime]
    last_run_status: Optional[str]
    
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class InspectionResultResponse(BaseModel):
    """巡检结果响应"""
    id: int
    task_id: int
    scan_type: str
    trigger: str
    operator: str
    status: str
    total_targets: int
    online_count: int
    offline_count: int
    new_device_count: int
    change_count: int
    error_message: Optional[str]
    started_at: datetime
    finished_at: Optional[datetime]
    duration_seconds: Optional[float]
    ai_summary: Optional[Any] = None

    class Config:
        from_attributes = True


class DeviceFingerprintResponse(BaseModel):
    """设备指纹响应"""
    id: int
    ip_address: str
    device_id: Optional[int]
    sys_descr: Optional[str]
    sys_name: Optional[str]
    sys_object_id: Optional[str]
    sys_location: Optional[str]
    vendor: Optional[str]
    last_seen_online: Optional[datetime] = None
    last_full_scan_at: Optional[datetime] = None
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class InspectionDeviceResultResponse(BaseModel):
    """单设备巡检结果响应"""
    id: int
    result_id: int
    ip_address: str
    device_id: Optional[int]
    is_online: bool
    detection_method: str
    open_ports: Optional[List[int]]
    
    # SNMP采集结果
    sys_descr: Optional[str]
    sys_name: Optional[str]
    sys_object_id: Optional[str]
    sys_up_time: Optional[int]
    sys_location: Optional[str]
    vendor: Optional[str]
    cpu_usage: Optional[float]
    memory_usage: Optional[float]
    
    # 变更检测
    is_new_device: bool
    has_fingerprint_change: bool
    change_detail: Optional[Dict[str, List[str]]]
    
    # 执行信息
    scan_duration_ms: int
    error_message: Optional[str]
    scanned_at: datetime
    
    class Config:
        from_attributes = True


class AlertCountResponse(BaseModel):
    """告警统计响应"""
    total: int = 0
    unresolved: int = 0
    new_device: int = 0
    missing_device: int = 0
    changed_device: int = 0
