"""OpenAI 兼容 SSE chunk 解析."""

from __future__ import annotations

from typing import Any

from llm.types import (
    StreamDelta,
    TextDelta,
    ThinkDelta,
    ToolCall,
    ToolCallDelta,
    ToolCallsDelta,
    UsageDelta,
)


class ChunkParser:
    """把流式 chunk 逐个喂入, 产出类型化增量."""

    def __init__(self) -> None:
        self.usage_raw: dict[str, Any] | None = None
        self.finish_reason: str | None = None
        self._tool_acc: dict[int, dict[str, str]] = {}

    def feed(self, chunk: dict[str, Any]) -> list[StreamDelta]:
        deltas: list[StreamDelta] = []
        if chunk.get("usage"):
            self.usage_raw = chunk["usage"]
        choices = chunk.get("choices") or []
        if choices:
            fr = choices[0].get("finish_reason")
            if fr:
                self.finish_reason = str(fr)
        if not choices:
            return deltas
        delta = choices[0].get("delta") or {}
        reasoning = delta.get("reasoning_content")
        if reasoning:
            deltas.append(ThinkDelta(text=str(reasoning)))
        content = delta.get("content")
        if content:
            deltas.append(TextDelta(text=str(content)))
        for item in delta.get("tool_calls") or []:
            parsed = self._ingest_tool_call_fragment(item)
            if parsed is not None:
                deltas.append(parsed)
        return deltas

    def _ingest_tool_call_fragment(self, item: Any) -> ToolCallDelta | None:
        if not isinstance(item, dict):
            return None
        raw_index = item.get("index", 0)
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            index = 0
        acc = self._tool_acc.setdefault(
            index, {"id": "", "name": "", "arguments": ""}
        )
        call_id = item.get("id")
        if call_id:
            acc["id"] = str(call_id)
        function = item.get("function") or {}
        name = function.get("name")
        if name:
            acc["name"] = str(name)
        arguments = function.get("arguments")
        arg_fragment = ""
        if arguments is not None:
            arg_fragment = str(arguments)
            acc["arguments"] += arg_fragment
        return ToolCallDelta(
            index=index,
            id=str(call_id) if call_id else None,
            name=str(name) if name else None,
            arguments=arg_fragment,
        )

    def assembled_tool_calls(self) -> tuple[ToolCall, ...]:
        """按 index 顺序组装本轮已收到的完整 tool_calls."""
        calls: list[ToolCall] = []
        for index in sorted(self._tool_acc):
            acc = self._tool_acc[index]
            call_id = acc["id"]
            name = acc["name"]
            if not call_id or not name:
                continue
            calls.append(
                ToolCall(id=call_id, name=name, arguments=acc["arguments"])
            )
        return tuple(calls)

    def finish(self) -> list[StreamDelta]:
        deltas: list[StreamDelta] = []
        calls = self.assembled_tool_calls()
        if calls:
            deltas.append(ToolCallsDelta(calls=calls))
        if self.usage_raw is not None:
            deltas.append(
                UsageDelta(
                    prompt_tokens=int(self.usage_raw.get("prompt_tokens") or 0),
                    completion_tokens=int(
                        self.usage_raw.get("completion_tokens") or 0
                    ),
                    finish_reason=self.finish_reason,
                )
            )
        elif self.finish_reason is not None and not calls:
            # 无 usage 但仍有 finish_reason 时不额外发空 UsageDelta
            pass
        return deltas
