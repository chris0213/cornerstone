import logging
from typing import Optional
from datetime import datetime

logger = None

def setup_logger(name: str = "cornerstone", level: int = logging.INFO) -> logging.Logger:
    global logger
    if logger is None:
        logger = logging.getLogger(name)
        logger.setLevel(level)
        
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    return logger

def get_logger() -> logging.Logger:
    global logger
    if logger is None:
        return setup_logger()
    return logger

async def audit_log(db_session, username: str, resource_type: str, resource_id: int, 
                   action: str, details: dict = None, ip_address: str | None = None):
    """记录审计日志到数据库。username 为操作者用户名（与登录/SSO/设置类审计口径统一）。"""
    from ..models import AuditLog
    import json
    
    log_entry = AuditLog(
        user=username,
        resource=f"{resource_type}:{resource_id}",
        action=action,
        detail=json.dumps(details or {}),
        ip_address=ip_address
    )
    db_session.add(log_entry)
    await db_session.commit()
