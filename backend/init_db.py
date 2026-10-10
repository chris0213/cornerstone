#!/usr/bin/env python3
"""初始化数据库"""
import os
import sys
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from passlib.context import CryptContext
import sqlalchemy.orm
from src.database import sync_engine
from src.models import Aggregate, AuditLog, Backup, Circuit, Device, IPAddress, Prefix, Site, User, Vlan, VlanGroup, Role, Permission, RolePermission
from src.models.device_link import DeviceLink
from src.models.alert import AlertRule  # 确保关联模型被加载

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def seed_demo_data(session: sqlalchemy.orm.Session):
    """写入脱敏演示数据，仅在空库中执行。"""
    # 检查核心实体（devices）是否已有数据，避免重复写入
    if session.query(Device).first():
        return

    sites = [
        Site(id=1, name="演示站点A", location="示例园区A · 101机房", city="示例城市A", room="101机房", contact="演示管理员", contact_phone="010-0000-0001", status="online", alert_count=0),
        Site(id=2, name="演示站点B", location="示例园区B · 201机房", city="示例城市B", room="201机房", contact="演示操作员", contact_phone="010-0000-0002", status="alert", alert_count=2),
        Site(id=3, name="演示实验室", location="示例实验室 · 机柜区", city="示例城市C", room="实验室机柜区", contact="演示观察员", contact_phone="010-0000-0003", status="offline", alert_count=0),
    ]
    session.add_all(sites)
    session.flush()

    aggregates = [
        Aggregate(id=1, network="192.0.2.0/24", name="演示管理地址池"),
        Aggregate(id=2, network="198.51.100.0/24", name="演示实验室地址池"),
    ]
    session.add_all(aggregates)

    prefixes = [
        Prefix(id=1, aggregate_id=1, network="192.0.2.0/26", site_id=1, vlan="10", usage="演示办公网络"),
        Prefix(id=2, aggregate_id=1, network="192.0.2.64/26", site_id=1, vlan="20", usage="演示管理网络"),
        Prefix(id=3, aggregate_id=1, network="192.0.2.128/26", site_id=2, vlan="30", usage="演示分支网络"),
        Prefix(id=4, aggregate_id=2, network="198.51.100.0/26", site_id=3, vlan="120", usage="演示实验室网络"),
    ]
    session.add_all(prefixes)
    session.flush()

    devices = [
        Device(id=1, name="SW-DEMO-CORE-01", type="交换机", brand="Cisco", vendor="cisco_ios", model="Catalyst 9300", sn="DEMO-SW-0001", site_id=1, location="演示机柜A-U12", status="active", purchase_date=datetime(2024, 3, 12), warranty_end=datetime(2026, 6, 18), purchase_amount=82000, owner="演示网络组", note="演示核心交换机"),
        Device(id=2, name="FW-DEMO-EDGE-01", type="防火墙", brand="Huawei", vendor="huawei_vrp", model="USG6655E", sn="DEMO-FW-0001", site_id=1, location="演示机柜B-U06", status="active", purchase_date=datetime(2023, 8, 20), warranty_end=datetime(2026, 5, 30), purchase_amount=128000, owner="演示安全组", note="演示互联网边界防火墙"),
        Device(id=3, name="RT-DEMO-WAN-01", type="路由器", brand="H3C", vendor="h3c", model="MSR 5660", sn="DEMO-RT-0001", site_id=2, location="演示机柜C-U08", status="maintenance", purchase_date=datetime(2022, 10, 1), warranty_end=datetime(2026, 12, 1), purchase_amount=64000, owner="演示网络组", note="演示广域网边界路由器"),
        Device(id=4, name="SW-DEMO-ACC-01", type="交换机", brand="Huawei", vendor="huawei_vrp", model="S5735-L24T4X-A", sn="DEMO-SW-0002", site_id=1, location="演示机柜A-U08", status="active", purchase_date=datetime(2024, 5, 20), warranty_end=datetime(2027, 5, 20), purchase_amount=18000, owner="演示网络组", note="演示接入交换机-24口"),
        Device(id=5, name="SW-DEMO-ACC-02", type="交换机", brand="Huawei", vendor="huawei_vrp", model="S5735-L24T4X-A", sn="DEMO-SW-0003", site_id=1, location="演示机柜A-U09", status="active", purchase_date=datetime(2024, 5, 20), warranty_end=datetime(2027, 5, 20), purchase_amount=18000, owner="演示网络组", note="演示接入交换机-24口"),
        Device(id=6, name="SRV-DEMO-APP-01", type="服务器", brand="Dell", vendor="dell_os10", model="PowerEdge R750", sn="DEMO-SRV-0001", site_id=1, location="演示机柜D-U04", status="active", purchase_date=datetime(2023, 11, 15), warranty_end=datetime(2026, 11, 15), purchase_amount=45000, owner="演示运维组", note="演示应用服务器"),
    ]
    session.add_all(devices)
    session.flush()

    ip_addresses = [
        IPAddress(id=1, address="192.0.2.65", prefix_id=2, device_id=1, usage="演示核心交换机管理地址", owner="演示网络组", status="assigned"),
        IPAddress(id=2, address="192.0.2.66", prefix_id=2, device_id=2, usage="演示防火墙管理地址", owner="演示安全组", status="assigned"),
        IPAddress(id=3, address="192.0.2.129", prefix_id=3, device_id=3, usage="演示分支路由器管理地址", owner="演示网络组", status="assigned"),
        IPAddress(id=4, address="198.51.100.10", prefix_id=4, usage="演示实验室预留主机", owner="演示实验室", status="reserved"),
        IPAddress(id=5, address="192.0.2.67", prefix_id=2, device_id=4, usage="演示接入交换机管理地址", owner="演示网络组", status="assigned"),
        IPAddress(id=6, address="192.0.2.68", prefix_id=2, device_id=5, usage="演示接入交换机管理地址", owner="演示网络组", status="assigned"),
        IPAddress(id=7, address="192.0.2.69", prefix_id=2, device_id=6, usage="演示应用服务器管理地址", owner="演示运维组", status="assigned"),
    ]
    session.add_all(ip_addresses)
    session.flush()
    for device_id, mgmt_ip_id in [(1, 1), (2, 2), (3, 3), (4, 5), (5, 6), (6, 7)]:
        session.query(Device).filter(Device.id == device_id).update({"mgmt_ip_id": mgmt_ip_id})
    session.flush()

    circuits = [
        Circuit(name="演示站点A互联网专线", provider="演示运营商A", type="互联网专线", site_id=1, bandwidth=1000, monthly_cost=18800, contract_start=datetime(2025, 7, 1), contract_end=datetime(2026, 6, 12), circuit_no="DEMO-INET-001", support_phone="010-0000-1001", public_ip="203.0.113.8/29", status="正常", note="演示主用互联网专线", updated_by="admin"),
        Circuit(name="演示站点A-B MPLS专线", provider="演示运营商B", type="MPLS", site_id=2, bandwidth=500, monthly_cost=22600, contract_start=datetime(2025, 4, 20), contract_end=datetime(2026, 5, 28), circuit_no="DEMO-MPLS-002", support_phone="010-0000-1002", public_ip="", status="正常", note="演示私有广域网专线", updated_by="ops"),
        Circuit(name="演示实验室SD-WAN备份", provider="演示运营商C", type="SD-WAN", site_id=3, bandwidth=200, monthly_cost=5200, contract_start=datetime(2024, 11, 1), contract_end=datetime(2026, 11, 1), circuit_no="DEMO-SDWAN-003", support_phone="010-0000-1003", public_ip="198.51.100.16/28", status="故障", note="演示降级备份链路", updated_by="ops"),
    ]
    session.add_all(circuits)
    session.flush()

    backups = [
        Backup(device_id=1, version=1, content="hostname SW-DEMO-CORE-01\ninterface Vlan20\n ip address 192.0.2.65 255.255.255.192\nspanning-tree mode rapid-pvst\nntp server 192.0.2.10\nline vty 0 4\n transport input ssh", trigger="scheduled", operator="system", status="success", has_change=False, size=1186, note="演示每日备份"),
        Backup(device_id=1, version=2, content="hostname SW-DEMO-CORE-01\ninterface Vlan20\n ip address 192.0.2.65 255.255.255.192\nspanning-tree mode rapid-pvst\nntp server 192.0.2.10\nntp server 192.0.2.11\nline vty 0 4\n transport input ssh", trigger="scheduled", operator="system", status="success", has_change=True, change_summary="演示新增NTP服务器", size=1224, note="演示每日备份"),
        Backup(device_id=2, version=1, content="", trigger="scheduled", operator="system", status="failed", error_message="演示SSH连接超时", has_change=False, size=0, note="演示SSH连接超时"),
    ]
    session.add_all(backups)

    vlan_groups = [
        VlanGroup(id=1, name="演示站点A VLAN组", site_id=1, description="演示站点A的VLAN分组"),
        VlanGroup(id=2, name="演示站点B VLAN组", site_id=2, description="演示站点B的VLAN分组"),
        VlanGroup(id=3, name="演示实验室 VLAN组", site_id=3, description="演示实验室的VLAN分组"),
    ]
    session.add_all(vlan_groups)
    session.flush()

    vlans = [
        Vlan(vid=10, name="演示办公网络", group_id=1, site_id=1, status="active", description="演示办公网络VLAN"),
        Vlan(vid=20, name="演示管理网络", group_id=1, site_id=1, status="active", description="演示设备管理VLAN"),
        Vlan(vid=30, name="演示服务器网络", group_id=1, site_id=1, status="active", description="演示服务器VLAN"),
        Vlan(vid=10, name="演示分支办公网络", group_id=2, site_id=2, status="active", description="演示分支办公网络VLAN"),
        Vlan(vid=120, name="演示实验室网络", group_id=3, site_id=3, status="active", description="演示实验室网络VLAN"),
        Vlan(vid=999, name="演示DMZ网络", status="reserved", description="演示预留DMZ VLAN"),
    ]
    session.add_all(vlans)
    session.flush()

    device_links = [
        DeviceLink(id=1, source_device_id=1, source_interface="GigabitEthernet1/0/1", target_device_id=2, target_interface="GigabitEthernet0/0/1", link_type="manual", confidence=100),
        DeviceLink(id=2, source_device_id=2, source_interface="GigabitEthernet0/0/2", target_device_id=3, target_interface="GigabitEthernet0/0/1", link_type="manual", confidence=100),
        DeviceLink(id=3, source_device_id=1, source_interface="GigabitEthernet1/0/2", target_device_id=4, target_interface="GigabitEthernet0/0/24", link_type="lldp", confidence=95),
        DeviceLink(id=4, source_device_id=1, source_interface="GigabitEthernet1/0/3", target_device_id=5, target_interface="GigabitEthernet0/0/24", link_type="lldp", confidence=95),
        DeviceLink(id=5, source_device_id=1, source_interface="GigabitEthernet1/0/4", target_device_id=6, target_interface="eth0", link_type="manual", confidence=100),
    ]
    session.add_all(device_links)
    session.flush()

    audit_logs = [
        AuditLog(user="ops", action="更新专线状态", resource="演示实验室SD-WAN备份", detail="状态由 正常 改为 故障", ip_address="192.0.2.200", success="true"),
        AuditLog(user="system", action="配置备份", resource="FW-DEMO-EDGE-01", detail="备份失败：SSH连接超时", ip_address="127.0.0.1", success="false"),
    ]
    session.add_all(audit_logs)


