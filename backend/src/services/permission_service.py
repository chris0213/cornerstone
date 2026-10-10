import os

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from passlib.context import CryptContext

from ..models.user import Role, Permission, RolePermission, User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 权限定义
PERMISSIONS = [
    # 站点管理
    {"module": "sites", "action": "read", "display_name": "站点管理-查看", "description": "查看站点列表和详情"},
    {"module": "sites", "action": "write", "display_name": "站点管理-新增编辑", "description": "新增和编辑站点"},
    {"module": "sites", "action": "delete", "display_name": "站点管理-删除", "description": "删除站点"},
    {"module": "sites", "action": "export", "display_name": "站点管理-导出", "description": "导出站点数据"},
    
    # 专线管理
    {"module": "circuits", "action": "read", "display_name": "专线管理-查看", "description": "查看专线列表和详情"},
    {"module": "circuits", "action": "write", "display_name": "专线管理-新增编辑", "description": "新增和编辑专线"},
    {"module": "circuits", "action": "delete", "display_name": "专线管理-删除", "description": "删除专线"},
    {"module": "circuits", "action": "export", "display_name": "专线管理-导出", "description": "导出专线数据"},
    
    # IP地址管理
    {"module": "ipam", "action": "read", "display_name": "IP管理-查看", "description": "查看IP地址列表和详情"},
    {"module": "ipam", "action": "write", "display_name": "IP管理-新增编辑", "description": "新增和编辑IP地址"},
    {"module": "ipam", "action": "delete", "display_name": "IP管理-删除", "description": "删除IP地址"},
    {"module": "ipam", "action": "export", "display_name": "IP管理-导出", "description": "导出IP地址数据"},
    {"module": "ipam", "action": "scan_exec", "display_name": "IP管理-扫描", "description": "触发IP扫描"},
    
    # 设备台账
    {"module": "devices", "action": "read", "display_name": "设备管理-查看", "description": "查看设备列表和详情"},
    {"module": "devices", "action": "write", "display_name": "设备管理-新增编辑", "description": "新增和编辑设备"},
    {"module": "devices", "action": "delete", "display_name": "设备管理-删除", "description": "删除设备"},
    {"module": "devices", "action": "export", "display_name": "设备管理-导出", "description": "导出设备数据"},
    
    # 配置备份
    {"module": "backups", "action": "read", "display_name": "备份管理-查看", "description": "查看备份列表和详情"},
    {"module": "backups", "action": "write", "display_name": "备份管理-新增编辑", "description": "新增和编辑备份任务"},
    {"module": "backups", "action": "delete", "display_name": "备份管理-删除", "description": "删除备份记录"},
    {"module": "backups", "action": "export", "display_name": "备份管理-导出", "description": "导出备份数据"},
    {"module": "backups", "action": "backup_exec", "display_name": "备份管理-执行", "description": "触发备份任务"},
    
    # 网络拓扑
    {"module": "topology", "action": "read", "display_name": "拓扑管理-查看", "description": "查看网络拓扑"},
    {"module": "topology", "action": "write", "display_name": "拓扑管理-编辑", "description": "编辑拓扑布局"},
    {"module": "topology", "action": "delete", "display_name": "拓扑管理-删除", "description": "删除拓扑数据"},
    
    # 预警中心
    {"module": "alerts", "action": "read", "display_name": "预警管理-查看", "description": "查看预警信息"},

    # 运营月报
    {"module": "reports", "action": "read", "display_name": "运营月报-查看", "description": "查看和下载运营月报"},

    # 智能巡检
    {"module": "inspection", "action": "read", "display_name": "智能巡检-查看", "description": "查看智能巡检任务与结果"},

    # 系统管理
    {"module": "system", "action": "read", "display_name": "系统管理-查看", "description": "查看系统设置"},
    {"module": "system", "action": "write", "display_name": "系统管理-编辑", "description": "编辑系统设置"},
    {"module": "system", "action": "delete", "display_name": "系统管理-删除", "description": "删除系统数据"},
    {"module": "system", "action": "admin", "display_name": "系统管理-高级", "description": "用户/角色/SSO/安全/通知/日志等高级系统管理"},
    
    # 操作日志
    {"module": "logs", "action": "read", "display_name": "日志管理-查看", "description": "查看操作日志"},
    
    # 首页仪表盘
    {"module": "dashboard", "action": "read", "display_name": "仪表盘-查看", "description": "查看仪表盘数据"},
    
    # 用户管理
    {"module": "users", "action": "read", "display_name": "用户管理-查看", "description": "查看用户列表"},
    {"module": "users", "action": "write", "display_name": "用户管理-新增编辑", "description": "新增和编辑用户"},
    {"module": "users", "action": "delete", "display_name": "用户管理-删除", "description": "删除用户"},
]

# 角色定义
ROLES = [
    {
        "name": "super_admin",
        "display_name": "超级管理员",
        "description": "所有权限，包括用户管理、系统设置，唯一可以管理其他用户角色的账号",
        "is_builtin": True,
        "permissions": ["all"]  # 所有权限
    },
    {
        "name": "engineer",
        "display_name": "IT运维工程师",
        "description": "所有业务模块读写权限，不可操作用户管理和系统设置",
        "is_builtin": True,
        "permissions": [
            "sites:read", "sites:write", "sites:delete", "sites:export",
            "circuits:read", "circuits:write", "circuits:delete", "circuits:export",
            "ipam:read", "ipam:write", "ipam:delete", "ipam:export", "ipam:scan_exec",
            "devices:read", "devices:write", "devices:delete", "devices:export",
            "backups:read", "backups:write", "backups:delete", "backups:export", "backups:backup_exec",
            "topology:read", "topology:write", "topology:delete",
            "alerts:read",
            "inspection:read",
            "logs:read"
        ]
    },
    {
        "name": "viewer",
        "display_name": "IT负责人",
        "description": "管理看板、审批操作、月报下载",
        "is_builtin": True,
        "permissions": [
            "dashboard:read",
            "circuits:read",
            "alerts:read",
            "reports:read",
            "inspection:read",
            "logs:read"
        ]
    }
]

