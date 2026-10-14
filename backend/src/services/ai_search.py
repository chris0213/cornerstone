"""
AI 自然语言查询核心服务
将用户的自然语言问题转换为结构化查询，执行数据库查询，并用 AI 格式化回答
"""
import json
import ipaddress
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Site, Circuit, Device, IPAddress, Prefix, Backup, InspectionDeviceResult, InspectionResult, Vlan, DeviceLink, AuditLog
from .ai_client import call_ai, get_ai_config

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 系统 Prompt：告诉 AI 如何解析用户问题
# ──────────────────────────────────────────────
SYSTEM_PROMPT = """
你是基石（Cornerstone）企业级IT基础设施智能运维平台的智能助手。
你的任务是理解用户的自然语言问题，将其转换为结构化的查询意图。

可查询的数据类型：
- sites：站点/办公室信息（名称、城市、联系人）
- circuits：专线信息（运营商、带宽、状态、合同到期日）
- devices：网络设备（名称、类型、位置、管理IP、保修日期）
- ip_addresses：IP地址（地址、状态、绑定设备、用途）
- prefixes：IP子网（网段、使用率、站点）
- backups：配置备份记录（设备、时间、状态、是否有变更）
- inspection_results：巡检记录（设备在线状态、离线记录）
- topology：设备拓扑连线（源设备/接口 → 目标设备/接口）
- vlans：VLAN 配置（VLAN ID、名称、状态）
- audit_logs：审计日志（操作人、动作、资源、时间）

你必须返回严格的 JSON 格式，不要返回任何其他内容：
{
    "intent": "query",
    "entities": {
        "type": "数据类型",
        "filters": {
            "字段名": "过滤值"
        },
        "time_range": {
            "field": "时间字段名",
            "start": "ISO时间或相对时间如last_7_days",
            "end": "ISO时间或now"
        },
        "sort": {
            "field": "排序字段",
            "order": "asc或desc"
        },
        "limit": 20
    },
    "answer_format": "list或summary或single",
    "original_question": "用户原始问题"
}
"""


async def parse_user_query(question: str, last_data_type: str = "") -> dict:
    """
    调用大模型解析用户问题为结构化查询意图
    失败时返回降级查询（full text search fallback）
    """
    prompt = f"请解析以下查询：{question}"

    ai_config = None  # 先尝试从全局获取，如果没有配置则返回降级
    from ..database import async_session
    from ..models.setting import Setting
    from sqlalchemy import select

    try:
        async with async_session() as db:
            ai_config = await get_ai_config(db)
    except Exception:
        pass

    if ai_config and ai_config.is_configured():
        try:
            raw = await call_ai(prompt, SYSTEM_PROMPT, ai_config, max_tokens=1000, timeout=6)
            # 提取 JSON
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            intent = json.loads(raw)
            return intent
        except Exception as e:
            logger.warning(f"AI parse failed, fallback to keyword search: {e}")

    # 降级：关键字匹配
    return _fallback_parse(question, last_data_type)


# execute_query 支持的全部数据类型，用于追问时沿用上一轮的上下文
VALID_DATA_TYPES = {
    "sites", "circuits", "devices", "ip_addresses", "prefixes",
    "backups", "inspection_results", "topology", "vlans", "audit_logs",
}


