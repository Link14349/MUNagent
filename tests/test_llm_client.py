"""LLM 客户端 mock 测试 — 不打真实 API."""

from __future__ import annotations

import httpx
import pytest

from munagent.llm import ChatMessage, LLMClient


@pytest.mark.asyncio
async def test_chat_success(
    sample_config,
    mock_llm_transport: httpx.MockTransport,
    usage_collector,
) -> None:
    client = LLMClient(
        sample_config,
        usage_sink=usage_collector.emit,
        transport=mock_llm_transport,
    )
    text = await client.chat(
        "delegate",
        [ChatMessage(role="user", content="ping")],
        max_tokens=1,
        thinking_enabled=False,
    )
    assert text == "pong"
    assert len(usage_collector.records) == 1
    rec = usage_collector.records[0]
    assert rec.cache_hit_tokens == 3
    assert rec.thinking_enabled is False


@pytest.mark.asyncio
async def test_chat_thinking_enabled_by_default(
    sample_config,
) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content.decode()))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    client = LLMClient(sample_config, transport=httpx.MockTransport(handler))
    await client.chat(
        "dm",
        [ChatMessage(role="user", content="x")],
        max_tokens=1,
    )
    assert captured.get("thinking") == {"type": "enabled"}


@pytest.mark.asyncio
async def test_chat_thinking_disabled_param(
    sample_config,
) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content.decode()))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    client = LLMClient(sample_config, transport=httpx.MockTransport(handler))
    await client.chat(
        "delegate",
        [ChatMessage(role="user", content="ping")],
        max_tokens=16,
        thinking_enabled=False,
    )
    assert captured.get("thinking") == {"type": "disabled"}
