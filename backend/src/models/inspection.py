from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Boolean, Float
from sqlalchemy.sql import func

from ..database import Base


class InspectionTask(Base):
    """巡检任务配置"""
    __tablename__ = "inspection_tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    scan_type = Column(String(20), default="full")  # quick / full
    is_enabled = Column(Boolean, default=True)
    cron_expr = Column(String(50), default="0 */4 * * *")
    
    # 扫描目标（三选一）
    target_type = Column(String(20), default="all_devices")  # all_devices / site / ip_range
    site_id = Column(Integer, ForeignKey("sites.id"))
    ip_range = Column(String(50))
    
    # SNMP配置（全量扫描用）
    snmp_community = Column(String(50), default="public")
    snmp_version = Column(String(10), default="v2c")
    snmp_timeout = Column(Integer, default=3)
    snmp_retries = Column(Integer, default=1)
    
    # TCP探测配置
    tcp_ports = Column(JSON, default="[22, 80, 443, 445, 3389]")
    tcp_timeout_ms = Column(Integer, default=2000)
    
    # 并发控制
    max_concurrent = Column(Integer, default=50)
    
    # 告警配置
    alert_on_offline = Column(Boolean, default=True)
    alert_on_new_device = Column(Boolean, default=True)
    alert_on_fingerprint_change = Column(Boolean, default=True)
    
    # 执行记录
    last_run_at = Column(DateTime(timezone=True))
    last_run_status = Column(String(20))  # success / partial_fail / failed
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class InspectionResult(Base):
    """单次巡检执行记录"""
    __tablename__ = "inspection_results"
    
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("inspection_tasks.id"))
    scan_type = Column(String(20))  # quick / full
    trigger = Column(String(20))  # scheduled / manual
    operator = Column(String(50))  # 操作人
    status = Column(String(20), default="running")  # running / success / partial_fail / failed
    total_targets = Column(Integer, default=0)
    online_count = Column(Integer, default=0)
    offline_count = Column(Integer, default=0)
    new_device_count = Column(Integer, default=0)
    change_count = Column(Integer, default=0)
    error_message = Column(String(500))
    
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    duration_seconds = Column(Float)

    ai_summary = Column(JSON, nullable=True, comment="AI异常二次研判结论")


class InspectionDeviceResult(Base):
    """单台设备的巡检结果"""
    __tablename__ = "inspection_device_results"
    
    id = Column(Integer, primary_key=True, index=True)
    result_id = Column(Integer, ForeignKey("inspection_results.id"))
    ip_address = Column(String(50), nullable=False)
    device_id = Column(Integer, ForeignKey("devices.id"))
    is_online = Column(Boolean)
    detection_method = Column(String(20))  # icmp / tcp / none
    open_ports = Column(JSON)
    
    # SNMP采集结果（全量扫描）
    sys_descr = Column(String(500))
    sys_name = Column(String(100))
    sys_object_id = Column(String(100))
    sys_up_time = Column(Integer)
    sys_location = Column(String(200))
    vendor = Column(String(50))
    cpu_usage = Column(Float)
    memory_usage = Column(Float)
    
    # 变更检测
    is_new_device = Column(Boolean, default=False)
    has_fingerprint_change = Column(Boolean, default=False)
    change_detail = Column(JSON)
    
    # 执行信息
    scan_duration_ms = Column(Integer)
    error_message = Column(String(500))
    scanned_at = Column(DateTime(timezone=True))


class DeviceFingerprint(Base):
    """设备指纹快照（每次全量扫描后更新）"""
    __tablename__ = "device_fingerprints"
    
    id = Column(Integer, primary_key=True, index=True)
    ip_address = Column(String(50), unique=True, nullable=False)
    device_id = Column(Integer, ForeignKey("devices.id"))
    sys_descr = Column(String(500))
    sys_name = Column(String(100))
    sys_object_id = Column(String(100))
    sys_location = Column(String(200))
    vendor = Column(String(50))
    last_seen_online = Column(DateTime(timezone=True))
    last_full_scan_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
