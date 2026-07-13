"""LLM 客户端 mock 测试 — 不打真实 API."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from munagent.llm.client import parse_tool_arguments, sanitize_tool_arguments
from munagent.llm import (
    ChatMessage,
    LLMClient,
    StreamDelta,
    TextDelta,
    ThinkDelta,
    ToolCall,
    ToolCallDelta,
    UsageDelta,
)


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


# ---------- chat_stream ----------


def _sse_body(*chunks: dict[str, Any]) -> bytes:
    lines = [f"data: {json.dumps(c)}\n\n" for c in chunks]
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


def _stream_chunks() -> list[dict[str, Any]]:
    """reasoning → content → tool_calls 参数分片 → 末 chunk 带 usage."""
    return [
        {"choices": [{"delta": {"reasoning_content": "先想想"}}]},
        {"choices": [{"delta": {"content": "我来"}}]},
        {"choices": [{"delta": {"content": "读文件。"}}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "read_file", "arguments": ""},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"path"'}}]}}
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [{"index": 0, "function": {"arguments": ': "seats/"}'}}]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
        {
            "choices": [],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 7,
                "prompt_cache_hit_tokens": 6,
                "prompt_cache_miss_tokens": 4,
            },
        },
    ]


async def _collect(client: LLMClient, **kwargs: Any) -> list[StreamDelta]:
    return [
        d
        async for d in client.chat_stream(
            "delegate", [ChatMessage(role="user", content="ping")], **kwargs
        )
    ]


@pytest.mark.asyncio
async def test_chat_stream_deltas_and_usage(sample_config, usage_collector) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content.decode()))
        return httpx.Response(
            200,
            content=_sse_body(*_stream_chunks()),
            headers={"content-type": "text/event-stream"},
        )

    client = LLMClient(
        sample_config, usage_sink=usage_collector.emit, transport=httpx.MockTransport(handler)
    )
    tools = [{"type": "function", "function": {"name": "read_file", "parameters": {}}}]
    deltas = await _collect(client, tools=tools)

    assert captured["stream"] is True
    assert captured["stream_options"] == {"include_usage": True}
    assert captured["tools"] == tools

    assert [type(d) for d in deltas] == [ThinkDelta, TextDelta, TextDelta, ToolCallDelta, UsageDelta]
    tool = deltas[3]
    assert isinstance(tool, ToolCallDelta)
    assert tool.id == "call_1"
    assert tool.name == "read_file"
    assert json.loads(tool.arguments) == {"path": "seats/"}

    assert len(usage_collector.records) == 1
    rec = usage_collector.records[0]
    assert rec.prompt_tokens == 10
    assert rec.cache_hit_tokens == 6


@pytest.mark.asyncio
async def test_chat_stream_retries_before_first_delta(sample_config) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, text="boom")
        return httpx.Response(
            200,
            content=_sse_body({"choices": [{"delta": {"content": "ok"}}]}),
            headers={"content-type": "text/event-stream"},
        )

    client = LLMClient(sample_config, transport=httpx.MockTransport(handler))
    deltas = await _collect(client)
    assert calls["n"] == 2
    assert deltas == [TextDelta(text="ok")]


class _BreakMidStream(httpx.AsyncByteStream):
    """先吐一个合法 chunk 再断流 — 模拟已开始吐字后的网络中断."""

    async def __aiter__(self):  # type: ignore[override]
        yield b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
        raise httpx.ReadError("connection lost")


class _MidStreamTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.calls = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        return httpx.Response(
            200,
            stream=_BreakMidStream(),
            headers={"content-type": "text/event-stream"},
            request=request,
        )


@pytest.mark.asyncio
async def test_chat_stream_no_retry_after_first_delta(sample_config) -> None:
    transport = _MidStreamTransport()
    client = LLMClient(sample_config, transport=transport)
    got: list[StreamDelta] = []
    with pytest.raises(RuntimeError):
        async for d in client.chat_stream(
            "delegate", [ChatMessage(role="user", content="ping")]
        ):
            got.append(d)
    assert got == [TextDelta(text="hi")]
    assert transport.calls == 1  # 已吐字, 不得静默重试


def test_chat_message_tool_payload() -> None:
    call = ToolCall(id="call_1", name="read_file", arguments='{"path": "x"}')
    assistant = ChatMessage(role="assistant", content="看一下", tool_calls=[call])
    assert assistant.to_payload() == {
        "role": "assistant",
        "content": "看一下",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "read_file", "arguments": '{"path": "x"}'},
            }
        ],
    }
    tool_msg = ChatMessage(role="tool", content="文件内容…", tool_call_id="call_1")
    assert tool_msg.to_payload() == {
        "role": "tool",
        "content": "文件内容…",
        "tool_call_id": "call_1",
    }
    plain = ChatMessage(role="user", content="hi")
    assert plain.to_payload() == {"role": "user", "content": "hi"}


def test_sanitize_tool_arguments_replaces_invalid_json() -> None:
    bad = '{"content": "# incomplete'
    assert sanitize_tool_arguments(bad) == "{}"
    payload = ChatMessage(
        role="assistant",
        content="",
        tool_calls=[ToolCall(id="c1", name="write_file", arguments=bad)],
    ).to_payload()
    assert payload["tool_calls"][0]["function"]["arguments"] == "{}"


def test_parse_tool_arguments_invalid() -> None:
    args, err = parse_tool_arguments('{"path":')
    assert args == {}
    assert err is not None
    assert "JSON 无效" in err


def test_parse_tool_arguments_truncated_write_hint() -> None:
    truncated = '{"path": "background.md", "content": "# ' + "x" * 200
    args, err = parse_tool_arguments(truncated)
    assert args == {}
    assert err is not None
    assert "Unterminated string" in err
    assert "append_file" in err
