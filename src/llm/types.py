"""LLM 消息与流式增量类型."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

MessageRole = Literal["system", "user", "assistant", "tool"]
ToolChoice = Literal["auto", "none", "required"] | dict[str, Any]


@dataclass(frozen=True)
class ToolSpec:
    """发给模型的单个 function tool 定义(OpenAI tools 格式)."""

    name: str
    description: str
    parameters: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True)
class ToolCall:
    """一次完整的函数调用(id + name + arguments JSON 字符串)."""

    id: str
    name: str
    arguments: str


@dataclass
class ChatMessage:
    role: MessageRole
    content: str = ""
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None
    name: str | None = None

    def to_payload(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        if self.name:
            msg["name"] = self.name
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": call.arguments,
                    },
                }
                for call in self.tool_calls
            ]
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
class ToolCallDelta:
    """流式 tool_call 片段;同一 index 的多次增量拼接为完整调用."""

    index: int
    id: str | None = None
    name: str | None = None
    arguments: str = ""
    type: Literal["tool_call"] = "tool_call"


@dataclass(frozen=True)
class ToolCallsDelta:
    """本轮流式结束后组装出的完整 tool_calls."""

    calls: tuple[ToolCall, ...]
    type: Literal["tool_calls"] = "tool_calls"


@dataclass(frozen=True)
class UsageDelta:
    """流末尾用量汇总."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: str | None = None
    type: Literal["usage"] = "usage"


StreamDelta = ThinkDelta | TextDelta | ToolCallDelta | ToolCallsDelta | UsageDelta
