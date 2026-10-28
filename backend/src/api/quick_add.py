from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert
from pydantic import BaseModel
import asyncio
import re

from ..database import get_db
from ..models import Device, IPAddress, Credential, Site
from ..services.backup_collector import VENDOR_MAP, TEST_COMMANDS
from ..utils.crypto import encrypt_password
from .dependencies import get_current_active_user, require_permission
from .backups import _check_credential_test_target

router = APIRouter(tags=["quick-add"])


class TestConnectionRequest(BaseModel):
    ip_address: str
    vendor: str
    username: str
    password: str
    port: int = 22
    enable_password: str | None = None


class TestConnectionResponse(BaseModel):
    success: bool
    message: str
    device_info: dict | None = None


class QuickAddDeviceRequest(BaseModel):
    name: str
    ip_address: str
    prefix_id: int | None = None
    site_id: int | None = None
    vendor: str
    username: str
    password: str
    port: int = 22
    enable_password: str | None = None
    type: str = "switch"
    location: str = ""
    owner: str = ""


class QuickAddDeviceResponse(BaseModel):
    success: bool
    message: str
    device_id: int | None = None


async def test_device_connection(ip_address: str, vendor: str, username: str, password: str, 
                                 port: int = 22, enable_password: str | None = None) -> tuple[bool, str, dict | None]:
    try:
        if vendor not in VENDOR_MAP:
            return False, f"不支持的厂商类型: {vendor}", None
        
        netmiko_device_type = VENDOR_MAP[vendor]
        test_command = TEST_COMMANDS.get(vendor, "show version")
        
        from netmiko import ConnectHandler
        
        device_params = {
            "device_type": netmiko_device_type,
            "ip": ip_address,
            "username": username,
            "password": password,
            "port": port,
            "timeout": 15,
            "conn_timeout": 10,
        }
        
        if enable_password:
            device_params["secret"] = enable_password
        
        with ConnectHandler(**device_params) as conn:
            if enable_password:
                conn.enable()
            
            output = conn.send_command(test_command, read_timeout=10)
            
            device_info = {
                "ip_address": ip_address,
                "vendor": vendor,
                "output": output[:500] if output else "",
            }
            
            if "Version" in output or "version" in output.lower():
                version_match = re.search(r'Version\s+([\d.]+)', output, re.IGNORECASE)
                if version_match:
                    device_info["version"] = version_match.group(1)
            
            model_match = re.search(r'Model\s*[:=]\s*([\w-]+)', output, re.IGNORECASE)
            if not model_match:
                model_match = re.search(r'Cisco\s+([\w-]+)', output)
            if model_match:
                device_info["model"] = model_match.group(1)
            
            return True, "连接成功", device_info
    
    except Exception as e:
        return False, f"连接失败: {str(e)}", None


@router.post("/test-connection", response_model=TestConnectionResponse)
async def test_connection(
    request: TestConnectionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_active_user)
):
    # R5：测试目标 IP 必须是私网段或设备表内已登记 IP（此处不做限流）
    await _check_credential_test_target(request.ip_address, db)

    success, message, device_info = await test_device_connection(
        ip_address=request.ip_address,
        vendor=request.vendor,
        username=request.username,
        password=request.password,
        port=request.port,
        enable_password=request.enable_password
    )
    
    return {
        "success": success,
        "message": message,
        "device_info": device_info
    }


@router.post("/quick-add", response_model=QuickAddDeviceResponse)
async def quick_add_device(
    request: QuickAddDeviceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("devices:write"))
):
    try:
        ip_address = None
        existing_ip = await db.execute(
            select(IPAddress).where(IPAddress.address == request.ip_address)
        )
        existing_ip = existing_ip.scalar_one_or_none()

        if existing_ip:
            # 区分「扫描发现/预登记的未归属记录」与「已被其他设备占用」：
            # 网段扫描会把在线 IP 自动入库占位（status=已分配），此时添加设备应接管该记录，
            # 而不是报错阻断；仅当 IP 已作为其他设备的管理 IP 时才是真冲突。
            used_by = (await db.execute(
                select(Device).where(Device.mgmt_ip_id == existing_ip.id)
            )).scalars().first()
            if used_by:
                return {
                    "success": False,
                    "message": f"IP地址 {request.ip_address} 已被设备「{used_by.name}」占用",
                    "device_id": None
                }
            # 接管扫描占位/预登记记录
            ip_address = existing_ip
            existing_ip.status = "已分配"
            existing_ip.usage = "管理IP"
            if request.prefix_id and existing_ip.prefix_id is None:
                existing_ip.prefix_id = request.prefix_id

        if ip_address is None:
            if request.prefix_id:
                stmt = insert(IPAddress).values(
                    address=request.ip_address,
                    prefix_id=request.prefix_id,
                    status="已分配",
                    usage="管理IP"
                ).returning(IPAddress)
                result = await db.execute(stmt)
                ip_address = result.scalar_one()
        
        stmt = insert(Device).values(
            name=request.name,
            type=request.type,
            vendor=request.vendor,
            site_id=request.site_id,
            location=request.location,
            mgmt_ip_id=ip_address.id if ip_address else None,
            status="active",
            owner=request.owner
        ).returning(Device)
        result = await db.execute(stmt)
        new_device = result.scalar_one()
        
        stmt = insert(Credential).values(
            name=f"{request.name}-credential",
            device_id=new_device.id,
            username=request.username,
            password=encrypt_password(request.password),
            port=request.port,
            enable_password=encrypt_password(request.enable_password) if request.enable_password else "",
        )
        await db.execute(stmt)
        
        await db.commit()
        
        return {
            "success": True,
            "message": f"设备 {request.name} 添加成功",
            "device_id": new_device.id
        }
    
    except Exception as e:
        await db.rollback()
        return {
            "success": False,
            "message": f"添加失败: {str(e)}",
            "device_id": None
        }