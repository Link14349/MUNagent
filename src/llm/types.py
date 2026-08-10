"""LLM 消息与流式增量类型."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

MessageRole = Literal["system", "user", "assistant", "tool"]


@dataclass
class ChatMessage:
    role: MessageRole
    content: str
    tool_call_id: str | None = None

    def to_payload(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        return msg


@dataclass(frozen=True)
class ThinkDelta:
    """思维链增量; 仅展示, 不回喂上下文."""

    text: str
    type: Literal["think"] = "think"


@dataclass(frozen=True)
class TextDelta:
    """正文增量."""

    text: str
    type: Literal["text"] = "text"


@dataclass(frozen=True)
class UsageDelta:
    """流末尾用量汇总."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: str | None = None
    type: Literal["usage"] = "usage"


StreamDelta = ThinkDelta | TextDelta | UsageDelta
