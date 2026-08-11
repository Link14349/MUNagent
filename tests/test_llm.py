"""LLM 模块 mock 测试 - 不调用真实 API."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from config.models import AppConfig, ProviderConfig
from llm import (
    ChatMessage,
    LLM,
    LLMCancelledError,
    TextDelta,
    ThinkDelta,
    ToolCall,
    ToolCallDelta,
    ToolCallsDelta,
    ToolSpec,
    UsageDelta,
)


@pytest.fixture
def sample_config() -> AppConfig:
    return AppConfig(
        providers={
            "deepseek": ProviderConfig(
                base_url="https://api.deepseek.com",
                api_key="test-key",
            ),
        },
        default_provider="deepseek",
        default_model="deepseek-v4-flash",
    )


def _sse_body(*chunks: dict[str, Any]) -> bytes:
    lines = [f"data: {json.dumps(c)}\n\n" for c in chunks]
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


def _stream_chunks() -> list[dict[str, Any]]:
    return [
        {"choices": [{"delta": {"reasoning_content": "先想想"}}]},
        {"choices": [{"delta": {"content": "你好"}}]},
        {"choices": [{"delta": {"content": "世界"}}]},
        {
            "choices": [{"finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        },
    ]


@pytest.mark.asyncio
async def test_stream_deltas(sample_config: AppConfig) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content.decode()))
        return httpx.Response(
            200,
            content=_sse_body(*_stream_chunks()),
            headers={"content-type": "text/event-stream"},
        )

    llm = LLM(config=sample_config, transport=httpx.MockTransport(handler))
    deltas = [d async for d in llm.stream([ChatMessage(role="user", content="ping")])]

    assert captured["model"] == "deepseek-v4-flash"
    assert captured["stream"] is True
    assert captured["thinking"] == {"type": "enabled"}
    assert captured["stream_options"] == {"include_usage": True}

    assert [type(d) for d in deltas] == [ThinkDelta, TextDelta, TextDelta, UsageDelta]
    assert deltas[1].text == "你好"
    assert deltas[3].prompt_tokens == 5


@pytest.mark.asyncio
async def test_thinking_disabled(sample_config: AppConfig) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content.decode()))
        return httpx.Response(
            200,
            content=_sse_body({"choices": [{"delta": {"content": "ok"}}]}),
            headers={"content-type": "text/event-stream"},
        )

    llm = LLM(config=sample_config, thinking=False, transport=httpx.MockTransport(handler))
    _ = [d async for d in llm.stream([ChatMessage(role="user", content="x")])]
    assert captured["thinking"] == {"type": "disabled"}


@pytest.mark.asyncio
async def test_custom_model(sample_config: AppConfig) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content.decode()))
        return httpx.Response(
            200,
            content=_sse_body({"choices": [{"delta": {"content": "ok"}}]}),
            headers={"content-type": "text/event-stream"},
        )

    llm = LLM(
        config=sample_config,
        model="deepseek-v4-pro",
        transport=httpx.MockTransport(handler),
    )
    _ = [d async for d in llm.stream([ChatMessage(role="user", content="x")])]
    assert captured["model"] == "deepseek-v4-pro"


@pytest.mark.asyncio
async def test_stop_cancels_stream(sample_config: AppConfig) -> None:
    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):  # type: ignore[override]
            yield b'data: {"choices":[{"delta":{"content":"a"}}]}\n\n'
            await asyncio.sleep(5)
            yield b'data: {"choices":[{"delta":{"content":"b"}}]}\n\n'

    llm = LLM(
        config=sample_config,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                stream=SlowStream(),
                headers={"content-type": "text/event-stream"},
                request=request,
            )
        ),
    )

    got: list[str] = []

    async def consume() -> None:
        async for delta in llm.stream([ChatMessage(role="user", content="x")]):
            if isinstance(delta, TextDelta):
                got.append(delta.text)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    llm.stop()
    with pytest.raises(LLMCancelledError):
        await task
    assert got == ["a"]


@pytest.mark.asyncio
async def test_complete_joins_text(sample_config: AppConfig) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_sse_body(
                {"choices": [{"delta": {"content": "你"}}]},
                {"choices": [{"delta": {"content": "好"}}]},
            ),
            headers={"content-type": "text/event-stream"},
        )

    llm = LLM(config=sample_config, transport=httpx.MockTransport(handler))
    text = await llm.complete([ChatMessage(role="user", content="hi")])
    assert text == "你好"


def _send_message_tool() -> ToolSpec:
    return ToolSpec(
        name="send_message",
        description="以本代表身份公开发言",
        parameters={
            "type": "object",
            "properties": {"content": {"type": "string"}},
            "required": ["content"],
        },
    )


@pytest.mark.asyncio
async def test_stream_sends_tools_payload(sample_config: AppConfig) -> None:
    captured: dict[str, Any] = {}
    tool = _send_message_tool()

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content.decode()))
        return httpx.Response(
            200,
            content=_sse_body({"choices": [{"delta": {"content": "ok"}}]}),
            headers={"content-type": "text/event-stream"},
        )

    llm = LLM(config=sample_config, transport=httpx.MockTransport(handler))
    _ = [
        d
        async for d in llm.stream(
            [ChatMessage(role="user", content="发言")],
            tools=[tool],
            tool_choice="auto",
        )
    ]
    assert captured["tools"] == [tool.to_payload()]
    assert captured["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_tool_choice_requires_tools(sample_config: AppConfig) -> None:
    llm = LLM(
        config=sample_config,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=_sse_body())
        ),
    )
    with pytest.raises(ValueError, match="tool_choice"):
        _ = [
            d
            async for d in llm.stream(
                [ChatMessage(role="user", content="x")],
                tool_choice="auto",
            )
        ]


@pytest.mark.asyncio
async def test_stream_parses_tool_calls(sample_config: AppConfig) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_sse_body(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {"name": "send_message", "arguments": ""},
                                    }
                                ]
                            }
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {"arguments": '{"content":'},
                                    }
                                ]
                            }
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {"arguments": '"hello"}'},
                                    }
                                ]
                            }
                        }
                    ]
                },
                {
                    "choices": [{"finish_reason": "tool_calls"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 8},
                },
            ),
            headers={"content-type": "text/event-stream"},
        )

    llm = LLM(config=sample_config, transport=httpx.MockTransport(handler))
    deltas = [
        d
        async for d in llm.stream(
            [ChatMessage(role="user", content="请发言")],
            tools=[_send_message_tool()],
        )
    ]

    assert [type(d) for d in deltas] == [
        ToolCallDelta,
        ToolCallDelta,
        ToolCallDelta,
        ToolCallsDelta,
        UsageDelta,
    ]
    assert deltas[0].id == "call_1"
    assert deltas[0].name == "send_message"
    assert deltas[1].arguments == '{"content":'
    assert deltas[2].arguments == '"hello"}'
    finished = deltas[3]
    assert isinstance(finished, ToolCallsDelta)
    assert finished.calls == (
        ToolCall(
            id="call_1",
            name="send_message",
            arguments='{"content":"hello"}',
        ),
    )
    assert deltas[4].finish_reason == "tool_calls"


def test_chat_message_tool_roundtrip_payload() -> None:
    assistant = ChatMessage(
        role="assistant",
        content="",
        tool_calls=[
            ToolCall(id="call_1", name="send_message", arguments='{"content":"hi"}')
        ],
    )
    tool_result = ChatMessage(
        role="tool",
        content="ok",
        tool_call_id="call_1",
        name="send_message",
    )
    assert assistant.to_payload()["tool_calls"][0]["function"]["name"] == "send_message"
    assert tool_result.to_payload() == {
        "role": "tool",
        "content": "ok",
        "tool_call_id": "call_1",
        "name": "send_message",
    }
