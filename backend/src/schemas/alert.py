from typing import Optional, List
from pydantic import BaseModel

class AlertRuleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    device_id: Optional[int] = None
    condition_type: str
    operator: str
    threshold: float
    severity: str = "warning"
    enabled: bool = True
    notification_channels: Optional[List[str]] = None
    # 自适应告警（可选）：不传则按 static 静态阈值处理，与历史行为一致
    detection_mode: Optional[str] = None
    baseline_window: Optional[int] = None
    baseline_sensitivity: Optional[float] = None
    mutation_threshold: Optional[float] = None

class AlertRuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    device_id: Optional[int] = None
    condition_type: Optional[str] = None
    operator: Optional[str] = None
    threshold: Optional[float] = None
    severity: Optional[str] = None
    enabled: Optional[bool] = None
    notification_channels: Optional[List[str]] = None
    # 自适应告警（可选）
    detection_mode: Optional[str] = None
    baseline_window: Optional[int] = None
    baseline_sensitivity: Optional[float] = None
    mutation_threshold: Optional[float] = None
