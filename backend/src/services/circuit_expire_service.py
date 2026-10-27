import logging
"""专线到期检查服务"""
import asyncio
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from src.models.circuit import Circuit
from src.models.alert import AlertRecord, AlertNotification
from src.models.setting import Setting
from src.config import settings
from src.services.alert_ws import broadcast_new_alert
import json

NOTIFICATION_SETTINGS_KEY = "notification_settings"

logger = logging.getLogger(__name__)


class CircuitExpireService:
    """专线到期检查服务"""
    
    @staticmethod
    async def check_expiring_circuits(db: AsyncSession, days_before: int = 30):
        """
        检查即将到期的专线
        
        :param db: 数据库会话
        :param days_before: 提前多少天检查到期（默认30天）
        """
        now = datetime.now()
        expire_threshold = now + timedelta(days=days_before)
        
        query = select(Circuit).where(
            Circuit.contract_end.isnot(None),
            Circuit.contract_end <= expire_threshold,
            Circuit.status != "已终止"
        )
        
        result = await db.execute(query)
        expiring_circuits = result.scalars().all()
        
        for circuit in expiring_circuits:
            days_remaining = (circuit.contract_end - now).days
            
            if days_remaining < 0:
                severity = "critical"
                message = f"专线 [{circuit.name}] 已过期 {abs(days_remaining)} 天！合同到期日: {circuit.contract_end.strftime('%Y-%m-%d')}"
            elif days_remaining == 0:
                severity = "critical"
                message = f"专线 [{circuit.name}] 今日到期！合同到期日: {circuit.contract_end.strftime('%Y-%m-%d')}"
            elif days_remaining <= 7:
                severity = "critical"
                message = f"专线 [{circuit.name}] 将在 {days_remaining} 天后到期！合同到期日: {circuit.contract_end.strftime('%Y-%m-%d')}"
            elif days_remaining <= 14:
                severity = "warning"
                message = f"专线 [{circuit.name}] 将在 {days_remaining} 天后到期！合同到期日: {circuit.contract_end.strftime('%Y-%m-%d')}"
            else:
                severity = "info"
                message = f"专线 [{circuit.name}] 将在 {days_remaining} 天后到期！合同到期日: {circuit.contract_end.strftime('%Y-%m-%d')}"
            
            await CircuitExpireService._create_expire_alert(db, circuit, severity, message)
    
    @staticmethod
    async def _create_expire_alert(db: AsyncSession, circuit: Circuit, severity: str, message: str):
        """创建专线到期告警记录

        去重策略（按 对象+规则 即 circuit_expire + circuit.id）：
        - 已有未处理（active/acknowledged）告警 → 原地更新内容，不新增；
          created_at 保留首次触发时间，last_checked_at 记录最新检测时间。
        - 已处理（resolved）→ 默认不再重建（处理有效语义）；仅当阈值恶化
          （剩余天数比上次处理时更小，如 19 天 → 10 天）才视为新问题重建。
        """
        now = datetime.now()
        days_remaining = (circuit.contract_end - now).days

        existing_query = select(AlertRecord).where(
            AlertRecord.alert_type == "circuit_expire",
            AlertRecord.device_id == circuit.id,
            AlertRecord.status.in_(("active", "acknowledged"))
        ).order_by(AlertRecord.created_at.desc()).limit(1)
        existing_result = await db.execute(existing_query)
        existing_alert = existing_result.scalar_one_or_none()

        if existing_alert:
            # 检查是否需要重新发送通知
            old_severity = existing_alert.severity
            existing_alert.message = message
            existing_alert.severity = severity
            existing_alert.current_value = days_remaining
            await db.flush()

            # 如果严重度升级，需要重新发送通知
            severity_order = {"info": 0, "warning": 1, "critical": 2}
            old_level = severity_order.get(old_severity, 0)
            new_level = severity_order.get(severity, 0)

            if new_level > old_level:
                logger.info(f"专线 [{circuit.name}] 告警严重度升级: {old_severity} -> {severity}, 重新发送通知")
                await CircuitExpireService._send_expire_notifications(db, existing_alert)
            else:
                # 检查上次通知时间，如果超过24小时则重新发送
                last_notification_query = select(AlertNotification).where(
                    AlertNotification.record_id == existing_alert.id,
                    AlertNotification.status == "sent"
                ).order_by(AlertNotification.sent_at.desc()).limit(1)
                last_notification_result = await db.execute(last_notification_query)
                last_notification = last_notification_result.scalar_one_or_none()

                if last_notification and last_notification.sent_at:
                    hours_since_last_notification = (now - last_notification.sent_at).total_seconds() / 3600
                    if hours_since_last_notification >= 24:
                        logger.info(f"专线 [{circuit.name}] 告警已超过24小时，重新发送通知")
                        await CircuitExpireService._send_expire_notifications(db, existing_alert)
                elif not last_notification:
                    # 从未发送过通知，立即发送
                    logger.info(f"专线 [{circuit.name}] 告警从未发送过通知，立即发送")
                    await CircuitExpireService._send_expire_notifications(db, existing_alert)
            return

        # 无未处理告警：检查是否处理过同类告警（resolved）
        # 处理有效语义：处理后不再因同一问题反复重建；仅阈值恶化才重建
        resolved_query = select(AlertRecord).where(
            AlertRecord.alert_type == "circuit_expire",
            AlertRecord.device_id == circuit.id,
            AlertRecord.status == "resolved"
        ).order_by(AlertRecord.resolved_at.desc()).limit(1)
        resolved_result = await db.execute(resolved_query)
        resolved_alert = resolved_result.scalar_one_or_none()

        if resolved_alert and resolved_alert.current_value is not None \
                and days_remaining >= resolved_alert.current_value:
            # 剩余天数未比上次处理时更小（问题未恶化），不重建
            logger.info(f"专线 [{circuit.name}] 到期告警已于 {resolved_alert.resolved_at} 处理（当时剩余 {resolved_alert.current_value:.0f} 天，现 {days_remaining} 天，未恶化），不重建")
            return

        # 全新告警（或处理后又恶化）：新建记录，object_type 标记真实对象类型
        alert_record = AlertRecord(
            rule_id=None,
            device_id=circuit.id,
            target_ip=circuit.public_ip or "",
            alert_type="circuit_expire",
            severity=severity,
            message=message,
            current_value=days_remaining,
            threshold=0,
            object_type="circuit"
        )
        db.add(alert_record)
        await db.flush()

        await CircuitExpireService._send_expire_notifications(db, alert_record)

        # 实时推送给在线前端（失败不影响告警落库）
        await broadcast_new_alert(alert_record)

    @staticmethod
    async def _send_expire_notifications(db: AsyncSession, alert_record: AlertRecord):
        """发送专线到期通知（渠道启用开关过滤）"""
        from src.utils.notification_store import get_notification_config, is_channel_enabled, is_email_ready
        config = await get_notification_config(db)
        
        enabled_channels = []
        if config.get("dingtalk_webhook_url") and is_channel_enabled(config, "dingtalk"):
            enabled_channels.append("dingtalk")
        if config.get("wechat_webhook_url") and is_channel_enabled(config, "wechat"):
            enabled_channels.append("wechat")
        if config.get("feishu_webhook_url") and is_channel_enabled(config, "feishu"):
            enabled_channels.append("feishu")
        if is_email_ready(config) and is_channel_enabled(config, "email"):
            enabled_channels.append("email")
        
        for channel in enabled_channels:
            notification = AlertNotification(
                record_id=alert_record.id,
                channel=channel,
                target="",
                status="pending"
            )
            db.add(notification)
            
            try:
                await CircuitExpireService._send_notification(db, channel, alert_record, config)
                notification.status = "sent"
                notification.sent_at = datetime.now()
            except Exception as e:
                notification.status = "failed"
                notification.error_message = str(e)[:500]
                await db.commit()
    
    
    @staticmethod
    async def _send_notification(db: AsyncSession, channel: str, alert_record: AlertRecord, config: dict):
        """发送单个通知（webhook 复用 AlertService 统一实现；邮件走统一 SMTP helper）"""
        from src.services.alert_service import AlertService
        
        message = f"【专线到期告警】[{alert_record.severity.upper()}] {alert_record.message}"
        
        if channel == "dingtalk":
            await AlertService._send_dingtalk_notification(config["dingtalk_webhook_url"], message)
        elif channel == "wechat":
            await AlertService._send_wechat_notification(config["wechat_webhook_url"], message)
        elif channel == "feishu":
            await AlertService._send_feishu_notification(config["feishu_webhook_url"], message)
        elif channel == "email":
            from email.mime.text import MIMEText
            from email.utils import formataddr
            
            msg = MIMEText(message, 'plain', 'utf-8')
            msg['From'] = formataddr(('Cornerstone专线告警', config["smtp_from_email"]))
            msg['Subject'] = "【专线到期告警】"
            
            import asyncio as _asyncio
            def _smtp_send():
                with AlertService._smtp_connect(config) as server:
                    server.login(config["smtp_username"], config["smtp_password"])
                    server.sendmail(config["smtp_from_email"], [config["smtp_from_email"]], msg.as_string())
            await _asyncio.to_thread(_smtp_send)


circuit_expire_service = CircuitExpireService()