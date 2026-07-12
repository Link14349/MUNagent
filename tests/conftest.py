"""pytest 公共 fixture."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from munagent.config.models import AppConfig, ProviderConfig, RoleConfig, default_config
from munagent.llm import LLMClient, UsageCollector


@pytest.fixture
def sample_config() -> AppConfig:
    cfg = default_config()
    cfg.providers["deepseek"] = ProviderConfig(
        base_url="https://api.deepseek.com",
        api_key="sk-testkey1234567890",
    )
    cfg.roles["delegate"] = RoleConfig(provider="deepseek", model="deepseek-v4-flash")
    return cfg


@pytest.fixture
def usage_collector() -> UsageCollector:
    return UsageCollector()


@pytest.fixture
def mock_llm_response() -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": "pong"}}],
        "usage": {
            "prompt_tokens": 5,
            "completion_tokens": 1,
            "prompt_cache_hit_tokens": 3,
            "prompt_cache_miss_tokens": 2,
        },
    }


@pytest.fixture
def llm_client(sample_config: AppConfig, usage_collector: UsageCollector) -> LLMClient:
    return LLMClient(sample_config, usage_sink=usage_collector.emit)


@pytest.fixture
async def mock_llm_transport(mock_llm_response: dict[str, Any]) -> AsyncIterator[httpx.MockTransport]:
    """拦截 chat/completions 的 httpx transport."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(200, json=mock_llm_response)
        return httpx.Response(404, text="not found")

    yield httpx.MockTransport(handler)
