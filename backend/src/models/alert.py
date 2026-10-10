"""告警相关模型"""
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean, JSON, Text, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from src.database import Base


class AlertRule(Base):
    """告警规则"""
    __tablename__ = "alert_rules"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, comment="规则名称")
    description = Column(String(500), comment="规则描述")
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=True, comment="设备ID（为空则应用于所有设备）")
    condition_type = Column(String(50), nullable=False, comment="条件类型：latency/packet_loss/status")
    operator = Column(String(10), nullable=False, comment="比较操作符：gt/lt/eq/ne")
    threshold = Column(Float, nullable=False, comment="阈值")
    severity = Column(String(20), nullable=False, default="warning", comment="告警级别：info/warning/critical")
    enabled = Column(Boolean, default=True, comment="是否启用")
    notification_channels = Column(JSON, default=list, comment="通知渠道：email/dingtalk/wechat/webhook")
    muted_until = Column(DateTime, nullable=True, comment="静默截止时间：到期前该规则不产生新告警")

    # 自适应告警（突变检测）——默认 static，与历史行为完全一致
    detection_mode = Column(String(20), nullable=True, comment="检测模式：static（静态阈值）/anomaly（自适应突变检测）")
    baseline_window = Column(Integer, nullable=True, comment="基线窗口：参与统计的样本数（默认 50）")
    baseline_sensitivity = Column(Float, nullable=True, comment="基线敏感度：z-score 阈值（默认 3.0）")
    mutation_threshold = Column(Float, nullable=True, comment="环比突变阈值：相对变化率（默认 0.5，即 50%）")

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    
    device = relationship("Device", back_populates="alert_rules")


class AlertRecord(Base):
    """告警记录"""
    __tablename__ = "alert_records"
    __table_args__ = (
        Index('ix_alert_records_status_created_at', 'status', 'created_at'),
    )
    
    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, ForeignKey("alert_rules.id"), nullable=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=True, comment="关联设备ID；巡检发现的未登记设备可能尚无 device 记录，故允许为空")
    target_ip = Column(String(50), comment="目标IP")
    alert_type = Column(String(50), nullable=False, comment="告警类型")
    severity = Column(String(20), nullable=False, comment="告警级别")
    message = Column(String(1000), nullable=False, comment="告警消息")
    current_value = Column(Float, comment="当前值")
    threshold = Column(Float, comment="阈值")
    status = Column(String(20), nullable=False, default="active", comment="状态：active/acknowledged/resolved")
    acknowledged_by = Column(Integer, ForeignKey("users.id"), nullable=True, comment="确认人")
    acknowledged_at = Column(DateTime, comment="确认时间")
    resolved_at = Column(DateTime, comment="恢复时间")
    ai_analysis = Column(Text, nullable=True, comment="AI根因分析结果")
    created_at = Column(DateTime, server_default=func.now())
    
    rule = relationship("AlertRule")
    device = relationship("Device", back_populates="alert_records")
    acknowledged_user = relationship("User")


class AlertNotification(Base):
    """告警通知记录"""
    __tablename__ = "alert_notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    record_id = Column(Integer, ForeignKey("alert_records.id"))
    channel = Column(String(50), nullable=False, comment="通知渠道")
    target = Column(String(200), comment="通知目标")
    status = Column(String(20), default="pending", comment="状态：pending/sent/failed")
    error_message = Column(String(500), comment="错误信息")
    sent_at = Column(DateTime, comment="发送时间")
    created_at = Column(DateTime, server_default=func.now())
    
    record = relationship("AlertRecord")
