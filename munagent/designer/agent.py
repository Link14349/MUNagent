"""场景设计 Agent loop — 见 design/designer/03-agent-interaction.md §7."""

from __future__ import annotations

import asyncio
import difflib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from munagent.config.models import AppConfig
from munagent.designer import prompt as prompt_seg
from munagent.designer.scenario import chats as chat_svc
from munagent.designer.scenario import files as file_svc
from munagent.designer.tools import ToolContext, execute_tool, openai_tool_definitions
from munagent.llm import ChatMessage, LLMClient
from munagent.llm.stream import (
    TextDelta,
    ThinkDelta,
    ToolCall,
    ToolCallDelta,
    UsageDelta,
)
from munagent.security.sanitize import sanitize_text

LLM_ROLE = "designer"
MAX_TOOL_CALLS_PER_TASK = 30
TOOL_TIMEOUT_S = 600.0  # 单次工具执行上限 10 分钟


class LoopResult(str, Enum):
    DONE = "done"
    ABORTED = "aborted"
    FAILED = "failed"


class AgentEventSink(Protocol):
    """可选事件回调 — 由 server 层接 SSE, loop 本身不依赖 HTTP."""

    def on_think_delta(self, text: str) -> None: ...

    def on_text_delta(self, text: str) -> None: ...

    def on_record_appended(self, record: dict[str, Any]) -> None: ...


@dataclass
class _NoopEventSink:
    def on_think_delta(self, text: str) -> None:
        del text

    def on_text_delta(self, text: str) -> None:
        del text

    def on_record_appended(self, record: dict[str, Any]) -> None:
        del record