def _fallback_parse(question: str, last_data_type: str = "") -> dict:
    """降级解析：通过关键字匹配确定查询类型"""
    q = question.lower()
    data_type: Optional[str] = None

    # 优先级处理：长句优先（避免"电路备份"误匹配到 circuits）；
    # 「子网/使用率」要排在「ip」前面，否则"子网的IP使用率"会误判成查 IP 地址
    if any(k in q for k in ["防疫", "灾备"]):
        data_type = "backups"
    elif any(k in q for k in ["拓扑", "连线"]):
        data_type = "topology"
    elif any(k in q for k in ["vlan", "vlan配置", "子接口"]):
        data_type = "vlans"
    elif any(k in q for k in ["日志", "审计", "操作记录"]):
        data_type = "audit_logs"
    elif any(k in q for k in ["使用率", "利用率", "子网", "网段", "prefix", "可用的子网", "可用的网段"]):
        data_type = "prefixes"
    elif any(k in q for k in ["站点", "办公室", "机房", "site", "场所"]):
        data_type = "sites"
    elif any(k in q for k in ["专线", "电路", "circuit", "带宽", "链路"]):
        data_type = "circuits"
    elif any(k in q for k in ["设备", "交换机", "路由器", "防火墙", "device", "保修",
                              "机器", "硬件", "资产", "节点", "清单"]):
        data_type = "devices"
    elif any(k in q for k in ["ip", "地址", "ip地址", "分配"]):
        data_type = "ip_addresses"
    elif any(k in q for k in ["备份", "backup", "配置保存"]):
        data_type = "backups"
    elif any(k in q for k in ["巡检", "离线", "在线", "扫描"]):
        data_type = "inspection_results"

    # 这问兜底：没命中任何关键词、且上一轮有明确类型时，沿用上一轮的数据类型。
    # 例：先问"统计各子网的IP使用率"，再问"都是什么"，应继续查子网而不是默认设备。
    if data_type is None:
        if last_data_type in VALID_DATA_TYPES:
            data_type = last_data_type
        else:
            data_type = "devices"

    answer_format = "summary" if any(k in q for k in ["多少", "几个", "统计", "总数", "总共", "数一数", "计数"]) else "list"

    return {
        "intent": "query",
        "entities": {
            "type": data_type,
            "filters": {},
            "time_range": {},
            "sort": {},
            "limit": 20,
        },
        "answer_format": answer_format,
        "original_question": question,
    }


# ──────────────────────────────────────────────
# 执行查询
# ──────────────────────────────────────────────
async def execute_query(intent: dict, db: AsyncSession) -> list:
    """根据解析出的查询意图执行数据库查询"""
    entities = intent.get("entities", {})
    data_type = entities.get("type", "devices")
    filters = entities.get("filters", {})
    time_range = entities.get("time_range", {})
    sort = entities.get("sort", {})
    limit = entities.get("limit", 20)

    if data_type == "sites":
        return await _query_sites(db, filters)
    elif data_type == "circuits":
        return await _query_circuits(db, filters, time_range, sort, limit)
    elif data_type == "devices":
        return await _query_devices(db, filters, time_range, sort, limit)
    elif data_type == "ip_addresses":
        return await _query_ip_addresses(db, filters, limit)
    elif data_type == "prefixes":
        return await _query_prefixes(db, filters, limit)
    elif data_type == "backups":
        return await _query_backups(db, filters, time_range, sort, limit)
    elif data_type == "inspection_results":
        return await _query_inspection(db, filters, time_range, limit)
    elif data_type == "topology":
        return await _query_topology(db, filters, limit)
    elif data_type == "vlans":
        return await _query_vlans(db, filters, limit)
    elif data_type == "audit_logs":
        return await _query_audit_logs(db, filters, limit)
    return []


async def _query_sites(db: AsyncSession, filters: dict) -> list:
    stmt = select(Site)
    if "name" in filters:
        stmt = stmt.where(Site.name.contains(filters["name"]))
    if "status" in filters:
        stmt = stmt.where(Site.status == filters["status"])
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        {"id": s.id, "name": s.name, "city": s.city, "location": s.location,
         "contact": s.contact, "status": s.status, "alert_count": s.alert_count}
        for s in rows
    ]


async def _query_circuits(db: AsyncSession, filters: dict, time_range: dict, sort: dict, limit: int) -> list:
    stmt = select(Circuit)
    if "status" in filters:
        stmt = stmt.where(Circuit.status == filters["status"])

    # 处理时间范围（如合同即将到期）
    if time_range.get("field") == "contract_end":
        if time_range.get("end") == "now" or "soon" in str(time_range.get("start", "")):
            soon = datetime.now(timezone.utc) + timedelta(days=30)
            stmt = stmt.where(Circuit.contract_end <= soon)
            stmt = stmt.where(Circuit.contract_end >= datetime.now(timezone.utc))
        elif "expired" in str(time_range.get("start", "")):
            stmt = stmt.where(Circuit.contract_end < datetime.now(timezone.utc))

    if sort and sort.get("field"):
        col = getattr(Circuit, sort["field"], None)
        if col:
            stmt = stmt.order_by(col.desc() if sort.get("order") == "desc" else col.asc())

    stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        {"id": c.id, "name": c.name, "provider": c.provider, "type": c.type,
         "bandwidth": c.bandwidth, "status": c.status,
         "contract_end": c.contract_end.isoformat() if c.contract_end else None,
         "monthly_cost": c.monthly_cost}
        for c in rows
    ]


