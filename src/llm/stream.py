"""OpenAI 兼容 SSE chunk 解析."""

from __future__ import annotations

from typing import Any

from llm.types import StreamDelta, TextDelta, ThinkDelta, UsageDelta


class ChunkParser:
    """把流式 chunk 逐个喂入, 产出类型化增量."""

    def __init__(self) -> None:
        self.usage_raw: dict[str, Any] | None = None
        self.finish_reason: str | None = None

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
        return deltas

    def finish(self) -> list[StreamDelta]:
        if self.usage_raw is None:
            return []
        return [
            UsageDelta(
                prompt_tokens=int(self.usage_raw.get("prompt_tokens") or 0),
                completion_tokens=int(self.usage_raw.get("completion_tokens") or 0),
                finish_reason=self.finish_reason,
            )
        ]
