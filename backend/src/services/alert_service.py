"""告警服务"""
import asyncio
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, delete
from datetime import datetime, timedelta
import statistics
import time
import httpx
from email.mime.text import MIMEText
from email.utils import formataddr
import smtplib
import json
import logging

from src.models.alert import AlertRule, AlertRecord, AlertNotification
from src.models.device import Device
from src.models.link_monitor import LinkMonitor
from src.models.setting import Setting
from src.config import settings
from src.services.alert_ws import broadcast_new_alert
from src.utils.logger import get_logger

logger = get_logger()

NOTIFICATION_SETTINGS_KEY = "notification_settings"

# ---------------- 自适应告警（突变检测）相关常量与缓存 ----------------
# 默认 detection_mode='static'，因此升级后默认不写入任何样本、不产生任何行为变化
ANOMALY_RULE_CHECK_TTL = 60.0          # 是否存在 anomaly 规则的缓存时间（秒）
METRIC_RETENTION_DAYS = 7              # 历史样本保留天数（防止表无限增长）
METRIC_PRUNE_INTERVAL = 3600.0         # 清理执行的最小间隔（秒）
MIN_BASELINE_SAMPLES = 10              # 冷启动保护：样本不足时不告警

_ANOMALY_RULE_CACHE = {"checked_at": 0.0, "exists": False}
_LAST_PRUNE_AT = 0.0