async def _query_devices(db: AsyncSession, filters: dict, time_range: dict, sort: dict, limit: int) -> list:
    stmt = select(Device)
    if "name" in filters:
        stmt = stmt.where(Device.name.contains(filters["name"]))
    if "type" in filters:
        stmt = stmt.where(Device.type.contains(filters["type"]))
    if "status" in filters:
        stmt = stmt.where(Device.status == filters["status"])

    # 保修到期查询
    if time_range.get("field") == "warranty_end":
        if "soon" in str(time_range):
            soon = datetime.now(timezone.utc) + timedelta(days=30)
            stmt = stmt.where(Device.warranty_end <= soon)
        elif "expired" in str(time_range):
            stmt = stmt.where(Device.warranty_end < datetime.now(timezone.utc))

    if sort and sort.get("field"):
        col = getattr(Device, sort["field"], None)
        if col:
            stmt = stmt.order_by(col.desc() if sort.get("order") == "desc" else col.asc())

    stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        {"id": d.id, "name": d.name, "type": d.type, "brand": d.brand,
         "model": d.model, "sn": d.sn, "location": d.location,
         "status": d.status, "owner": d.owner,
         "warranty_end": d.warranty_end.isoformat() if d.warranty_end else None,
         "purchase_date": d.purchase_date.isoformat() if d.purchase_date else None}
        for d in rows
    ]


async def _query_ip_addresses(db: AsyncSession, filters: dict, limit: int) -> list:
    stmt = select(IPAddress)
    if "address" in filters:
        stmt = stmt.where(IPAddress.address.contains(filters["address"]))
    if "status" in filters:
        stmt = stmt.where(IPAddress.status == filters["status"])
    stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        {"id": ip.id, "address": ip.address, "status": ip.status,
         "usage": ip.usage, "owner": ip.owner, "device_id": ip.device_id}
        for ip in rows
    ]


async def _query_prefixes(db: AsyncSession, filters: dict, limit: int) -> list:
    stmt = select(Prefix)
    if "network" in filters:
        stmt = stmt.where(Prefix.network.contains(filters["network"]))
    stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    # 汇总每个子网的 IP 使用情况
    output = []
    for p in rows:
        total_ips = 0
        try:
            net = ipaddress.ip_network(p.network, strict=False)
            total_ips = net.num_addresses - 2  # 减去网络地址和广播地址
        except Exception:
            pass
        used_count = await db.execute(
            select(func.count(IPAddress.id)).where(IPAddress.prefix_id == p.id)
        )
        used = used_count.scalar() or 0
        output.append({
            "id": p.id, "network": p.network, "vlan": p.vlan,
            "usage": p.usage, "site_id": p.site_id,
            "total_ips": total_ips, "used_ips": used,
            "usage_rate": round(used / total_ips * 100, 1) if total_ips > 0 else 0,
        })
    return output


async def _query_backups(db: AsyncSession, filters: dict, time_range: dict, sort: dict, limit: int) -> list:
    stmt = select(Backup)
    if time_range:
        if "last_7_days" in str(time_range):
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)
            stmt = stmt.where(Backup.created_at >= cutoff)
        elif time_range.get("start"):
            stmt = stmt.where(Backup.created_at >= time_range["start"])
    if sort and sort.get("field"):
        col = getattr(Backup, sort["field"], None)
        if col:
            stmt = stmt.order_by(col.desc() if sort.get("order") == "desc" else col.asc())
    stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        {"id": b.id, "device_id": b.device_id, "version": b.version,
         "status": b.status, "has_change": b.has_change, "note": b.note}
        for b in rows
    ]


