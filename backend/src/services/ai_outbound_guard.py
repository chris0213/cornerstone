"""
AI 外发防护：字段白名单、值级脱敏、禁止外发开关、api_url 校验、敏感行剔除。

所有发往外部 LLM 的内容都必须经过本模块处理：
- filter_rows_for_llm：按数据类型做字段白名单过滤 + 值级脱敏
- mask_outbound_text：通用文本脱敏（知识库正文、告警 message 等）
- strip_sensitive_lines：配置 diff 剔除含密码/community/私钥的行
- validate_ai_api_url：保存/测试时校验 api_url（https、拒绝内网、可选域名白名单）
- is_external_blocked：读取「禁止外发」总开关
"""
import ipaddress
import logging
import os
import re
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.setting import Setting
from ..utils.crypto import decrypt_secret  # noqa: F401  (re-export 供调用方统一 import)

logger = logging.getLogger(__name__)

AI_PRIVACY_KEY = "ai_privacy_settings"

# ── 值级脱敏正则（与聊天日志脱敏同源，集中管理） ──────────────

_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_MAC_RE = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 设备序列号/资产编码类：纯字母数字、长度>=10 且同时含字母与数字
_SN_RE = re.compile(r"\b(?=[A-Za-z0-9]{10,}\b)(?=[A-Za-z0-9]*[A-Za-z])(?=[A-Za-z0-9]*\d)[A-Za-z0-9]+\b")
# 问题文本中的凭证类：password=xxx / token: xxx / Bearer xxx / 私钥块
# 中文标签（密码=/口令=/令牌=/密钥=）同样按凭证脱敏
_CRED_KV_RE = re.compile(
    r"(?i)(?:\b(?:password|passwd|pwd|token|secret|api[_-]?key|apikey)\b"
    r"|密码|口令|令牌|秘钥|密钥)\s*[:=]\s*\S+"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]+")
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)

# 允许明文保留 IP 的字段（查询主体，脱敏后回答无意义）
_PLAIN_IP_FIELDS = {"address", "ip_address", "target_ip", "ip"}

# ── 字段白名单（发给 LLM 的数据，按 data_type） ──────────────

FIELD_WHITELIST: dict[str, set[str]] = {
    "devices": {
        "id", "name", "type", "brand", "model", "location",
        "status", "warranty_end", "purchase_date",
    },
    "circuits": {
        "id", "name", "provider", "type", "bandwidth",
        "status", "contract_end",
    },
    "sites": {"id", "name", "city", "location", "status", "alert_count"},
    "ip_addresses": {"id", "address", "status", "usage", "device_id"},
    "prefixes": None,   # None = 不限字段（仍做值级脱敏）
    "topology": None,
    "vlans": None,
    "backups": None,
    "inspection_results": None,
}


def mask_outbound_text(text: str) -> str:
    """外发文本通用脱敏：邮箱/MAC/IP/序列号。"""
    if not text:
        return text
    text = _EMAIL_RE.sub("[邮箱已脱敏]", text)
    text = _MAC_RE.sub("[MAC已脱敏]", text)
    text = _IPV4_RE.sub("[IP已脱敏]", text)
    text = _SN_RE.sub("[编码已脱敏]", text)
    return text


def mask_question(text: str) -> str:
    """用户提问落库前脱敏：在通用规则上追加凭证类规则。"""
    if not text:
        return text
    text = _PRIVATE_KEY_RE.sub("[私钥已脱敏]", text)
    text = _CRED_KV_RE.sub("[凭证已脱敏]", text)
    text = _BEARER_RE.sub("[凭证已脱敏]", text)
    return mask_outbound_text(text)


def _mask_value(field: str, value) :
    """按字段决定是否保留明文 IP，其余走通用脱敏。"""
    if not isinstance(value, str):
        return value
    if field in _PLAIN_IP_FIELDS:
        # 查询主体 IP 保留明文，但仍清掉同串中的邮箱/MAC/SN
        v = _EMAIL_RE.sub("[邮箱已脱敏]", value)
        v = _MAC_RE.sub("[MAC已脱敏]", v)
        return _SN_RE.sub("[编码已脱敏]", v)
    return mask_outbound_text(value)


