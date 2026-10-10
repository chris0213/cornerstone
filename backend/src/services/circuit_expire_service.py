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
        """创建专线到期告警记录"""
        existing_query = select(AlertRecord).where(
            AlertRecord.alert_type == "circuit_expire",
            AlertRecord.device_id == circuit.id,
            AlertRecord.status == "active"
        )
        existing_result = await db.execute(existing_query)
        existing_alert = existing_result.scalar_one_or_none()
        
        if existing_alert:
            # 检查是否需要重新发送通知
            old_severity = existing_alert.severity
            existing_alert.message = message
            existing_alert.severity = severity
            existing_alert.current_value = (circuit.contract_end - datetime.now()).days
            await db.flush()
            
            # 如果严重度升级，需要重新发送通知
            severity_order = {"info": 0, "warning": 1, "critical": 2}
            old_level = severity_order.get(old_severity, 0)
            new_level = severity_order.get(severity, 0)
            
            if new_level > old_level:
                print(f"专线 [{circuit.name}] 告警严重度升级: {old_severity} -> {severity}, 重新发送通知")
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
                    hours_since_last_notification = (datetime.now() - last_notification.sent_at).total_seconds() / 3600
                    if hours_since_last_notification >= 24:
                        print(f"专线 [{circuit.name}] 告警已超过24小时，重新发送通知")
                        await CircuitExpireService._send_expire_notifications(db, existing_alert)
                elif not last_notification:
                    # 从未发送过通知，立即发送
                    print(f"专线 [{circuit.name}] 告警从未发送过通知，立即发送")
                    await CircuitExpireService._send_expire_notifications(db, existing_alert)
        else:
            acknowledged_query = select(AlertRecord).where(
                AlertRecord.alert_type == "circuit_expire",
                AlertRecord.device_id == circuit.id,
                AlertRecord.status == "acknowledged",
                AlertRecord.acknowledged_at.isnot(None)
            ).order_by(AlertRecord.acknowledged_at.desc()).limit(1)
            acknowledged_result = await db.execute(acknowledged_query)
            acknowledged_alert = acknowledged_result.scalar_one_or_none()
            
            if acknowledged_alert:
                acknowledge_time = acknowledged_alert.acknowledged_at
                if acknowledge_time and (datetime.now() - acknowledge_time).days < 7:
                    print(f"专线 [{circuit.name}] 的到期告警已在 {acknowledge_time} 被确认，7天内不再重复通知")
                    return
            
            alert_record = AlertRecord(
                rule_id=None,
                device_id=circuit.id,
                target_ip=circuit.public_ip or "",
                alert_type="circuit_expire",
                severity=severity,
                message=message,
                current_value=(circuit.contract_end - datetime.now()).days,
                threshold=0
            )
            db.add(alert_record)
            await db.flush()
            
            await CircuitExpireService._send_expire_notifications(db, alert_record)

            # 实时推送给在线前端（失败不影响告警落库）
            await broadcast_new_alert(alert_record)
    
    @staticmethod
    async def _send_expire_notifications(db: AsyncSession, alert_record: AlertRecord):
        """发送专线到期通知"""
        config = await CircuitExpireService._get_notification_config(db)
        
        enabled_channels = []
        if config.get("dingtalk_webhook_url"):
            enabled_channels.append("dingtalk")
        if config.get("wechat_webhook_url"):
            enabled_channels.append("wechat")
        if config.get("feishu_webhook_url"):
            enabled_channels.append("feishu")
        if all([config.get("smtp_host"), config.get("smtp_username"), 
               config.get("smtp_password"), config.get("smtp_from_email")]):
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
                notification.error_message = str(e)
    
    @staticmethod
    async def _get_notification_config(db: AsyncSession) -> dict:
        """获取通知配置"""
        result = await db.execute(select(Setting).filter(Setting.key == NOTIFICATION_SETTINGS_KEY))
        setting = result.scalars().first()
        
        config = {}
        if setting:
            try:
                config = json.loads(setting.value)
            except json.JSONDecodeError:
                pass
        
        return {
            "dingtalk_webhook_url": config.get("dingtalk_webhook_url") or settings.notification.dingtalk_webhook_url,
            "wechat_webhook_url": config.get("wechat_webhook_url") or settings.notification.wechat_webhook_url,
            "feishu_webhook_url": config.get("feishu_webhook_url") or settings.notification.feishu_webhook_url,
            "smtp_host": config.get("smtp_host") or settings.notification.smtp_host,
            "smtp_port": config.get("smtp_port") or settings.notification.smtp_port,
            "smtp_username": config.get("smtp_username") or settings.notification.smtp_username,
            "smtp_password": config.get("smtp_password") or settings.notification.smtp_password,
            "smtp_from_email": config.get("smtp_from_email") or settings.notification.smtp_from_email
        }
    
    @staticmethod
    async def _send_notification(db: AsyncSession, channel: str, alert_record: AlertRecord, config: dict):
        """发送单个通知"""
        import httpx
        from email.mime.text import MIMEText
        from email.utils import formataddr
        import smtplib
        
        message = f"【专线到期告警】[{alert_record.severity.upper()}] {alert_record.message}"
        
        if channel == "dingtalk":
            async with httpx.AsyncClient() as client:
                payload = {
                    "msgtype": "text",
                    "text": {
                        "content": message
                    }
                }
                response = await client.post(config["dingtalk_webhook_url"], json=payload, timeout=10)
                response.raise_for_status()
        
        elif channel == "wechat":
            async with httpx.AsyncClient() as client:
                payload = {
                    "msgtype": "text",
                    "text": {
                        "content": message
                    }
                }
                response = await client.post(config["wechat_webhook_url"], json=payload, timeout=10)
                response.raise_for_status()
        
        elif channel == "feishu":
            async with httpx.AsyncClient() as client:
                payload = {
                    "msg_type": "text",
                    "content": {
                        "text": message
                    }
                }
                response = await client.post(config["feishu_webhook_url"], json=payload, timeout=10)
                response.raise_for_status()
        
        elif channel == "email":
            msg = MIMEText(message, 'plain', 'utf-8')
            msg['From'] = formataddr(('Cornerstone专线告警', config["smtp_from_email"]))
            msg['Subject'] = "【专线到期告警】"
            
            with smtplib.SMTP(config["smtp_host"], config["smtp_port"]) as server:
                server.starttls()
                server.login(config["smtp_username"], config["smtp_password"])
                server.sendmail(config["smtp_from_email"], [config["smtp_from_email"]], msg.as_string())


circuit_expire_service = CircuitExpireService()