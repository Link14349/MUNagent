"""配置读写与连接测试."""

from __future__ import annotations

import httpx

from munagent.config import load_config, mask_api_key, save_config
from munagent.config.models import AppConfig
from munagent.llm import ChatMessage, LLMClient
from munagent.security import sanitize_text
from munagent.server.schemas import (
    ConfigPublic,
    ConfigTestRequest,
    ConfigTestResponse,
    ConfigUpdate,
    to_public,
)


def _is_masked_or_empty(value: str) -> bool:
    return not value or "****" in value or value == "(未设置)"


def merge_config_update(current: AppConfig, update: ConfigUpdate) -> AppConfig:
    data = current.model_dump()
    if update.providers:
        providers = dict(data.get("providers") or {})
        for name, patch in update.providers.items():
            existing = dict(providers.get(name) or {})
            if "base_url" in patch:
                existing["base_url"] = patch["base_url"]
            if "api_key" in patch and not _is_masked_or_empty(patch["api_key"]):
                existing["api_key"] = patch["api_key"]
            providers[name] = existing
        data["providers"] = providers
    if update.roles:
        data["roles"] = {k: v.model_dump() for k, v in update.roles.items()}
    if update.tools:
        tools = dict(data.get("tools") or {})
        tools = _deep_merge(tools, update.tools)
        if "search" in tools and "api_key" in tools["search"]:
            key = tools["search"]["api_key"]
            if _is_masked_or_empty(key):
                tools["search"]["api_key"] = current.tools.search.api_key
        data["tools"] = tools
    if update.engine:
        data["engine"] = update.engine.model_dump()
    if update.server:
        data["server"] = update.server.model_dump()
    return AppConfig.model_validate(data)


def _deep_merge(base: dict, overlay: dict) -> dict:
    out = dict(base)
    for k, v in overlay.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def get_config_public() -> ConfigPublic:
    return to_public(load_config())


def put_config(update: ConfigUpdate) -> ConfigPublic:
    current = load_config()
    merged = merge_config_update(current, update)
    save_config(merged)
    return to_public(merged)


async def test_config(req: ConfigTestRequest) -> ConfigTestResponse:
    config = load_config()
    target = req.target.strip()

    if target.startswith("provider:"):
        name = target.split(":", 1)[1]
        role = _role_for_provider(config, name)
        if role is None:
            return ConfigTestResponse(ok=False, message=f"未找到使用 provider {name} 的角色")
        try:
            client = LLMClient(config)
            await client.chat(
                role,
                [ChatMessage(role="user", content="回复 ok")],
                max_tokens=16,
                thinking_enabled=False,
            )
            _, base_url, model = client.resolve_route(role)
            key = config.providers[name].api_key
            return ConfigTestResponse(
                ok=True,
                message=f"provider={name} model={model} url={base_url} key={mask_api_key(key)}",
            )
        except Exception as exc:
            return ConfigTestResponse(ok=False, message=sanitize_text(str(exc)))

    if target == "tool:mineru":
        url = config.tools.mineru.base_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{url}/health")
                resp.raise_for_status()
            return ConfigTestResponse(ok=True, message=f"MinerU 在线: {url}")
        except Exception as exc:
            return ConfigTestResponse(ok=False, message=sanitize_text(str(exc)))

    if target == "tool:search":
        key = config.tools.search.api_key
        if not key:
            return ConfigTestResponse(ok=False, message="未配置 tools.search.api_key")
        if config.tools.search.provider != "tavily":
            return ConfigTestResponse(
                ok=False, message=f"P1 仅实现 Tavily 测试, 当前为 {config.tools.search.provider}"
            )
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    "https://api.tavily.com/search",
                    json={"api_key": key, "query": "test", "max_results": 1},
                )
                resp.raise_for_status()
            return ConfigTestResponse(ok=True, message="Tavily 搜索可用")
        except Exception as exc:
            return ConfigTestResponse(ok=False, message=sanitize_text(str(exc)))

    return ConfigTestResponse(ok=False, message=f"未知测试目标: {target}")


def _role_for_provider(config: AppConfig, provider_name: str) -> str | None:
    for role, rc in config.roles.items():
        if rc.provider == provider_name:
            return role
    return None
