"""设计 Agent 工具公共类型与约束."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from munagent.config.models import AppConfig

SUMMARY_MAX_LEN = 200


class ToolContext(BaseModel):
    """单次工具调用上下文 — Agent loop 构造后传入."""

    model_config = {"arbitrary_types_allowed": True}

    scenario_id: str
    config: AppConfig
    chat_id: str | None = None
    turn: int | None = None


class ToolResult(BaseModel):
    """工具执行结果 — summary 写入 chat tool_call 记录."""

    ok: bool
    summary: str = Field(max_length=SUMMARY_MAX_LEN)
    data: dict[str, Any] | None = None


class ToolExecutionError(Exception):
    """工具业务失败(路径非法、只读等), 由 registry 转为 ToolResult."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def clip_summary(text: str, limit: int = SUMMARY_MAX_LEN) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 1] + "…"