class AlertService:
    """告警服务"""
    
    @staticmethod
    async def evaluate_rules(db: AsyncSession, device_id: int, target_ip: str, 
                            latency: float, packet_loss: float, status: str) -> List[dict]:
        """
        评估告警规则，生成告警记录
        
        返回：触发的告警列表
        """
        alerts = []
        
        # 获取适用的告警规则
        query = select(AlertRule).where(
            AlertRule.enabled == True,
            (AlertRule.device_id == device_id) | (AlertRule.device_id == None)
        )
        result = await db.execute(query)
        rules = result.scalars().all()
        logger.info(f"[evaluate_rules] device_id={device_id} target_ip={target_ip} "
                    f"latency={latency} packet_loss={packet_loss} status={status} "
                    f"found {len(rules)} enabled rules")
        
        for rule in rules:
            # 静默中的规则不产生新告警（到期后自动恢复）
            if rule.muted_until is not None and rule.muted_until > datetime.now():
                logger.info(f"[evaluate_rules] device_id={device_id} rule={rule.id} muted until {rule.muted_until}, skip")
                continue
            mode = (getattr(rule, "detection_mode", None) or "static")
            baseline_info = None

            if mode == "anomaly" and rule.condition_type in ("latency", "packet_loss"):
                # 自适应突变检测（新增能力，仅 detection_mode='anomaly' 的规则会走到）
                matched, baseline_info = await AlertService._check_anomaly_condition(
                    db, rule, device_id, latency, packet_loss
                )
            else:
                # 原有静态阈值判定：完全沿用历史逻辑，行为保持不变
                matched = await AlertService._check_condition(rule, latency, packet_loss, status)

            if matched:
                logger.info(f"[evaluate_rules] device_id={device_id} rule={rule.id} name={rule.name} "
                            f"condition_type={rule.condition_type} severity={rule.severity} condition matched")
                # 检查是否已有相同类型的未处理告警（active/acknowledged 均视为未处理）
                existing_query = select(AlertRecord).where(
                    AlertRecord.device_id == device_id,
                    AlertRecord.rule_id == rule.id,
                    AlertRecord.status.in_(("active", "acknowledged"))
                ).order_by(AlertRecord.created_at.desc()).limit(1)
                existing_result = await db.execute(existing_query)
                existing_alert = existing_result.scalar_one_or_none()
                
                if not existing_alert:
                    # 处理有效语义：已处理（resolved）的同对象+同规则告警，
                    # 仅当阈值再次恶化（对 gt 操作符当前值更高 / lt 更低）才重建，避免反复复发
                    previous_query = select(AlertRecord).where(
                        AlertRecord.device_id == device_id,
                        AlertRecord.rule_id == rule.id,
                        AlertRecord.status == "resolved"
                    ).order_by(AlertRecord.resolved_at.desc()).limit(1)
                    previous_result = await db.execute(previous_query)
                    previous_alert = previous_result.scalar_one_or_none()

                    current_value = AlertService._get_current_value(rule, latency, packet_loss, status)
                    if previous_alert and previous_alert.current_value is not None and current_value is not None:
                        # 与上次触发时对比：恶化判定随操作符方向（gt 越大越坏 / lt 越小越坏）；
                        # status 类规则无连续数值（current_value 为 None），视为恶化需重建
                        worsened = (
                            current_value > previous_alert.current_value
                            if rule.operator in ("gt", "eq")
                            else current_value < previous_alert.current_value
                        )
                        if not worsened:
                            logger.info(f"[evaluate_rules] device_id={device_id} rule={rule.id} "
                                        f"已处理告警阈值未恶化（上次 {previous_alert.current_value}，"
                                        f"当前 {current_value}），不重建")
                            continue

                    logger.info(f"[evaluate_rules] device_id={device_id} rule={rule.id} no existing active alert, creating new")
                    # 创建新告警
                    alert_record = AlertRecord(
                        rule_id=rule.id,
                        device_id=device_id,
                        target_ip=target_ip,
                        alert_type=rule.condition_type,
                        severity=rule.severity,
                        message=AlertService._generate_message(rule, latency, packet_loss, status, baseline_info),
                        current_value=current_value,
                        threshold=rule.threshold,
                        object_type="device"
                    )
                    db.add(alert_record)
                    await db.flush()
                    
                    # 发送通知
                    await AlertService._send_notifications(db, alert_record)

                    # 实时推送给在线前端（失败不影响告警落库）
                    await broadcast_new_alert(alert_record)

                    # critical 告警触发 AI 根因分析
                    if rule.severity == "critical":
                        logger.info(f"[evaluate_rules] device_id={device_id} rule={rule.id} new critical alert, triggering AI analysis")
                        await AlertService._perform_ai_analysis(db, alert_record)

                    logger.info(f"[evaluate_rules] device_id={device_id} rule={rule.id} new alert created, id={alert_record.id}")
                    alerts.append({
                        "id": alert_record.id,
                        "rule_id": rule.id,
                        "device_id": device_id,
                        "severity": rule.severity,
                        "message": alert_record.message
                    })
                else:
                    # 更新现有告警信息
                    logger.info(f"[evaluate_rules] device_id={device_id} rule={rule.id} existing active alert exists, updating")
                    old_severity = existing_alert.severity
                    existing_alert.message = AlertService._generate_message(rule, latency, packet_loss, status, baseline_info)
                    existing_alert.current_value = AlertService._get_current_value(rule, latency, packet_loss, status)
                    await db.flush()
                    
                    # 检查是否需要重新发送通知
                    severity_order = {"info": 0, "warning": 1, "critical": 2}
                    old_level = severity_order.get(old_severity, 0)
                    new_level = severity_order.get(rule.severity, 0)
                    
                    should_send = False
                    reason = ""
                    
                    if new_level > old_level:
                        # 严重度升级，需要重新发送通知
                        should_send = True
                        reason = f"告警严重度升级: {old_severity} -> {rule.severity}"
                        logger.info(f"[evaluate_rules] device_id={device_id} rule={rule.id} {reason}, will resend notification")
                    else:
                        # 检查上次通知时间
                        last_notification_query = select(AlertNotification).where(
                            AlertNotification.record_id == existing_alert.id,
                            AlertNotification.status == "sent"
                        ).order_by(AlertNotification.sent_at.desc()).limit(1)
                        last_notification_result = await db.execute(last_notification_query)
                        last_notification = last_notification_result.scalar_one_or_none()
                        
                        if not last_notification:
                            # 从未发送过通知
                            should_send = True
                            reason = "告警从未发送过通知"
                        elif last_notification.sent_at:
                            hours_since_last = (datetime.now() - last_notification.sent_at).total_seconds() / 3600
                            if hours_since_last >= 24:
                                # 超过24小时，重新发送
                                should_send = True
                                reason = f"告警已超过24小时（{hours_since_last:.1f}h），重新发送"
                    
                    if should_send:
                        logger.info(f"设备 [{device_id}] 告警重新发送通知: {reason}")
                        await AlertService._send_notifications(db, existing_alert)

                        # 升级到 critical 时触发 AI 根因分析
                        if new_level > old_level and rule.severity == "critical":
                            await AlertService._perform_ai_analysis(db, existing_alert)
                    
                    alerts.append({
                        "id": existing_alert.id,
                        "rule_id": rule.id,
                        "device_id": device_id,
                        "severity": rule.severity,
                        "message": existing_alert.message
                    })
        
        return alerts
    
    @staticmethod
    async def _check_condition(rule: AlertRule, latency: float, packet_loss: float, status: str) -> bool:
        """检查告警条件是否满足"""
        value = None
        
        if rule.condition_type == "latency" and latency is not None:
            value = latency
        elif rule.condition_type == "packet_loss" and packet_loss is not None:
            value = packet_loss
        elif rule.condition_type == "status":
            return status != "normal"
        
        if value is None:
            return False
        
        # 比较操作
        if rule.operator == "gt":
            return value > rule.threshold
        elif rule.operator == "lt":
            return value < rule.threshold
        elif rule.operator == "eq":
            return value == rule.threshold
        elif rule.operator == "ne":
            return value != rule.threshold
        
        return False
    
    # ---------------- 自适应告警（突变检测）----------------

    @staticmethod
    async def _has_anomaly_rules(db: AsyncSession) -> bool:
        """是否存在启用的 anomaly 模式规则（带短缓存，避免每轮每设备重复查库）"""
        now = time.time()
        if now - _ANOMALY_RULE_CACHE["checked_at"] < ANOMALY_RULE_CHECK_TTL:
            return _ANOMALY_RULE_CACHE["exists"]
        try:
            result = await db.execute(
                select(AlertRule.id)
                .where(AlertRule.enabled == True, AlertRule.detection_mode == "anomaly")
                .limit(1)
            )
            exists = result.scalar_one_or_none() is not None
        except Exception as e:
            # 列尚未就绪等异常：一律按「无规则」处理，保证默认零写入、零影响
            logger.warning(f"[自适应告警] 检测 anomaly 规则失败，按无规则处理（不影响告警流程）: {e}")
            exists = False
        _ANOMALY_RULE_CACHE["checked_at"] = now
        _ANOMALY_RULE_CACHE["exists"] = exists
        return exists

    @staticmethod
    async def collect_metric_samples(db: AsyncSession, device_id: int,
                                     latency: Optional[float],
                                     packet_loss: Optional[float]) -> None:
        """采集指标样本（滚动基线用）。

        升级安全要点：仅当存在启用的 anomaly 规则时才入库；
        默认 detection_mode='static' → 不产生任何额外写入。
        """
        try:
            if not await AlertService._has_anomaly_rules(db):
                return
            from src.models import MetricSample

            now = datetime.now()
            for metric, value in (("latency", latency), ("packet_loss", packet_loss)):
                if value is None:
                    continue
                db.add(MetricSample(
                    device_id=device_id,
                    metric=metric,
                    value=float(value),
                    sampled_at=now,
                ))

            await AlertService._prune_metric_samples(db)
        except Exception as e:
            logger.warning(f"[自适应告警] 指标采样失败（不影响监控与告警主流程）: {e}")

    @staticmethod
    async def _prune_metric_samples(db: AsyncSession) -> None:
        """按保留天数清理过期样本（限频执行，避免高频 DELETE 冲击生产库）"""
        global _LAST_PRUNE_AT
        now = time.time()
        if now - _LAST_PRUNE_AT < METRIC_PRUNE_INTERVAL:
            return
        try:
            from src.models import MetricSample

            cutoff = datetime.now() - timedelta(days=METRIC_RETENTION_DAYS)
            await db.execute(delete(MetricSample).where(MetricSample.sampled_at < cutoff))
            _LAST_PRUNE_AT = now
        except Exception as e:
            logger.warning(f"[自适应告警] 历史样本清理失败（不影响主流程）: {e}")

    @staticmethod
    async def _check_anomaly_condition(db: AsyncSession, rule: AlertRule, device_id: int,
                                       latency: Optional[float],
                                       packet_loss: Optional[float]) -> tuple:
        """自适应突变检测：返回 (是否异常, 基线信息)

        判定口径（任一命中即判定异常）：
        1) z-score：|当前值 - 均值| / 标准差 > baseline_sensitivity（默认 3.0）
        2) 变化率：|当前值 - 均值| / |均值| > mutation_threshold（默认 0.5，即 50%）

        冷启动保护：样本数 < MIN_BASELINE_SAMPLES 时一律不告警，避免上线即误报风暴。
        """
        value = latency if rule.condition_type == "latency" else packet_loss
        if value is None:
            return False, None

        window = int(getattr(rule, "baseline_window", None) or 50)
        window = max(10, min(window, 500))
        sensitivity = float(getattr(rule, "baseline_sensitivity", None) or 3.0)
        mutation_threshold = float(getattr(rule, "mutation_threshold", None) or 0.5)

        try:
            from src.models import MetricSample

            rows = await db.execute(
                select(MetricSample.value)
                .where(MetricSample.device_id == device_id,
                       MetricSample.metric == rule.condition_type)
                .order_by(MetricSample.sampled_at.desc())
                .limit(window)
            )
            values = [float(v) for (v,) in rows.all() if v is not None]
        except Exception as e:
            logger.warning(
                f"[自适应告警] rule={rule.id} 读取历史样本失败，本次不告警（不影响主流程）: {e}"
            )
            return False, None

        if len(values) < MIN_BASELINE_SAMPLES:
            return False, {
                "status": "insufficient",
                "samples": len(values),
                "required": MIN_BASELINE_SAMPLES,
            }

        mean = statistics.mean(values)
        stdev = statistics.pstdev(values)

        # 阻尼：方差趋零时 z-score 会过度敏感（极稳定链路的微小抖动被放大成「突变」），
        # 故给标准差设一个相对下限（均值的 2%）。
        stdev_eff = max(stdev, abs(mean) * 0.02)
        z_score = ((value - mean) / stdev_eff) if stdev_eff > 0 else 0.0

        # 零基线兜底：历史恒为 0（如丢包率长期 0%）时，用绝对下限做分母，
        # 避免 0% → 5% 这类真实突变被 0 分母吞掉而漏报。
        denom = max(abs(mean), 1.0)
        change_rate = abs(value - mean) / denom

        # 基线完全无波动时 z-score 无统计意义，交由变化率判定，避免 0→0.1 这类
        # 微小抖动被放大成突变（此时 stdev_eff 为 0，本分支自动失效）
        by_zscore = stdev_eff > 0 and abs(z_score) > sensitivity
        by_rate = mutation_threshold > 0 and change_rate > mutation_threshold

        return (by_zscore or by_rate), {
            "status": "ready",
            "samples": len(values),
            "mean": mean,
            "stdev": stdev,
            "z_score": z_score,
            "change_rate": change_rate,
            "sensitivity": sensitivity,
            "mutation_threshold": mutation_threshold,
        }

    @staticmethod
    async def get_metric_history(db: AsyncSession, device_id: int, metric: str,
                                 limit: int = 200) -> dict:
        """事件回看：返回指定设备/指标的近期采样序列与基线统计"""
        from src.models import MetricSample

        rows = await db.execute(
            select(MetricSample.value, MetricSample.sampled_at)
            .where(MetricSample.device_id == device_id, MetricSample.metric == metric)
            .order_by(MetricSample.sampled_at.desc())
            .limit(limit)
        )
        row_list = rows.all()
        values = [float(v) for v, _ in row_list if v is not None]

        samples = [
            {"value": float(v), "sampled_at": (t.isoformat() if t is not None else None)}
            for v, t in reversed(row_list)
        ]

        if len(values) >= 2:
            baseline = {
                "status": "ready",
                "samples": len(values),
                "mean": statistics.mean(values),
                "stdev": statistics.pstdev(values),
            }
        else:
            baseline = {"status": "insufficient", "samples": len(values)}

        return {
            "device_id": device_id,
            "metric": metric,
            "samples": samples,
            "baseline": baseline,
        }

    @staticmethod
    def _generate_message(rule: AlertRule, latency: float, packet_loss: float, status: str,
                          baseline_info: Optional[dict] = None) -> str:
        """生成告警消息"""
        status_text: dict[str, str] = {
            "critical": "严重",
            "warning": "警告",
            "info": "提示",
            "normal": "正常",
        }
        status_cn = status_text.get(status, status)

        # 自适应突变检测命中：给出「偏离基线」描述（新增分支，不影响静态阈值文案）
        if baseline_info and baseline_info.get("status") == "ready" \
                and rule.condition_type in ("latency", "packet_loss"):
            is_latency = rule.condition_type == "latency"
            metric_cn = "延迟" if is_latency else "丢包率"
            unit = "ms" if is_latency else "%"
            current = latency if is_latency else packet_loss
            mean = baseline_info.get("mean") or 0
            return (
                f"设备{metric_cn}显著偏离历史基线: 当前 {current}{unit}, "
                f"基线均值 {mean:.2f}{unit}, "
                f"偏离 {(baseline_info.get('z_score') or 0):.2f} 个标准差"
                f"（变化率 {((baseline_info.get('change_rate') or 0) * 100):.1f}%, "
                f"样本数 {baseline_info.get('samples')}）"
            )

        if rule.condition_type == "latency":
            return f"设备延迟过高: 当前 {latency}ms, 阈值 {rule.threshold}ms"
        elif rule.condition_type == "packet_loss":
            return f"设备丢包率过高: 当前 {packet_loss}%, 阈值 {rule.threshold}%"
        elif rule.condition_type == "status":
            return f"设备状态异常: {status_cn}"
        return f"告警触发: {rule.name}"
    
    @staticmethod
    def _get_current_value(rule: AlertRule, latency: float, packet_loss: float, status: str) -> Optional[float]:
        """获取当前值"""
        if rule.condition_type == "latency":
            return latency
        elif rule.condition_type == "packet_loss":
            return packet_loss
        return None
    
    @staticmethod
    async def _perform_ai_analysis(db: AsyncSession, alert_record: AlertRecord):
        """对 critical 告警执行 AI 根因分析，结果存入 ai_analysis 字段"""
        try:
            from src.services.ai_client import get_ai_config, call_ai
            from src.services.ai_outbound_guard import is_external_blocked, mask_outbound_text

            # 禁止外发开关开启时跳过（告警消息不外发）
            if await is_external_blocked(db):
                logger.debug("[AI根因分析] 禁止外发开关已开启，跳过根因分析")
                return

            ai_config = await get_ai_config(db)
            if not ai_config:
                logger.debug("[AI根因分析] 无AI配置，跳过根因分析")
                return

            # 获取设备信息
            device = await db.get(Device, alert_record.device_id)
            device_name = device.name if device else "未知设备"
            device_type = device.type if device else "未知"
            device_brand = getattr(device, "brand", "") or ""
            device_model = getattr(device, "model", "") or ""

            logger.info(f"[AI根因分析] alert_id={alert_record.id} device={device_name} "
                        f"provider={ai_config.provider} model={ai_config.model} 开始调用AI")

            prompt = (
                f"请对以下 IT 基础设施告警进行根因分析，给出可能的故障原因和处理建议。\n\n"
                f"告警信息：\n"
                f"- 设备名称：{device_name}\n"
                f"- 设备类型：{device_type}\n"
                f"- 品牌/型号：{device_brand} {device_model}\n"
                f"- 目标IP：{alert_record.target_ip or 'N/A'}\n"
                f"- 告警类型：{alert_record.alert_type}\n"
                f"- 严重级别：{alert_record.severity}\n"
                f"- 告警消息：{mask_outbound_text(alert_record.message or '')}\n"
                f"- 当前值：{alert_record.current_value}\n"
                f"- 阈值：{alert_record.threshold}\n\n"
                f"请按以下格式输出：\n"
                f"1. 可能根因（列出 2-3 个最可能的原因，按可能性排序）\n"
                f"2. 排查步骤（每个根因对应的排查方法）\n"
                f"3. 处理建议（优先级排序的修复方案）"
            )

            system = (
                "你是一位资深的 IT 基础设施运维专家，擅长网络设备、服务器、存储等基础设施的故障诊断。"
                "请基于告警信息进行专业、准确的根因分析，输出简洁实用的分析报告。"
            )

            result = await call_ai(prompt, system, ai_config, max_tokens=1500, timeout=20)
            result_len = len(result) if result else 0
            alert_record.ai_analysis = result
            await db.flush()
            logger.info(f"[AI根因分析] alert_id={alert_record.id} device={device_name} "
                        f"分析完成，结果长度={result_len} 已存入告警记录")

        except Exception as e:
            import traceback
            logger.warning(f"[AI根因分析] alert_id={alert_record.id} 失败（不影响告警流程）: {e}\n{traceback.format_exc()}")

    @staticmethod
    async def _send_notifications(db: AsyncSession, alert_record: AlertRecord):
        """发送告警通知"""
        # 获取规则配置的通知渠道
        query = select(AlertRule).where(AlertRule.id == alert_record.rule_id)
        result = await db.execute(query)
        rule = result.scalar_one_or_none()
        
        if not rule:
            logger.warning(f"[_send_notifications] alert_id={alert_record.id} rule not found (rule_id={alert_record.rule_id}), skipping")
            return
        
        channels = rule.notification_channels or []
        logger.info(f"[_send_notifications] alert_id={alert_record.id} rule={rule.id} sending to channels={channels}")

        # 渠道启用开关过滤（notification_settings.channel_enabled，未配置默认启用）
        from src.utils.notification_store import get_notification_config, is_channel_enabled
        notify_cfg = await get_notification_config(db)
        channels = [c for c in channels if is_channel_enabled(notify_cfg, c)]
        
        for channel in channels:
            notification = AlertNotification(
                record_id=alert_record.id,
                channel=channel,
                target="",
                status="pending"
            )
            db.add(notification)
            logger.info(f"[_send_notifications] alert_id={alert_record.id} channel={channel} starting send")
            
            # 模拟发送通知
            try:
                await AlertService._send_notification(db, channel, alert_record)
                notification.status = "sent"
                notification.sent_at = datetime.now()
                logger.info(f"[_send_notifications] alert_id={alert_record.id} channel={channel} sent successfully")
            except Exception as e:
                notification.status = "failed"
                notification.error_message = str(e)
                logger.error(f"[_send_notifications] alert_id={alert_record.id} channel={channel} send failed: {e}")
    
    @staticmethod
    async def _get_notification_config(db: AsyncSession) -> dict:
        """获取通知配置（统一走 notification_store：解密 + 环境变量回落 + 渠道开关）"""
        from src.utils.notification_store import get_notification_config
        return await get_notification_config(db)
    
    @staticmethod
    async def _send_notification(db: AsyncSession, channel: str, alert_record: AlertRecord):
        """发送单个通知"""
        # 获取设备信息
        query = select(Device.name).where(Device.id == alert_record.device_id)
        result = await db.execute(query)
        device_name = result.scalar_one_or_none() or "未知设备"
        
        message = f"【告警】[{alert_record.severity.upper()}] {device_name}: {alert_record.message}"
        
        # 获取通知配置
        config = await AlertService._get_notification_config(db)
        
        # 根据渠道发送通知
        if channel == "dingtalk":
            await AlertService._send_dingtalk_notification(config["dingtalk_webhook_url"], message)
        elif channel == "wechat":
            await AlertService._send_wechat_notification(config["wechat_webhook_url"], message)
        elif channel == "feishu":
            await AlertService._send_feishu_notification(config["feishu_webhook_url"], message)
        elif channel == "email":
            await AlertService._send_email_notification(config, message)
        elif channel == "webhook":
            await AlertService._send_custom_webhook(message)
    
    @staticmethod
    async def _send_dingtalk_notification(webhook_url: str, message: str):
        """发送钉钉机器人通知"""
        if not webhook_url:
            logger.warning("钉钉Webhook地址未配置")
            return
        
        async with httpx.AsyncClient() as client:
            payload = {
                "msgtype": "text",
                "text": {
                    "content": message
                }
            }
            try:
                response = await client.post(webhook_url, json=payload, timeout=10)
                response.raise_for_status()
                logger.info(f"钉钉通知发送成功: {message}")
            except Exception as e:
                logger.error(f"钉钉通知发送失败: {e}")
                raise
    
    @staticmethod
    async def _send_wechat_notification(webhook_url: str, message: str):
        """发送企业微信机器人通知"""
        if not webhook_url:
            logger.warning("企业微信Webhook地址未配置")
            return

        async with httpx.AsyncClient() as client:
            payload = {
                "msgtype": "text",
                "text": {
                    "content": message
                }
            }
            try:
                response = await client.post(webhook_url, json=payload, timeout=10)
                response.raise_for_status()
                logger.info(f"企业微信通知发送成功: {message}")
            except Exception as e:
                logger.error(f"企业微信通知发送失败: {e}")
                raise
    
    @staticmethod
    async def _send_feishu_notification(webhook_url: str, message: str):
        """发送飞书机器人通知"""
        if not webhook_url:
            logger.warning("飞书Webhook地址未配置")
            return

        async with httpx.AsyncClient() as client:
            payload = {
                "msg_type": "text",
                "content": {
                    "text": message
                }
            }
            try:
                response = await client.post(webhook_url, json=payload, timeout=10)
                response.raise_for_status()
                logger.info(f"飞书通知发送成功: {message}")
            except Exception as e:
                logger.error(f"飞书通知发送失败: {e}")
                raise
    
    @staticmethod
    def _smtp_connect(config: dict):
        """按 smtp_security 建立 SMTP 连接（none/starttls/ssl），三处发送统一走此 helper。"""
        import smtplib
        security = (config.get("smtp_security") or "starttls").lower()
        if security == "ssl":
            server = smtplib.SMTP_SSL(config["smtp_host"], config["smtp_port"], timeout=15)
        else:
            server = smtplib.SMTP(config["smtp_host"], config["smtp_port"], timeout=15)
            if security == "starttls":
                server.starttls()
        return server

    @staticmethod
    async def _send_email_notification(config: dict, message: str):
        """发送邮件通知"""
        import asyncio as _asyncio
        smtp_host = config["smtp_host"]
        smtp_port = config["smtp_port"]
        smtp_username = config["smtp_username"]
        smtp_password = config["smtp_password"]
        smtp_from_email = config["smtp_from_email"]
        
        if not all([smtp_host, smtp_username, smtp_password, smtp_from_email]):
            logger.warning("邮件服务器配置未完整")
            return

        try:
            msg = MIMEText(message, 'plain', 'utf-8')
            msg['From'] = formataddr(('Cornerstone告警系统', smtp_from_email))
            msg['Subject'] = "【告警通知】"

            def _smtp_send():
                with AlertService._smtp_connect(config) as server:
                    server.login(smtp_username, smtp_password)
                    server.sendmail(smtp_from_email, [smtp_from_email], msg.as_string())

            # 同步 smtplib 放线程池，避免阻塞事件循环
            await _asyncio.to_thread(_smtp_send)
            logger.info(f"邮件通知发送成功: {message}")
        except Exception as e:
            logger.error(f"邮件通知发送失败: {e}")
            raise

    @staticmethod
    async def _send_custom_webhook(message: str):
        """发送自定义Webhook通知"""
        logger.info(f"自定义Webhook通知: {message}")
    
    @staticmethod
    async def send_backup_failure_notification(
        db: AsyncSession, task_id: int, task_name: str, summary: str
    ):
        """备份任务失败时推送通知（钉钉/企业微信/飞书/邮件）

        逐渠道隔离异常，单渠道失败不影响其他渠道，且不向调用方抛出异常。
        发送结果落 alert_notifications（record_id=None, channel='backup:<id>'）。
        """
        from src.utils.notification_store import get_notification_config, is_channel_enabled, is_email_ready

        try:
            config = await get_notification_config(db)
            message = f"【备份失败】任务 {task_id}（{task_name}）：{summary}"
            errors = []
            sent = False

            plans = []
            if config["dingtalk_webhook_url"] and is_channel_enabled(config, "dingtalk"):
                plans.append(("dingtalk", AlertService._send_dingtalk_notification(config["dingtalk_webhook_url"], message)))
            if config["wechat_webhook_url"] and is_channel_enabled(config, "wechat"):
                plans.append(("wechat", AlertService._send_wechat_notification(config["wechat_webhook_url"], message)))
            if config["feishu_webhook_url"] and is_channel_enabled(config, "feishu"):
                plans.append(("feishu", AlertService._send_feishu_notification(config["feishu_webhook_url"], message)))
            if is_email_ready(config) and is_channel_enabled(config, "email"):
                plans.append(("email", AlertService._send_email_notification(config, message)))

            for channel, coro in plans:
                notification = AlertNotification(
                    record_id=None,
                    channel=f"backup:{task_id}:{channel}",
                    target="",
                    status="pending",
                )
                db.add(notification)
                try:
                    await coro
                    notification.status = "sent"
                    notification.sent_at = datetime.now()
                    sent = True
                except Exception as e:
                    notification.status = "failed"
                    notification.error_message = str(e)[:500]
                    errors.append(f"{channel}: {e}")
            await db.commit()

            if sent:
                logger.info(f"[备份通知] 任务 {task_id} 失败通知已发送: {summary}")
            elif not errors:
                logger.warning("[备份通知] 未配置任何通知渠道（钉钉/企业微信/飞书/邮件），跳过备份失败通知")
            if errors:
                logger.error(f"[备份通知] 任务 {task_id} 部分渠道发送失败: {'; '.join(errors)}")
        except Exception as e:
            logger.error(f"[备份通知] 任务 {task_id} 失败通知发送异常（不影响备份流程）: {e}")

    @staticmethod
    async def acknowledge_alert(db: AsyncSession, alert_id: int, user_id: int):
        """确认告警"""
        stmt = update(AlertRecord).where(AlertRecord.id == alert_id).values(
            status="acknowledged",
            acknowledged_by=user_id,
            acknowledged_at=datetime.now()
        )
        await db.execute(stmt)
        await db.commit()
    
    @staticmethod
    async def resolve_alerts(db: AsyncSession, device_id: Optional[int] = None):
        """恢复告警（设备恢复正常时）"""
        query = select(AlertRecord).where(AlertRecord.status == "active")
        if device_id:
            query = query.where(AlertRecord.device_id == device_id)
        
        result = await db.execute(query)
        alerts = result.scalars().all()
        
        for alert in alerts:
            alert.status = "resolved"
            alert.resolved_at = datetime.now()
        
        await db.commit()
    
    @staticmethod
    async def get_active_alerts(db: AsyncSession, device_id: Optional[int] = None, 
                               severity: Optional[str] = None) -> List[AlertRecord]:
        """获取活动告警"""
        query = select(AlertRecord).where(AlertRecord.status == "active")
        
        if device_id:
            query = query.where(AlertRecord.device_id == device_id)
        if severity:
            query = query.where(AlertRecord.severity == severity)
        
        query = query.order_by(AlertRecord.created_at.desc())
        
        result = await db.execute(query)
        return result.scalars().all()
    
    @staticmethod
    async def get_alert_summary(db: AsyncSession) -> dict:
        """获取告警统计概览"""
        query = select(
            AlertRecord.severity,
            func.count(AlertRecord.id).label("count")
        ).where(AlertRecord.status == "active").group_by(AlertRecord.severity)

        result = await db.execute(query)
        status_counts = result.all()

        summary = {"info": 0, "warning": 0, "critical": 0}
        for severity, count in status_counts:
            if severity in summary:
                summary[severity] = count

        return summary

    @staticmethod
    async def get_full_summary(db: AsyncSession) -> dict:
        """完整统计口径：状态维度（总数/未认领/已认领/已处理）× 级别维度交叉计数

        前端顶部卡片与列表统一消费此接口，保证口径一致。
        """
        result = await db.execute(
            select(AlertRecord.status, AlertRecord.severity, func.count(AlertRecord.id))
            .group_by(AlertRecord.status, AlertRecord.severity)
        )
        rows = result.all()

        by_status = {"total": 0, "active": 0, "acknowledged": 0, "resolved": 0}
        by_severity = {"info": 0, "warning": 0, "critical": 0}
        # 未处理（active+acknowledged）按级别计数，供「严重/警告」卡片联动筛选
        open_by_severity = {"info": 0, "warning": 0, "critical": 0}

        for status, severity, count in rows:
            by_status["total"] += count
            if status in by_status:
                by_status[status] = count
            if severity in by_severity:
                by_severity[severity] += count
            if status in ("active", "acknowledged") and severity in open_by_severity:
                open_by_severity[severity] += count

        return {
            "by_status": by_status,
            "by_severity": by_severity,
            "open_by_severity": open_by_severity,
        }

    # 严重告警升级提醒：critical 未认领超过该小时数后，检查任务中重复发通知
    CRITICAL_ESCALATION_HOURS = 24

    @staticmethod
    async def escalate_stale_critical_alerts(db: AsyncSession) -> int:
        """严重告警升级：critical 且长时间未认领 → 重复发通知并标记 escalated_at

        幂等：每条告警两次提醒间隔不小于 CRITICAL_ESCALATION_HOURS。
        返回本次触发升级提醒的告警数。
        """
        threshold = datetime.now() - timedelta(hours=AlertService.CRITICAL_ESCALATION_HOURS)
        result = await db.execute(
            select(AlertRecord).where(
                AlertRecord.severity == "critical",
                AlertRecord.status == "active",
                AlertRecord.created_at < threshold,
            )
        )
        stale_alerts = result.scalars().all()

        escalated = 0
        for alert in stale_alerts:
            # 已提醒过且距上次提醒不足间隔 → 跳过（幂等）
            if alert.escalated_at and (datetime.now() - alert.escalated_at).total_seconds() / 3600 \
                    < AlertService.CRITICAL_ESCALATION_HOURS:
                continue
            logger.warning(f"[告警升级] critical 告警 id={alert.id} 已超过 "
                           f"{AlertService.CRITICAL_ESCALATION_HOURS}h 未认领，重复发送提醒")
            try:
                await AlertService._send_notifications(db, alert)
            except Exception as e:
                logger.warning(f"[告警升级] id={alert.id} 提醒发送失败（不影响主流程）: {e}")
            alert.escalated_at = datetime.now()
            escalated += 1

        if escalated:
            await db.commit()
        return escalated


alert_service = AlertService()