@dataclass
class Agent:
    """Designer Agent — 绑定场景包 + 单个 chat, 驱动 function calling 主循环."""

    scenario_id: str
    chat_id: str
    config: AppConfig
    context_file: str | None = None
    llm: LLMClient | None = None
    event_sink: AgentEventSink = field(default_factory=_NoopEventSink)
    abort_check: Callable[[], bool] | None = None

    messages: list[ChatMessage] = field(default_factory=list, init=False)
    turn: int = field(default=0, init=False)
    _tool_calls_total: int = field(default=0, init=False)
    _usage_totals: UsageDelta | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.llm is None:
            self.llm = LLMClient(self.config)

    # --- 对外主入口(用户框架中的 loop) ---

    async def loop(self, user_prompt: str, *, max_steps: int = 30) -> LoopResult:
        """一次用户消息触发的 Agent 任务."""
        self.messages = self.get_chat_messages()
        self.turn = self._next_turn()
        self._tool_calls_total = 0
        self._usage_totals = None

        self.add_message(
            ChatMessage(role="user", content=user_prompt),
            chat_record={"type": "user_message", "text": user_prompt},
        )

        result = LoopResult.DONE
        for _ in range(max_steps):
            if self._aborted():
                result = LoopResult.ABORTED
                break

            step = await self._llm_step()
            if step is None:
                result = LoopResult.FAILED
                break
            content, tool_calls, usage = step
            if usage is not None:
                self._usage_totals = usage

            if not tool_calls:
                if content.strip():
                    self.add_message(
                        ChatMessage(role="assistant", content=content),
                        chat_record={"type": "agent_text", "text": content},
                    )
                break

            assistant = ChatMessage(
                role="assistant",
                content=content or "",
                tool_calls=[
                    ToolCall(id=c.id, name=c.name, arguments=c.arguments) for c in tool_calls
                ],
            )
            self.messages.append(assistant)
            if content.strip():
                self._persist_chat_record({"type": "agent_text", "text": content})

            for call in tool_calls:
                if self._aborted():
                    result = LoopResult.ABORTED
                    break
                if self._tool_calls_total >= MAX_TOOL_CALLS_PER_TASK:
                    self._persist_chat_record(
                        {
                            "type": "system",
                            "kind": "error",
                            "text": f"工具调用已达上限 {MAX_TOOL_CALLS_PER_TASK} 次",
                        }
                    )
                    result = LoopResult.FAILED
                    break

                await self._run_tool(call)
                self._tool_calls_total += 1

            if result != LoopResult.DONE:
                break
        else:
            self._persist_chat_record(
                {
                    "type": "system",
                    "kind": "error",
                    "text": f"Agent 步数已达上限 {max_steps}",
                }
            )
            result = LoopResult.FAILED

        self._persist_usage()
        if result == LoopResult.ABORTED:
            self._persist_chat_record(
                {"type": "system", "kind": "aborted", "text": "任务已中止"}
            )
        return result

    # --- 用户框架: 统一写入 messages + JSONL ---

    def add_message(
        self,
        msg: ChatMessage,
        *,
        chat_record: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """追加 LLM 消息; chat_record 非空时同步落盘 chats JSONL."""
        self.messages.append(msg)
        if chat_record is None:
            return None
        return self._persist_chat_record(chat_record)

    def get_chat_messages(self) -> list[ChatMessage]:
        """组装发给 LLM 的 messages: G → H → L → JSONL 历史."""
        messages: list[ChatMessage] = [ChatMessage(role="system", content=prompt_seg.G)]
        if prompt_seg.H.strip():
            messages.append(ChatMessage(role="system", content=prompt_seg.H))
        messages.append(
            ChatMessage(
                role="system",
                content=prompt_seg.build_L(self.scenario_id, context_file=self.context_file),
            )
        )

        records = chat_svc.get_chat_records(self.scenario_id, self.chat_id)
        for rec in records:
            if rec.get("type") == "meta":
                continue
            messages.extend(_record_to_chat_messages(rec))
        return messages

    # 保留用户草稿中的命名
    getChatMessages = get_chat_messages
    addMessage = add_message

    # --- 内部 ---

    def _next_turn(self) -> int:
        records = chat_svc.get_chat_records(self.scenario_id, self.chat_id)
        return sum(1 for r in records if r.get("type") == "user_message") + 1

    def _persist_chat_record(self, record: dict[str, Any]) -> dict[str, Any]:
        entry = chat_svc.append_chat_record(
            self.scenario_id,
            self.chat_id,
            record,
            turn=self.turn,
        )
        self.event_sink.on_record_appended(entry)
        return entry

    def _persist_usage(self) -> None:
        if self._usage_totals is None:
            return
        u = self._usage_totals
        _provider, _base, model = self.llm.resolve_route(LLM_ROLE)  # type: ignore[union-attr]
        self._persist_chat_record(
            {
                "type": "usage",
                "model": model,
                "input_tokens": u.prompt_tokens,
                "output_tokens": u.completion_tokens,
                "tool_calls": self._tool_calls_total,
            }
        )

    def _aborted(self) -> bool:
        return self.abort_check is not None and self.abort_check()

    async def _llm_step(self) -> tuple[str, list[ToolCallDelta], UsageDelta | None] | None:
        """单步流式 LLM 调用, 聚合正文/工具/用量."""
        assert self.llm is not None
        content_parts: list[str] = []
        tool_calls: list[ToolCallDelta] = []
        usage: UsageDelta | None = None
        try:
            async for delta in self.llm.chat_stream(
                LLM_ROLE,
                self.messages,
                tools=openai_tool_definitions(),
                thinking_enabled=True,
            ):
                if isinstance(delta, ThinkDelta):
                    self.event_sink.on_think_delta(delta.text)
                elif isinstance(delta, TextDelta):
                    content_parts.append(delta.text)
                    self.event_sink.on_text_delta(delta.text)
                elif isinstance(delta, ToolCallDelta):
                    tool_calls.append(delta)
                elif isinstance(delta, UsageDelta):
                    usage = delta
        except Exception as exc:
            self._persist_chat_record(
                {
                    "type": "system",
                    "kind": "error",
                    "text": sanitize_text(str(exc)),
                }
            )
            return None
        return "".join(content_parts), tool_calls, usage

    async def _run_tool(self, call: ToolCallDelta) -> None:
        """执行单个工具调用并回喂 messages + 落盘 tool_call/(file_edit)."""
        args_summary = _args_summary(call)
        self.event_sink.on_record_appended(
            {
                "type": "tool_call",
                "tool": call.name,
                "args_summary": args_summary,
                "status": "running",
                "turn": self.turn,
            }
        )
        ctx = ToolContext(
            scenario_id=self.scenario_id,
            config=self.config,
            chat_id=self.chat_id,
            turn=self.turn,
        )
        try:
            args = json.loads(call.arguments or "{}")
        except json.JSONDecodeError:
            args = {}

        old_content: str | None = None
        if call.name == "write_file" and isinstance(args.get("path"), str):
            try:
                old_content = file_svc.get_file(self.scenario_id, args["path"]).content
            except (FileNotFoundError, ValueError):
                old_content = ""

        try:
            result = await asyncio.wait_for(
                execute_tool(ctx, call.name, args),
                timeout=TOOL_TIMEOUT_S,
            )
        except TimeoutError:
            result_summary = "工具执行超时(10 分钟)"
            status = "error"
            tool_payload = result_summary
            self._persist_chat_record(
                {
                    "type": "tool_call",
                    "tool": call.name,
                    "args_summary": args_summary,
                    "status": status,
                    "result_summary": result_summary,
                }
            )
            self.messages.append(
                ChatMessage(
                    role="tool",
                    content=tool_payload,
                    tool_call_id=call.id,
                )
            )
            return

        status = "ok" if result.ok else "error"
        result_summary = sanitize_text(result.summary)
        self._persist_chat_record(
            {
                "type": "tool_call",
                "tool": call.name,
                "args_summary": args_summary,
                "status": status,
                "result_summary": result_summary,
            }
        )

        if result.ok and call.name == "write_file" and result.data:
            path = str(result.data.get("path", ""))
            op = str(result.data.get("op", "modify"))
            new_content = str(args.get("content", ""))
            diff = _unified_diff(old_content or "", new_content, path)
            self._persist_chat_record(
                {"type": "file_edit", "path": path, "op": op, "diff": diff}
            )

        tool_payload = result_summary
        if result.data:
            tool_payload = json.dumps(
                {"summary": result_summary, "data": result.data},
                ensure_ascii=False,
            )
        self.messages.append(
            ChatMessage(role="tool", content=tool_payload, tool_call_id=call.id)
        )


def _args_summary(call: ToolCallDelta) -> str:
    try:
        args = json.loads(call.arguments or "{}")
        if isinstance(args, dict) and args:
            return ", ".join(f"{k}={v!r}" for k, v in list(args.items())[:3])
    except json.JSONDecodeError:
        pass
    raw = (call.arguments or "").strip()
    return raw[:120] + ("…" if len(raw) > 120 else "")


def _unified_diff(old: str, new: str, path: str) -> str:
    lines = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return "".join(lines)


def _record_to_chat_messages(rec: dict[str, Any]) -> list[ChatMessage]:
    """从 JSONL 记录重建 LLM 历史(工具只保留摘要, 见 01-data-chats §2.3)."""
    rtype = rec.get("type")
    if rtype == "user_message":
        return [ChatMessage(role="user", content=str(rec.get("text", "")))]
    if rtype == "agent_text":
        return [ChatMessage(role="assistant", content=str(rec.get("text", "")))]
    if rtype == "tool_call" and rec.get("status") in {"ok", "error"}:
        tool = rec.get("tool") or "tool"
        args = rec.get("args_summary") or ""
        result = rec.get("result_summary") or ""
        return [
            ChatMessage(
                role="assistant",
                content=f"[工具 {tool}] {args} → {result}",
            )
        ]
    if rtype == "file_edit":
        path = rec.get("path") or "?"
        op = rec.get("op") or "modify"
        return [ChatMessage(role="assistant", content=f"[文件编辑 {op}] {path}")]
    if rtype == "todo":
        return [ChatMessage(role="assistant", content=f"[计划清单]\n{rec.get('text', '')}")]
    if rtype == "system":
        return [ChatMessage(role="user", content=f"(系统) {rec.get('text', '')}")]
    return []