async def _query_inspection(db: AsyncSession, filters: dict, time_range: dict, limit: int) -> list:
    stmt = select(InspectionDeviceResult)

    # 离线查询
    if "offline" in str(filters) or "offline" in str(time_range):
        stmt = stmt.where(InspectionDeviceResult.is_online == False)

    if time_range:
        if "last_7_days" in str(time_range):
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)
            stmt = stmt.where(InspectionDeviceResult.scanned_at >= cutoff)

    stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        {"id": r.id, "ip_address": r.ip_address, "device_id": r.device_id,
         "is_online": r.is_online, "sys_name": r.sys_name,
         "has_fingerprint_change": r.has_fingerprint_change}
        for r in rows
    ]


async def _query_topology(db: AsyncSession, filters: dict, limit: int) -> list:
    stmt = select(DeviceLink).limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        {"id": r.id, "source_device_id": r.source_device_id,
         "source_interface": r.source_interface,
         "target_device_id": r.target_device_id,
         "target_interface": r.target_interface,
         "link_type": r.link_type, "confidence": r.confidence}
        for r in rows
    ]


async def _query_vlans(db: AsyncSession, filters: dict, limit: int) -> list:
    stmt = select(Vlan).limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        {"id": r.id, "vid": r.vid, "name": r.name,
         "status": r.status, "description": r.description}
        for r in rows
    ]


async def _query_audit_logs(db: AsyncSession, filters: dict, limit: int) -> list:
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        {"id": r.id, "user": r.user, "action": r.action,
         "resource": r.resource, "detail": r.detail,
         "success": r.success, "ip_address": r.ip_address,
         "created_at": r.created_at.isoformat() if r.created_at else None}
        for r in rows
    ]


# ──────────────────────────────────────────────
# 格式化回答
# ──────────────────────────────────────────────
async def format_answer(intent: dict, raw_data: list, question: str) -> dict:
    """
    将查询结果格式化为自然语言回答
    返回 answer_text + 原始数据 + data_type + suggestions
    """
    data_type = intent.get("entities", {}).get("type", "devices")

    # 尝试用 AI 生成自然语言回答
    ai_config = None
    try:
        from ..database import async_session
        async with async_session() as db:
            ai_config = await get_ai_config(db)
    except Exception:
        pass

    if ai_config and ai_config.is_configured() and raw_data:
        format_prompt = (
            f"用户问题：{question}\n"
            f"查询数据类型：{data_type}\n"
            f"查询结果（JSON）：{json.dumps(raw_data, ensure_ascii=False)}\n\n"
            f"请用简洁的中文回答用户的问题，基于以上数据。"
            f"同时给出 2-3 个进一步追问的建议（JSON数组）。"
            f"返回严格 JSON：{{\"answer_text\": \"...\", \"suggestions\": [...]}}"
        )
        format_system = "你是一位IT运维助手。根据数据和用户问题，生成简洁的自然语言回答和建议追问。只返回JSON。"
        try:
            raw = await call_ai(format_prompt, format_system, ai_config, max_tokens=1000, timeout=6)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            result = json.loads(raw)
            return {
                "answer_text": result.get("answer_text", _generate_fallback_answer(data_type, raw_data, question)),
                "data": raw_data,
                "data_type": data_type,
                "suggestions": result.get("suggestions", []),
            }
        except Exception:
            pass

    # 降级生成
    return {
        "answer_text": _generate_fallback_answer(data_type, raw_data, question),
        "data": raw_data,
        "data_type": data_type,
        "suggestions": [],
    }