def filter_rows_for_llm(data_type: str, rows) -> list:
    """按数据类型做字段白名单过滤 + 值级脱敏，返回可安全发给 LLM 的行列表。"""
    if not isinstance(rows, list):
        return rows
    whitelist = FIELD_WHITELIST.get(data_type)
    out = []
    for row in rows:
        if not isinstance(row, dict):
            out.append(row)
            continue
        filtered = {}
        for k, v in row.items():
            if whitelist is not None and k not in whitelist:
                continue
            if isinstance(v, list):
                filtered[k] = [
                    _mask_value(k, i) if isinstance(i, str) else i for i in v
                ]
            else:
                filtered[k] = _mask_value(k, v)
        out.append(filtered)
    return out


# ── 备份 diff 敏感行剔除 ──────────────────────────

_SENSITIVE_LINE_RE = re.compile(
    r"(?i)(password|passwd|secret|token\b|community|credential|"
    r"api[_-]?key|private[\s_-]?key|BEGIN [A-Z ]*PRIVATE KEY)"
)


def strip_sensitive_lines(text: str, max_chars: int = 3000) -> str:
    """配置 diff 发 LLM 前剔除敏感内容：先整块剔除 PEM 私钥（含 base64 主体行），
    再逐行剔除含密码/community 等关键词的行，最后截断。"""
    if not text:
        return text
    text = _PRIVATE_KEY_RE.sub("[私钥已脱敏]", text)
    kept = [line for line in text.splitlines() if not _SENSITIVE_LINE_RE.search(line)]
    result = "\n".join(kept)
    if len(result) > max_chars:
        result = result[:max_chars] + "\n... (已截断)"
    return result


# ── 禁止外发总开关 ──────────────────────────

async def get_privacy_settings(db: AsyncSession) -> dict:
    """读取 AI 隐私设置，默认允许外发（block_external=false）。"""
    result = await db.execute(select(Setting).filter(Setting.key == AI_PRIVACY_KEY))
    setting = result.scalars().first()
    if not setting:
        return {"block_external": False}
    try:
        import json
        data = json.loads(setting.value)
        return {"block_external": bool(data.get("block_external", False))}
    except Exception:
        return {"block_external": False}


async def is_external_blocked(db: AsyncSession) -> bool:
    """禁止外发开关是否开启。开启后所有 LLM 调用链路应跳过并走本地降级。"""
    return (await get_privacy_settings(db)).get("block_external", False)


# ── api_url 校验 ──────────────────────────

_LOCAL_DOMAIN_SUFFIXES = (".local", ".internal", ".lan", ".corp", ".home", ".localdomain")


def validate_ai_api_url(url: str) -> str | None:
    """校验 AI api_url。合法返回 None，否则返回错误信息。

    规则：
    - 必须是合法 URL 且 scheme 为 https
    - 主机不得为回环/私网/link-local/保留地址或 localhost 类域名
    - 环境变量 AI_API_ALLOWED_HOSTS（逗号分隔）非空时强制域名白名单
    """
    if not url or not url.strip():
        return "api_url 不能为空"
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return "api_url 必须使用 https"
    if not parsed.hostname:
        return "api_url 缺少主机名"

    hostname = parsed.hostname.lower()
    if hostname == "localhost" or hostname.endswith(_LOCAL_DOMAIN_SUFFIXES):
        return f"api_url 不允许使用内网/本地域名: {hostname}"

    # 域名白名单（可配置，默认不强制）
    allowed = os.environ.get("AI_API_ALLOWED_HOSTS", "").strip()
    if allowed:
        allowed_hosts = {h.strip().lower() for h in allowed.split(",") if h.strip()}
        if hostname not in allowed_hosts:
            return f"api_url 域名不在白名单中: {hostname}"

    # 主机若是 IP 字面量，拒绝内网/回环/link-local/保留段
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return None  # 普通域名且通过白名单检查
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return f"api_url 不允许使用内网/保留 IP: {hostname}"
    return None
