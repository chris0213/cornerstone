"""设备类型枚举定义与归一化。

规范值与前端 constants/deviceIcons.ts 的图标配置 key 对齐。
"""

from typing import Literal

DeviceType = Literal[
    "switch",
    "router",
    "firewall",
    "server",
    "ap",
    "wireless-controller",
    "load-balancer",
    "ids-ips",
    "waf",
    "vpn",
    "storage",
    "other",
]

DEVICE_TYPES: set[str] = {
    "switch",
    "router",
    "firewall",
    "server",
    "ap",
    "wireless-controller",
    "load-balancer",
    "ids-ips",
    "waf",
    "vpn",
    "storage",
    "other",
}

# 历史存量值（中文文案）与英文别名 → 规范枚举
_DEVICE_TYPE_ALIASES: dict[str, str] = {
    # 规范值自身
    **{v: v for v in DEVICE_TYPES},
    # 中文存量值（迁移前数据与导入文件可能使用）
    "交换机": "switch",
    "接入交换机": "switch",
    "核心交换机": "switch",
    "路由器": "router",
    "防火墙": "firewall",
    "服务器": "server",
    "AP": "ap",
    "无线AP": "ap",
    "无线控制器": "wireless-controller",
    "AC": "wireless-controller",
    "负载均衡": "load-balancer",
    "负载均衡器": "load-balancer",
    "入侵检测": "ids-ips",
    "IDS": "ids-ips",
    "IPS": "ids-ips",
    "IDS / IPS": "ids-ips",
    "Web应用防火墙": "waf",
    "WAF": "waf",
    "VPN网关": "vpn",
    "VPN": "vpn",
    "存储": "storage",
    "NAS": "storage",
    "NAS / 存储": "storage",
    "其他": "other",
    "未知": "other",
    "unknown": "other",
}


def normalize_device_type(value: str | None) -> str | None:
    """归一化设备类型。

    - None / 空字符串 → 返回 None（表示未设置）
    - 已知枚举值或历史中文别名 → 返回规范枚举值
    - 无法识别 → 抛 ValueError（pydantic 场景转为 422；导入场景按行捕获计入失败明细）
    """
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    normalized = _DEVICE_TYPE_ALIASES.get(trimmed)
    if normalized is None:
        raise ValueError(f"未知的设备类型: {value}，可选值: {', '.join(sorted(DEVICE_TYPES))}")
    return normalized