def _row_summary(data_type: str, r: dict) -> str:
    """把一条查询结果压成一行人话，供无模型时的兜底回答使用"""
    if data_type == "sites":
        s = r.get("name") or "-"
        if r.get("city"):
            s += f"（{r['city']}"
            if r.get("status"):
                s += f"，{r['status']}"
            s += "）"
        elif r.get("status"):
            s += f"（{r['status']}）"
        return s
    if data_type == "circuits":
        s = r.get("name") or "-"
        if r.get("provider"):
            s += f" · {r['provider']}"
        if r.get("bandwidth"):
            s += f" · {r['bandwidth']}"
        if r.get("status"):
            s += f" · {r['status']}"
        if r.get("contract_end"):
            s += f" · 合同至 {str(r['contract_end'])[:10]}"
        return s
    if data_type == "devices":
        s = r.get("name") or "-"
        extra = " ".join(str(x) for x in [r.get("type"), r.get("brand")] if x)
        if extra:
            s += f"（{extra}）"
        if r.get("status"):
            s += f" · {r['status']}"
        if r.get("location"):
            s += f" · {r['location']}"
        return s
    if data_type == "ip_addresses":
        s = r.get("address") or "-"
        if r.get("status"):
            s += f" · {r['status']}"
        if r.get("usage"):
            s += f" · {r['usage']}"
        return s
    if data_type == "prefixes":
        return (
            f"{r.get('network') or '-'}：已用 {r.get('used_ips', 0)}/{r.get('total_ips', 0)}"
            f"（{r.get('usage_rate', 0)}%）"
        )
    if data_type == "backups":
        s = f"设备#{r.get('device_id')} {r.get('version') or ''}".strip()
        if r.get("status"):
            s += f" · {r['status']}"
        if r.get("has_change"):
            s += " · 有变更"
        return s
    if data_type == "inspection_results":
        s = r.get("ip_address") or "-"
        s += " · 在线" if r.get("is_online") else " · 离线"
        if r.get("sys_name"):
            s += f" · {r['sys_name']}"
        if r.get("has_fingerprint_change"):
            s += " · 指纹变化"
        return s
    if data_type == "topology":
        return (
            f"设备#{r.get('source_device_id')}({r.get('source_interface') or '?'})"
            f" → 设备#{r.get('target_device_id')}({r.get('target_interface') or '?'})"
        )
    if data_type == "vlans":
        return f"VLAN {r.get('vid')} {r.get('name') or ''} · {r.get('status') or ''}".strip()
    if data_type == "audit_logs":
        return (
            f"{r.get('user') or '-'} {r.get('action') or ''} {r.get('resource') or ''}"
            f" · {str(r.get('created_at') or '')[:19]}"
        ).strip()
    return json.dumps(r, ensure_ascii=False)[:120]


def _generate_fallback_answer(data_type: str, raw_data: list, question: str) -> str:
    """降级回答生成：直接把查询结果摘出来，而不是只报一个数字"""
    count = len(raw_data)
    name_map = {
        "sites": "站点", "circuits": "专线", "devices": "设备",
        "ip_addresses": "IP地址", "prefixes": "子网", "backups": "备份记录",
        "inspection_results": "巡检结果",
        "topology": "拓扑连接", "vlans": "VLAN", "audit_logs": "审计日志",
    }
    label = name_map.get(data_type, data_type)

    if count == 0:
        return f"没有找到相关的{label}信息。"

    show = raw_data[:5]
    lines = [f"- {_row_summary(data_type, r)}" for r in show]
    tail = f"\n…（还有 {count - 5} 条，可以让我缩小范围）" if count > 5 else ""
    return f"共找到 {count} 条{label}：\n" + "\n".join(lines) + tail


# ──────────────────────────────────────────────
# 知识库检索（RAG）：操作类问题优先命中内部沉淀的处置经验
# ──────────────────────────────────────────────

_KB_STOPWORDS = {
    "如何", "怎么", "怎样", "怎么办", "什么", "哪些", "请问", "帮我", "告诉", "一下",
    "可以", "是否", "有没有", "是不是", "的", "了", "吗", "呢", "啊", "？", "?",
}

_HOWTO_HINTS = (
    "如何", "怎么", "怎样", "怎么办", "排查", "处理", "恢复", "解决", "步骤",
    "配置", "教程", "指南", "sop", "报错", "错误", "失败", "无法", "不能",
    "不通", "不了", "指南", "手册", "如何做", "怎么办",
)


def _kb_normalize(text: str) -> str:
    """归一化：去标点/空白并转小写，便于 n-gram 匹配"""
    import re
    return re.sub(r"[\s，。！？、,.!?\"'（）()【】\[\]：:；;#*|>_~`]+", "", text or "").lower()


def _looks_like_howto(question: str) -> bool:
    """问题是否偏操作/经验类（而非实时数据查询）"""
    q = question.lower()
    return any(h in q for h in _HOWTO_HINTS)


