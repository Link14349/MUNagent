"""流式增量类型与 SSE chunk 解析 — chat_stream 与 agent loop 的模块边界.

设计见 design/designer/03-agent-interaction.md §7.2-7.3: llm 层产出类型化增量,
上层(agent loop)不接触原始 chunk; tool_calls 的参数碎片在这里拼装, 只对外交付完整调用.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class ThinkDelta(BaseModel):
    """思维链增量(reasoning_content); 只做实时展示, 不回喂上下文."""

    type: Literal["think"] = "think"
    text: str


class TextDelta(BaseModel):
    """正文增量(content); 逐字推给前端."""

    type: Literal["text"] = "text"
    text: str


class ToolCall(BaseModel):
    """一次完整的工具调用; arguments 为原始 JSON 字符串, 由调用方解析校验."""

    id: str
    name: str
    arguments: str


class ToolCallDelta(ToolCall):
    """拼装完成后才产出, 不含碎片状态."""

    type: Literal["tool_call"] = "tool_call"


class UsageDelta(BaseModel):
    """流末尾的用量汇总(stream_options.include_usage)."""

    type: Literal["usage"] = "usage"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0


StreamDelta = ThinkDelta | TextDelta | ToolCallDelta | UsageDelta


class ChunkParser:
    """把 OpenAI 兼容流式 chunk 逐个喂入, 产出类型化增量.

    tool_calls 参数按 index 累积, 流结束调用 finish() 时统一产出——
    参数不需要逐字展示, 攒完整再交付可免去上层处理半截 JSON.
    """

    def __init__(self) -> None:
        self._tool_calls: dict[int, dict[str, str]] = {}
        self.usage_raw: dict[str, Any] | None = None

    def feed(self, chunk: dict[str, Any]) -> list[StreamDelta]:
        deltas: list[StreamDelta] = []
        if chunk.get("usage"):
            self.usage_raw = chunk["usage"]
        choices = chunk.get("choices") or []
        if not choices:
            return deltas
        delta = choices[0].get("delta") or {}
        reasoning = delta.get("reasoning_content")
        if reasoning:
            deltas.append(ThinkDelta(text=str(reasoning)))
        content = delta.get("content")
        if content:
            deltas.append(TextDelta(text=str(content)))
        for frag in delta.get("tool_calls") or []:
            slot = self._tool_calls.setdefault(
                int(frag.get("index") or 0), {"id": "", "name": "", "arguments": ""}
            )
            if frag.get("id"):
                slot["id"] = str(frag["id"])
            fn = frag.get("function") or {}
            if fn.get("name"):
                slot["name"] = str(fn["name"])
            if fn.get("arguments"):
                slot["arguments"] += str(fn["arguments"])
        return deltas

    def finish(self) -> list[StreamDelta]:
        """流结束后调用: 产出拼装完成的工具调用与用量."""
        deltas: list[StreamDelta] = [
            ToolCallDelta(**self._tool_calls[i]) for i in sorted(self._tool_calls)
        ]
        if self.usage_raw is not None:
            hit = int(self.usage_raw.get("prompt_cache_hit_tokens") or 0)
            miss = int(self.usage_raw.get("prompt_cache_miss_tokens") or 0)
            if hit == 0 and miss == 0:
                miss = int(self.usage_raw.get("prompt_tokens") or 0)
            deltas.append(
                UsageDelta(
                    prompt_tokens=int(self.usage_raw.get("prompt_tokens") or 0),
                    completion_tokens=int(self.usage_raw.get("completion_tokens") or 0),
                    cache_hit_tokens=hit,
                    cache_miss_tokens=miss,
                )
            )
        return deltas
