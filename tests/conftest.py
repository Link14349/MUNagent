"""pytest 公共 fixture."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from munagent.config.models import MunagentConfig, ProviderConfig, RoleConfig
from munagent.llm.client import LLMClient
from munagent.llm.usage import UsageRecord


@pytest.fixture
def sample_config() -> MunagentConfig:
    return MunagentConfig(
        providers={
            "deepseek": ProviderConfig(
                base_url="https://api.deepseek.com",
                api_key="sk-test-key-abcdefghijklmnop",
            )
        },
        roles={
            "delegate": RoleConfig(provider="deepseek", model="deepseek-v4-flash"),
            "chair": RoleConfig(provider="deepseek", model="deepseek-v4-pro"),
        },
    )


@pytest.fixture
def mock_llm_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "prompt_cache_hit_tokens": 8,
                    "prompt_cache_miss_tokens": 2,
                },
            },
        )

    return httpx.MockTransport(handler)


@pytest.fixture
def llm_client_factory(
    sample_config: MunagentConfig,
) -> Callable[..., LLMClient]:
    def factory(
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        usage_sink: Callable[[UsageRecord], None] | None = None,
    ) -> LLMClient:
        return LLMClient(sample_config, transport=transport, usage_sink=usage_sink)

    return factory
