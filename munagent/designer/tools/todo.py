"""Agent 计划清单 — chat 级 check_todo / edit_todo, 见 design/designer/01-data-chats.md §2.4."""

from __future__ import annotations

from pydantic import BaseModel, Field

from munagent.designer.scenario import chats as chat_svc
from munagent.designer.tools.base import ToolContext, ToolExecutionError, ToolResult, clip_summary

_EMPTY_TODO = "(暂无 todo)"


class CheckTodoArgs(BaseModel):
    """无参数 — 读取当前 chat 最新 todo 快照."""


class EditTodoArgs(BaseModel):
    todo: str = Field(description="整份计划清单全文, 一行一项, 非空行以 [ ] 或 [x] 开头")


def _require_chat(ctx: ToolContext) -> str:
    if not ctx.chat_id:
        raise ToolExecutionError("未指定 chat_id")
    return ctx.chat_id


def validate_todo_text(text: str) -> str | None:
    """校验 todo 全文; 合法返回 None, 否则返回错误说明."""
    for i, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        if not (line.startswith("[ ] ") or line.startswith("[x] ")):
            return f"第 {i} 行须以 '[ ] ' 或 '[x] ' 开头"
    return None


def _count_items(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


async def check_todo(ctx: ToolContext, args: CheckTodoArgs) -> ToolResult:
    del args
    chat_id = _require_chat(ctx)
    try:
        records = chat_svc.get_chat_records(ctx.scenario_id, chat_id)
    except FileNotFoundError as exc:
        raise ToolExecutionError(str(exc)) from exc
    current = chat_svc.derive_todo(records)
    text = current if current is not None else _EMPTY_TODO
    done = text.count("[x] ") if current else 0
    total = _count_items(text) if current else 0
    summary = f"todo {done}/{total} 项" if current else "暂无 todo"
    return ToolResult(ok=True, summary=clip_summary(summary), data={"text": text})


async def edit_todo(ctx: ToolContext, args: EditTodoArgs) -> ToolResult:
    chat_id = _require_chat(ctx)
    err = validate_todo_text(args.todo)
    if err:
        raise ToolExecutionError(err)
    try:
        chat_svc.append_chat_record(
            ctx.scenario_id,
            chat_id,
            {"type": "todo", "text": args.todo},
            turn=ctx.turn,
        )
    except (FileNotFoundError, PermissionError) as exc:
        raise ToolExecutionError(str(exc)) from exc
    total = _count_items(args.todo)
    done = args.todo.count("[x] ")
    return ToolResult(
        ok=True,
        summary=clip_summary(f"更新 todo {done}/{total} 项"),
        data={"text": args.todo},
    )
