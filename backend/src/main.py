from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer

from .api import api_router
from .config import settings
from .utils import setup_logger
from .utils.ip_whitelist import check_ip_allowed
from .tasks.backup_scheduler import start_scheduler as start_backup_scheduler, reload_tasks, scheduler as backup_scheduler
from .services.scheduler_service import start_scheduler as start_monitor_scheduler
from .tasks.inspection_scheduler import init_inspection_scheduler, reload_inspection_tasks
from .tasks.ipam_scheduler import init_ipam_scheduler, reload_ipam_scan
from .tasks.log_cleanup import start_log_cleanup_scheduler
from .database import async_session
from .database import get_db

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    redirect_slashes=False,
    # 生产环境关闭 FastAPI 自动文档与 OpenAPI schema，避免暴露内部结构
    # dev(DEBUG=true) 保留 docs/redoc 方便联调；生产由 nginx 侧也对 /docs /redoc /openapi.json 做 deny all 双保险
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None,
)

# 设置日志
logger = setup_logger()

# CORS配置：从环境变量读取允许的来源
cors_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# IP白名单中间件：只允许配置的IP访问
@app.middleware("http")
async def ip_whitelist_middleware(request: Request, call_next):
    # 跳过公开端点（登录前可访问）
    # 注意：白名单自身的读写接口必须放行，否则配错白名单后无法在页面上自救
    # （这两个接口仍有 JWT + super_admin 鉴权，IP 层放行不降低身份安全性）
    public_paths = [
        "/", "/health",
        "/api/v1/settings/public/brand",
        "/api/v1/settings/logo",
        "/api/v1/auth/captcha",
        "/api/v1/auth/token",
        "/api/v1/auth/login-with-captcha",
        # 白名单自救：精确放行（仅 GET 读取与 PUT 保存两个端点，均有 JWT + 超管鉴权）
        "/api/v1/settings/security/ip-whitelist",
    ]
    if (request.url.path in public_paths or
        request.url.path.startswith("/api/v1/auth/sso/") or
        request.url.path in ("/api/v1/auth/ldap/enabled", "/api/v1/auth/ldap/login") or
        request.url.path.startswith("/api/v1/reports/monthly/shared-download/")):
        # ldap 仅放行登录链路必需的两个端点（enabled/login），config/test 等管理接口不放行
        # shared-download 为 HMAC 签名直链（验签+7天过期），IP 层放行不降低安全性
        return await call_next(request)

    # 检查IP是否允许
    async with async_session() as session:
        try:
            allowed = await check_ip_allowed(request, session)
            if not allowed:
                from .utils.ip_whitelist import get_client_ip_from_request
                client_ip = get_client_ip_from_request(request)
                logger.warning(f"[IP白名单] 拒绝访问: client_ip={client_ip} path={request.url.path}")
                return JSONResponse(
                    status_code=403,
                    content={"detail": "访问被拒绝：您的IP地址不在白名单中"}
                )
            return await call_next(request)
        except Exception:
            # 如果检查过程出错，默认允许访问（避免锁死系统）
            logger.error("[IP白名单] 检查过程出错，默认允许访问")
            return await call_next(request)

# 包含API路由
app.include_router(api_router, prefix="/api/v1")

@app.get("/")
async def root():
    return {"message": "Welcome to Cornerstone API", "version": settings.app_version}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.on_event("startup")
async def startup_event():
    """应用启动时执行的初始化操作"""
    from .services.permission_service import init_permissions, init_roles, init_default_admin
    
    # 导入所有模型以确保注册到 Base.metadata（建表由 Alembic 迁移负责）
    from .models import User, Role, Permission, RolePermission, UserSession
    from .models.site import Site
    from .models.device import Device
    from .models.circuit import Circuit
    from .models.ip_address import IPAddress
    from .models.prefix import Prefix
    from .models.vlan import Vlan, VlanGroup
    from .models.audit_log import AuditLog
    from .models.system_config import SystemConfig
    from .models.backup_analysis import BackupAnalysis
    from .models.inspection import InspectionTask, InspectionResult, InspectionDeviceResult, DeviceFingerprint
    from .models.rack import Rack
    from .models.knowledge import KnowledgeArticle
    
    # 初始化权限和角色
    async with async_session() as session:
        await init_permissions(session)
        logger.info("Permissions initialized")
        
        await init_roles(session)
        logger.info("Roles initialized")
        
        await init_default_admin(session)
        logger.info("Default admin user initialized")
    
    # 启动备份调度器
    start_backup_scheduler()
    logger.info("Backup scheduler started")
    
    # 从数据库加载所有启用的任务
    async with async_session() as session:
        await reload_tasks(session)
    logger.info("Backup tasks loaded from database")
    
    # 启动监控定时任务（默认5分钟）
    start_monitor_scheduler(5)
    logger.info("Monitor scheduler started with 5 minutes interval")
    
    # 初始化巡检调度器（复用备份调度器）
    init_inspection_scheduler(backup_scheduler)
    async with async_session() as session:
        await reload_inspection_tasks(session)
    logger.info("Inspection scheduler initialized")

    # 初始化 IPAM 自动扫描调度器
    init_ipam_scheduler(backup_scheduler)
    async with async_session() as session:
        await reload_ipam_scan(db=session)
    logger.info("IPAM scan scheduler initialized")
    
    # 启动日志清理定时任务
    await start_log_cleanup_scheduler()
    logger.info("Log cleanup scheduler started")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