async def init_permissions(db: AsyncSession):
    """初始化权限定义"""
    for perm_data in PERMISSIONS:
        stmt = select(Permission).where(
            Permission.module == perm_data["module"],
            Permission.action == perm_data["action"]
        )
        result = await db.execute(stmt)
        existing = result.scalars().first()
        
        if not existing:
            permission = Permission(**perm_data)
            db.add(permission)
    
    await db.commit()

async def init_roles(db: AsyncSession):
    """初始化角色及其权限"""
    for role_data in ROLES:
        stmt = select(Role).where(Role.name == role_data["name"])
        result = await db.execute(stmt)
        role = result.scalar_one_or_none()
        
        # 更新或创建角色
        if not role:
            role = Role(
                name=role_data["name"],
                display_name=role_data["display_name"],
                description=role_data["description"],
                is_builtin=role_data["is_builtin"]
            )
            db.add(role)
            await db.flush()
        else:
            # 更新角色信息
            role.display_name = role_data["display_name"]
            role.description = role_data["description"]
        
        # 清除该角色的所有现有权限
        stmt_delete = select(RolePermission).where(RolePermission.role_id == role.id)
        result_delete = await db.execute(stmt_delete)
        for rp in result_delete.scalars().all():
            await db.delete(rp)
        
        # 获取该角色应有的权限列表
        perm_list = role_data["permissions"]
        
        # 获取所有权限
        stmt = select(Permission)
        result = await db.execute(stmt)
        all_permissions = result.scalars().all()
        
        # 超级管理员拥有所有权限
        if perm_list == ["all"]:
            perm_list = [f"{p.module}:{p.action}" for p in all_permissions]
        
        # 为角色添加权限
        for perm_str in perm_list:
            module, action = perm_str.split(":")
            stmt = select(Permission).where(
                Permission.module == module,
                Permission.action == action
            )
            result = await db.execute(stmt)
            permission = result.scalars().first()
            
            if permission:
                rp = RolePermission(role_id=role.id, permission_id=permission.id)
                db.add(rp)
    
    await db.commit()

async def init_default_admin(db: AsyncSession):
    """初始化默认超级管理员账号"""
    stmt = select(func.count(User.id))
    result = await db.execute(stmt)
    count = result.scalar_one()
    
    if count == 0:
        # 获取超级管理员角色
        stmt = select(Role).where(Role.name == "super_admin")
        result = await db.execute(stmt)
        admin_role = result.scalar_one_or_none()
        
        if admin_role:
            initial_password = os.environ.get("INITIAL_ADMIN_PASSWORD", "password")
            hashed_password = pwd_context.hash(initial_password)
            admin_user = User(
                username="admin",
                display_name="管理员",
                email="admin@example.com",
                hashed_password=hashed_password,
                role_id=admin_role.id,
                is_active=True,
                is_superuser=True
            )
            db.add(admin_user)
            await db.commit()

async def get_user_permissions(db: AsyncSession, user_id: int) -> list[str]:
    """获取用户的所有权限列表"""
    # 先获取用户的角色
    stmt_user = select(User).where(User.id == user_id)
    result_user = await db.execute(stmt_user)
    user = result_user.scalar_one_or_none()
    
    if not user:
        return []
    
    # 检查是否是超级管理员（或者角色有 "all" 权限）
    stmt_role = select(Role).where(Role.id == user.role_id)
    result_role = await db.execute(stmt_role)
    role = result_role.scalar_one_or_none()
    
    # 查找 ROLES 配置中是否有 "all" 权限的定义
    if role is None:
        return []

    for role_config in ROLES:
        if role_config["name"] == role.name:
            if "all" in role_config["permissions"]:
                # 返回所有权限
                stmt_all_perms = select(Permission)
                result_all = await db.execute(stmt_all_perms)
                all_perms = result_all.scalars().all()
                return [f"{p.module}:{p.action}" for p in all_perms]
            break
    
    # 正常获取权限
    stmt = select(Permission).join(
        RolePermission, RolePermission.permission_id == Permission.id
    ).join(
        Role, Role.id == RolePermission.role_id
    ).join(
        User, User.role_id == Role.id
    ).where(User.id == user_id)
    
    result = await db.execute(stmt)
    permissions = result.scalars().all()
    
    return [f"{p.module}:{p.action}" for p in permissions]

async def has_permission(db: AsyncSession, user_id: int, module: str, action: str) -> bool:
    """检查用户是否拥有指定权限"""
    permissions = await get_user_permissions(db, user_id)
    return f"{module}:{action}" in permissions

async def get_role_by_name(db: AsyncSession, role_name: str) -> Role | None:
    """根据角色名获取角色"""
    stmt = select(Role).where(Role.name == role_name)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

async def get_all_roles(db: AsyncSession) -> list[Role]:
    """获取所有角色"""
    stmt = select(Role)
    result = await db.execute(stmt)
    return result.scalars().all()

async def get_all_permissions(db: AsyncSession) -> list[Permission]:
    """获取所有权限"""
    stmt = select(Permission)
    result = await db.execute(stmt)
    return result.scalars().all()