def _question_ngrams(question: str) -> set[str]:
    """问题去掉疑问词后切 2/3-gram（中文无空格，LIKE 整句无法命中，需 n-gram 打分）"""
    core = question
    for hint in sorted(_HOWTO_HINTS, key=len, reverse=True):
        core = core.replace(hint, " ")
    for sw in sorted(_KB_STOPWORDS, key=len, reverse=True):
        core = core.replace(sw, " ")
    core = _kb_normalize(core)
    grams = {core[i:i + 2] for i in range(max(0, len(core) - 1))}
    grams |= {core[i:i + 3] for i in range(max(0, len(core) - 2))}
    return grams


async def search_knowledge_articles(db: AsyncSession, question: str, limit: int = 3) -> list[dict]:
    """检索已发布知识库文章：拉取候选后用问题 n-gram 与正文重叠度打分排序

    团队知识库规模有限，候选上限 200 篇在 Python 侧打分，
    比 SQL LIKE 拼接（中文问题切不出有效片段）更可靠。
    """
    from ..models import KnowledgeArticle

    grams = _question_ngrams(question)
    if not grams:
        return []

    rows = (await db.execute(
        select(KnowledgeArticle)
        .where(KnowledgeArticle.is_published.is_(True))
        .order_by(KnowledgeArticle.updated_at.desc())
        .limit(200)
    )).scalars().all()

    scored = []
    for a in rows:
        text = _kb_normalize(
            f"{a.title}\n{a.summary or ''}\n{a.tags or ''}\n{(a.content or '')[:5000]}"
        )
        matched = [g for g in grams if g in text]
        # 需至少命中 2 个片段且累计长度足够，避免"如何/处理"这类泛词误召回
        score = sum(len(g) for g in matched)
        if len(matched) >= 2 and score >= 5:
            scored.append((score, a))

    scored.sort(key=lambda x: (-x[0], x[1].updated_at))
    return [
        {"id": a.id, "title": a.title, "category": a.category or "其他",
         "summary": a.summary or "", "content": a.content or ""}
        for _, a in scored[:limit]
    ]


KB_SYSTEM_PROMPT = """你是基石（Cornerstone）企业级IT基础设施智能运维平台的智能助手。
用户询问的是运维操作/故障处置类问题，下面提供了内部知识库中相关的文章内容。
要求：
1. 优先依据知识库内容回答，操作步骤必须忠于原文，不得臆造步骤或命令
2. 回答末尾注明来源文章标题（格式：来源：《标题》）
3. 知识库内容与问题无关时如实说明"知识库中暂无相关沉淀"，并给出通用建议
4. 用简洁中文回答，步骤用编号列表"""


async def answer_from_knowledge(db: AsyncSession, question: str) -> Optional[dict]:
    """知识库 RAG：命中文章时返回 {answer_text, data_type="knowledge"}，否则 None 走原查询链路"""
    articles = await search_knowledge_articles(db, question)
    if not articles:
        return None

    ai_config = await get_ai_config(db)
    if ai_config and ai_config.is_configured():
        kb_text = "\n\n".join(
            f"《{a['title']}》（{a['category']}）\n{(a['content'] or a['summary'])[:1500]}"
            for a in articles
        )
        prompt = f"用户问题：{question}\n\n内部知识库相关文章：\n{kb_text}"
        try:
            answer = await call_ai(prompt, KB_SYSTEM_PROMPT, ai_config, max_tokens=1200, timeout=12)
            return {"answer_text": answer.strip(), "data_type": "knowledge"}
        except Exception as e:
            logger.warning(f"Knowledge RAG AI call failed, fallback to list: {e}")

    # 未配置 AI 或调用失败：直接给出检索结果列表
    lines = [f"在知识库中找到 {len(articles)} 篇相关文章："]
    for i, a in enumerate(articles, 1):
        summary = (a["summary"] or a["content"])[:120]
        lines.append(f"{i}. 《{a['title']}》（{a['category']}）— {summary}")
    lines.append("打开知识库页面可查看全文。")
    return {"answer_text": "\n".join(lines), "data_type": "knowledge"}