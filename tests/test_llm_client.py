"""LLM 客户端单元测试(mock, 不打真实 API)."""

from __future__ import annotations

import httpx
import pytest

from munagent.llm.client import ChatMessage, ChatRequest, LLMClient, LLMError


@pytest.mark.asyncio
async def test_chat_records_usage(
    llm_client_factory,
    mock_llm_transport,
) -> None:
    records = []
    client = llm_client_factory(transport=mock_llm_transport, usage_sink=records.append)
    content = await client.chat(
        ChatRequest(
            role="delegate",
            task="turn",
            messages=[ChatMessage(role="user", content="hello")],
            phase="ModeratedCaucus",
        )
    )
    assert '{"ok": true}' in content
    assert len(records) == 1
    assert records[0].cache_hit_tokens == 8
    assert records[0].cache_miss_tokens == 2
    assert records[0].thinking_enabled is True


@pytest.mark.asyncio
async def test_chat_unmod_disables_thinking(
    llm_client_factory,
    mock_llm_transport,
) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    client = llm_client_factory(transport=httpx.MockTransport(handler))
    await client.chat(
        ChatRequest(
            role="delegate",
            task="turn",
            messages=[ChatMessage(role="user", content="hi")],
            phase="UnmoderatedCaucus",
            scope="group",
        )
    )
    assert "thinking" not in captured["body"]


@pytest.mark.asyncio
async def test_missing_api_key_raises(sample_config) -> None:
    sample_config.providers["deepseek"].api_key = ""
    client = LLMClient(sample_config)
    with pytest.raises(LLMError, match="API key"):
        await client.chat(
            ChatRequest(role="delegate", task="turn", messages=[ChatMessage("user", "x")])
        )


@pytest.mark.asyncio
async def test_test_provider_success(llm_client_factory, mock_llm_transport) -> None:
    client = llm_client_factory(transport=mock_llm_transport)
    record = await client.test_provider("deepseek")
    assert record.task == "config_test"
    assert record.thinking_enabled is False
