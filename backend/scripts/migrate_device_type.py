#!/usr/bin/env python3
"""一次性脚本：将设备 type 存量中文值归一为规范英文枚举。

背景：device.type 为自由字符串，早期种子/导入写入中文（"交换机"等），
现行写入路径（schemas/device.py 经 normalize_device_type）已统一英文枚举。
本脚本把存量中文刷成规范枚举，展示层由前端/ai_search 映射表翻译。

幂等：已入枚举的行不受影响；无法识别的值保持原样并打印，便于人工处理。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, update

from src.database import async_session
from src.models.device import Device
from src.constants.device_type import _DEVICE_TYPE_ALIASES, DEVICE_TYPES


async def migrate_device_type():
    async with async_session() as session:
        rows = await session.execute(select(Device.id, Device.type).where(Device.type.isnot(None)))
        unknown: list[tuple[int, str]] = []
        updated = 0
        for device_id, raw in rows.all():
            trimmed = (raw or "").strip()
            if not trimmed or trimmed in DEVICE_TYPES:
                continue
            normalized = _DEVICE_TYPE_ALIASES.get(trimmed)
            if normalized is None:
                unknown.append((device_id, trimmed))
                continue
            await session.execute(
                update(Device).where(Device.id == device_id).values(type=normalized)
            )
            updated += 1
        await session.commit()

        print(f"归一完成：更新 {updated} 台设备")
        if unknown:
            print(f"有 {len(unknown)} 台设备 type 无法识别，保持原样，请人工核对：")
            for device_id, raw in unknown:
                print(f"  - device#{device_id}: {raw!r}")


if __name__ == "__main__":
    asyncio.run(migrate_device_type())
