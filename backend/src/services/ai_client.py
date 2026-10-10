"""
统一的 AI 调用客户端
从数据库 settings 表读取 AI 配置，支持 OpenAI / Anthropic / 通义千问 / DeepSeek / 自定义
"""
import asyncio
import json
import logging
from typing import Optional
from httpx import AsyncClient, Timeout, AsyncHTTPTransport
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..models.setting import Setting

logger = logging.getLogger(__name__)

AI_CONFIG_KEY = "ai_config"

# OpenAI 兼容接口的提供商列表
OPENAI_COMPATIBLE = {"openai", "deepseek", "qwen", "zhipu", "custom"}


class AIConfig:
    """AI 配置模型"""
    def __init__(self, provider: str, api_key: str, api_base: str, model: str):
        self.provider = provider
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model

    def is_configured(self) -> bool:
        return bool(self.api_key) and bool(self.api_base)


async def get_ai_config(db: AsyncSession) -> Optional[AIConfig]:
    """从 settings 表读取 AI 配置，未配置返回 None"""
    result = await db.execute(select(Setting).filter(Setting.key == AI_CONFIG_KEY))
    setting = result.scalars().first()
    if not setting:
        return None

    try:
        cfg = json.loads(setting.value)
        if isinstance(cfg, list):
            # 只在「已启用且真正配置好（有 api_key 与 api_url）」的配置里挑选。
            # 之前的默认项(openai)虽 is_default=true 但 key 为空，会把已配置好的项
            # （如 zhipu）挡在门外，导致整个 AI 走纯关键词兜底。
            # 这里让默认项失效时回退到第一个真正可用的配置。
            enabled = [c for c in cfg if c.get("enabled")]
            default_config = next(
                (
                    c for c in enabled
                    if c.get("is_default") and c.get("api_key") and c.get("api_url")
                ),
                None,
            )
            if not default_config:
                default_config = next(
                    (c for c in enabled if c.get("api_key") and c.get("api_url")),
                    None,
                )

            if default_config:
                provider = default_config.get("provider", "").lower()
                api_key = default_config.get("api_key", "")
                api_base = default_config.get("api_url", "")
                model = default_config.get("model", "")
                if api_key and api_base:
                    return AIConfig(provider=provider, api_key=api_key, api_base=api_base, model=model)
            return None
        
        provider = cfg.get("provider", "").lower()
        api_key = cfg.get("api_key", "")
        api_base = cfg.get("api_base", cfg.get("api_url", ""))
        model = cfg.get("model", "")
        if not api_key or not api_base:
            return None
        return AIConfig(provider=provider, api_key=api_key, api_base=api_base, model=model)
    except (json.JSONDecodeError, KeyError, IndexError):
        return None


async def get_ai_configs(db: AsyncSession) -> list:
    """获取所有 AI 配置列表"""
    result = await db.execute(select(Setting).filter(Setting.key == AI_CONFIG_KEY))
    setting = result.scalars().first()
    if not setting:
        return []

    try:
        cfg = json.loads(setting.value)
        if isinstance(cfg, list):
            return cfg
        return [{
            "id": 1,
            "name": cfg.get("description", ""),
            "provider": cfg.get("provider", ""),
            "model": cfg.get("model", ""),
            "api_url": cfg.get("api_base", cfg.get("api_url", "")),
            "description": "",
            "enabled": True,
            "is_default": True,
        }]
    except (json.JSONDecodeError, KeyError):
        return []


async def save_ai_configs(db: AsyncSession, configs: list):
    """保存 AI 配置列表"""
    result = await db.execute(select(Setting).filter(Setting.key == AI_CONFIG_KEY))
    setting = result.scalars().first()

    if setting:
        setting.value = json.dumps(configs)
    else:
        setting = Setting(key=AI_CONFIG_KEY, value=json.dumps(configs))
        db.add(setting)

    await db.commit()


async def call_ai(
    prompt: str,
    system: str,
    ai_config: AIConfig,
    max_tokens: int = 2000,
    timeout: int = 15,
) -> str:
    """
    统一 AI 调用入口
    自动适配不同提供商的 API 格式
    超时、重试（最多2次）、错误处理统一在此处理
    返回模型的文本响应
    """
    provider = ai_config.provider
    model = ai_config.model
    max_retries = 2
    last_error = None

    logger.info(f"[call_ai] provider={provider} model={model} max_tokens={max_tokens} timeout={timeout} max_retries={max_retries} starting")

    for attempt in range(max_retries + 1):
        try:
            if provider in OPENAI_COMPATIBLE:
                result = await _call_openai_compatible(prompt, system, ai_config, max_tokens, timeout)
            elif provider == "anthropic":
                result = await _call_anthropic(prompt, system, ai_config, max_tokens, timeout)
            else:
                raise ValueError(f"不支持的 AI 提供商: {provider}")

            result_len = len(result)
            logger.info(f"[call_ai] provider={provider} model={model} attempt={attempt+1} completed, response length={result_len}")
            return result
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                logger.warning(f"[call_ai] provider={provider} model={model} attempt={attempt+1} failed: {e}, retrying in 1s...")
                await asyncio.sleep(1)
            else:
                logger.error(f"[call_ai] provider={provider} model={model} all {max_retries+1} attempts failed: {e}")

    # 所有重试都失败
    raise last_error


async def _call_openai_compatible(
    prompt: str,
    system: str,
    config: AIConfig,
    max_tokens: int,
    timeout: int,
) -> str:
    """调用 OpenAI 兼容接口（OpenAI / DeepSeek / 通义千问 / 智谱 / 自定义）"""
    url = f"{config.api_base}/chat/completions"
    logger.debug(f"[_call_openai_compatible] url={url} model={config.model} max_tokens={max_tokens}")

    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }

    async with AsyncClient(timeout=Timeout(timeout), transport=AsyncHTTPTransport(proxy=None)) as client:
        resp = await client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        logger.debug(f"[_call_openai_compatible] url={url} completed, {len(content)} chars")
        return content


async def _call_anthropic(
    prompt: str,
    system: str,
    config: AIConfig,
    max_tokens: int,
    timeout: int,
) -> str:
    """调用 Anthropic Claude API"""
    url = f"{config.api_base}/v1/messages"
    logger.debug(f"[_call_anthropic] url={url} model={config.model} max_tokens={max_tokens}")

    headers = {
        "x-api-key": config.api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    body = {
        "model": config.model,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }

    async with AsyncClient(timeout=Timeout(timeout), transport=AsyncHTTPTransport(proxy=None)) as client:
        resp = await client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()
        content = data["content"][0]["text"].strip()
        logger.debug(f"[_call_anthropic] url={url} completed, {len(content)} chars")
        return content