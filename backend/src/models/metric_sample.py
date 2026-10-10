"""指标采样模型

为「自适应告警 / 突变检测」提供滚动基线数据。

设计要点（升级安全）：
- 仅在存在 detection_mode='anomaly' 的启用规则时才写入样本；
  默认 detection_mode='static'，因此升级后默认**不产生任何额外写入**。
- sampled_at 统一使用不带时区的 DateTime（与 AlertRecord/AlertRule 一致），
  并通过显式赋值写入，便于与 datetime.now() 做比较。
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Index
from sqlalchemy.sql import func

from src.database import Base


class MetricSample(Base):
    """设备指标采样点（滚动基线用）"""
    __tablename__ = "metric_samples"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=True, comment="设备ID")
    metric = Column(String(30), nullable=False, comment="指标名：latency / packet_loss")
    value = Column(Float, nullable=False, comment="采样值")
    sampled_at = Column(DateTime, server_default=func.now(), nullable=False, comment="采样时间")

    __table_args__ = (
        Index("ix_metric_samples_device_metric_time", "device_id", "metric", "sampled_at"),
    )