def _seed_permissions_and_roles(session):
    """初始化默认权限和角色（与 permission_service.py 数据一致）"""

    # 权限定义
    permissions_data = [
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
        # IPAM
        {"module": "ipam", "action": "read", "display_name": "IP管理-查看", "description": "查看IP地址列表"},
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

    # 创建权限
    perm_map = {}
    for pd in permissions_data:
        existing = session.query(Permission).filter(
            Permission.module == pd["module"],
            Permission.action == pd["action"]
        ).first()
        if not existing:
            p = Permission(**pd)
            session.add(p)
            session.flush()
            perm_map[f"{pd['module']}:{pd['action']}"] = p.id
        else:
            perm_map[f"{pd['module']}:{pd['action']}"] = existing.id

    # 角色定义
    roles_data = [
        {
            "name": "super_admin",
            "display_name": "超级管理员",
            "description": "所有权限，包括用户管理、系统设置，唯一可以管理其他用户角色的账号",
            "is_builtin": True,
            "permissions": ["all"]
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

    for rd in roles_data:
        role = session.query(Role).filter(Role.name == rd["name"]).first()
        if not role:
            role = Role(
                name=rd["name"],
                display_name=rd["display_name"],
                description=rd["description"],
                is_builtin=rd["is_builtin"]
            )
            session.add(role)
            session.flush()

        # 分配权限（super_admin 分配所有权限）
        if rd["permissions"] == ["all"]:
            for perm_key, perm_id in perm_map.items():
                existing_rp = session.query(RolePermission).filter(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == perm_id
                ).first()
                if not existing_rp:
                    rp = RolePermission(role_id=role.id, permission_id=perm_id)
                    session.add(rp)
        else:
            for perm_key in rd["permissions"]:
                if perm_key in perm_map:
                    existing_rp = session.query(RolePermission).filter(
                        RolePermission.role_id == role.id,
                        RolePermission.permission_id == perm_map[perm_key]
                    ).first()
                    if not existing_rp:
                        rp = RolePermission(role_id=role.id, permission_id=perm_map[perm_key])
                        session.add(rp)

    session.flush()
    print("默认权限和角色初始化成功！")


def init_db():
    """初始化种子数据（建表由 Alembic 迁移负责，本函数不创建/修改表结构）"""
    print("初始化种子数据...")
    initial_admin_password = os.environ.get("INITIAL_ADMIN_PASSWORD", "password")
    hashed_password = pwd_context.hash(initial_admin_password)

    with sqlalchemy.orm.Session(sync_engine) as session:
        # 初始化默认权限和角色
        _seed_permissions_and_roles(session)

        existing_admin = session.query(User).filter(User.username == "admin").first()
        if not existing_admin:
            # 查找 super_admin 角色
            admin_role = session.query(Role).filter(Role.name == "super_admin").first()
            admin_user = User(
                username="admin",
                email="admin@example.com",
                hashed_password=hashed_password,
                display_name="管理员",
                role_id=admin_role.id if admin_role else None,
                is_active=True,
                is_superuser=True,
            )
            session.add(admin_user)

            # 查找 engineer 角色
            eng_role = session.query(Role).filter(Role.name == "engineer").first()
            test_user = User(
                username="user",
                email="user@example.com",
                hashed_password=pwd_context.hash("user123"),
                display_name="测试用户",
                role_id=eng_role.id if eng_role else None,
                is_active=True,
                is_superuser=False,
            )
            session.add(test_user)
            session.flush()
            print("默认用户创建成功！")
        else:
            print("管理员用户已存在，跳过创建。")

            # 对现有 admin 用户补全 role_id（如果为空）
            if existing_admin.role_id is None:
                admin_role = session.query(Role).filter(Role.name == "super_admin").first()
                if admin_role:
                    existing_admin.role_id = admin_role.id
                    print(f"已补全 admin 用户 role_id = {admin_role.id}")

            # 对现有 user 用户补全 role_id（如果为空）
            existing_user = session.query(User).filter(User.username == "user").first()
            if existing_user and existing_user.role_id is None:
                eng_role = session.query(Role).filter(Role.name == "engineer").first()
                if eng_role:
                    existing_user.role_id = eng_role.id
                    print(f"已补全 user 用户 role_id = {eng_role.id}")

        # 写入演示数据（空库或首次运行）
        seed_demo_data(session)
        session.commit()

    print("\n默认账号:")
    print("  管理员: admin / INITIAL_ADMIN_PASSWORD 环境变量指定的密码（未设置时为开发默认 password）")
    print("  普通用户: user / user123")


if __name__ == "__main__":
    init_db()
