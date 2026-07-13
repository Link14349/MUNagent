"""场景设计 Agent loop — 见 design/designer/03-agent-interaction.md §7."""

from __future__ import annotations

import asyncio
import difflib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from munagent.config.models import AppConfig
from munagent.designer import prompt as prompt_seg
from munagent.designer.scenario import chats as chat_svc
from munagent.designer.scenario import files as file_svc
from munagent.designer.tools.base import SUMMARY_MAX_LEN, ToolContext, clip_summary
from munagent.designer.tools.registry import execute_tool, openai_tool_definitions
from munagent.llm import ChatMessage, LLMClient, parse_tool_arguments, sanitize_tool_arguments
from munagent.llm.stream import (
    TextDelta,
    ThinkDelta,
    ToolCall,
    ToolCallDelta,
    UsageDelta,
)
from munagent.security.sanitize import sanitize_text

LLM_ROLE = "designer"
MAX_TOOL_CALLS_PER_TASK = 50
MAX_PSEUDO_TOOL_NUDGES = 3
TOOL_TIMEOUT_S = 600.0  # 单次工具执行上限 10 分钟
_FILE_MUTATION_TOOLS = frozenset({"write_file", "append_file", "insert_file", "delete_file"})
# write_file 的 content 嵌在 tool arguments JSON 里; thinking + 长正文易触顶默认 4096 输出上限
DESIGNER_MAX_TOKENS = 65_536
DESIGNER_MAX_TOKENS_RETRY = 65_536

# 历史 replay 曾用 assistant+[工具 xxx] 格式, 长对话后模型会模仿; 检测用于拦截与清洗.
_PSEUDO_TOOL_LINE_RE = re.compile(
    r"^\s*\[(?:工具|文件编辑|计划清单)\b",
    re.MULTILINE,
)
_PSEUDO_TOOL_INLINE_RE = re.compile(r"\[(?:工具|文件编辑)\s+\w+")


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
    _pseudo_tool_nudges: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.llm is None:
            self.llm = LLMClient(self.config)

    # --- 对外主入口(用户框架中的 loop) ---

    async def loop(self, user_prompt: str, *, max_steps: int = 50) -> LoopResult:
        """一次用户消息触发的 Agent 任务."""
        self.messages = self.get_chat_messages()
        self.turn = self._next_turn()
        self._tool_calls_total = 0
        self._usage_totals = None
        self._pseudo_tool_nudges = 0

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
                if content.strip() and looks_like_pseudo_tools(content):
                    if self._pseudo_tool_nudges >= MAX_PSEUDO_TOOL_NUDGES:
                        self._persist_chat_record(
                            {
                                "type": "system",
                                "kind": "error",
                                "text": "多次在正文中模拟工具调用而未使用 function calling, 任务中止",
                            }
                        )
                        result = LoopResult.FAILED
                        break
                    self._pseudo_tool_nudges += 1
                    self.messages.append(ChatMessage(role="assistant", content=content))
                    self.messages.append(
                        ChatMessage(
                            role="user",
                            content=(
                                "(系统) 你刚才在正文里写了 `[工具 xxx]` / `[文件编辑 xxx]` 等格式, "
                                "但没有发出 function calling, 这些文字不会执行任何操作. "
                                "请立即通过 tools 真正调用; 若只是向用户说明进度, 用普通 Markdown, "
                                "不要伪造工具行."
                            ),
                        )
                    )
                    self._persist_chat_record(
                        {
                            "type": "system",
                            "kind": "error",
                            "text": "拦截模拟工具调用, 要求改用 function calling",
                        }
                    )
                    continue

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
                    ToolCall(
                        id=c.id,
                        name=c.name,
                        arguments=sanitize_tool_arguments(c.arguments),
                    )
                    for c in tool_calls
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
                content=prompt_seg.build_L(
                    self.scenario_id,
                    context_file=self.context_file,
                    chat_id=self.chat_id,
                ),
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

    def _refresh_L_message(self) -> None:
        """每步 LLM 调用前刷新 L 段(文件清单/todo 等), 避免多步任务内上下文过期."""
        l_idx = 2 if prompt_seg.H.strip() else 1
        if len(self.messages) <= l_idx or self.messages[l_idx].role != "system":
            return
        self.messages[l_idx] = ChatMessage(
            role="system",
            content=prompt_seg.build_L(
                self.scenario_id,
                context_file=self.context_file,
                chat_id=self.chat_id,
            ),
        )

    async def _llm_step(
        self, *, max_tokens: int = DESIGNER_MAX_TOKENS
    ) -> tuple[str, list[ToolCallDelta], UsageDelta | None] | None:
        """单步流式 LLM 调用, 聚合正文/工具/用量."""
        self._refresh_L_message()
        assert self.llm is not None
        content_parts: list[str] = []
        tool_calls: list[ToolCallDelta] = []
        usage: UsageDelta | None = None
        try:
            async for delta in self.llm.chat_stream(
                LLM_ROLE,
                self.messages,
                tools=openai_tool_definitions(),
                max_tokens=max_tokens,
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
        args, args_err = parse_tool_arguments(call.arguments)
        if args_err is not None:
            result_summary = sanitize_text(f"{call.name}: {args_err}")
            self._persist_chat_record(
                {
                    "type": "tool_call",
                    "tool": call.name,
                    "args_summary": args_summary,
                    "status": "error",
                    "result_summary": clip_summary(result_summary),
                }
            )
            self.messages.append(
                ChatMessage(
                    role="tool",
                    content=json.dumps(
                        {"summary": clip_summary(result_summary), "error": args_err},
                        ensure_ascii=False,
                    ),
                    tool_call_id=call.id,
                )
            )
            return

        old_content: str | None = None
        if call.name in _FILE_MUTATION_TOOLS and isinstance(args.get("path"), str):
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

        if result.ok and call.name in _FILE_MUTATION_TOOLS and result.data:
            path = str(result.data.get("path", ""))
            op = str(result.data.get("op", "modify"))
            new_content = str(result.data.get("new_content", args.get("content", "")))
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
        _compact_tool_call_arguments(self.messages, call)

        if call.name == "edit_todo" and result.ok:
            for rec in reversed(chat_svc.get_chat_records(self.scenario_id, self.chat_id)):
                if rec.get("type") == "todo":
                    self.event_sink.on_record_appended(rec)
                    break

        if (
            result.ok
            and call.name in _FILE_MUTATION_TOOLS
            and _todo_has_pending(self.scenario_id, self.chat_id)
        ):
            self.messages.append(
                ChatMessage(
                    role="user",
                    content=(
                        "(系统) 计划清单仍有未完成项. "
                        "若刚完成的文件写入对应其中一行, 下一步须先 edit_todo 勾掉再继续."
                    ),
                )
            )


def _todo_has_pending(scenario_id: str, chat_id: str) -> bool:
    """当前 chat 是否存在尚未全部勾选的 todo."""
    try:
        records = chat_svc.get_chat_records(scenario_id, chat_id)
    except FileNotFoundError:
        return False
    todo = chat_svc.derive_todo(records)
    if not todo:
        return False
    total = sum(1 for ln in todo.splitlines() if ln.strip())
    return todo.count("[x] ") < total


def _compact_tool_call_arguments(messages: list[ChatMessage], call: ToolCallDelta) -> None:
    """工具已执行后缩略 assistant.tool_calls.arguments, 避免单轮多次 write 撑爆上下文."""
    if call.name not in {"write_file", "append_file", "insert_file", "edit_todo"}:
        return
    compact = _args_summary(call)
    for msg in reversed(messages):
        if msg.role != "assistant" or not msg.tool_calls:
            continue
        for tc in msg.tool_calls:
            if tc.id == call.id:
                tc.arguments = json.dumps({"_summary": compact}, ensure_ascii=False)
                return
        break


def _args_summary(call: ToolCallDelta) -> str:
    """工具参数单行摘要 — 大字段(如 write_file.content)不得落全文, 见 01-data-chats §2.2."""
    try:
        args = json.loads(call.arguments or "{}")
    except json.JSONDecodeError:
        args = None

    if not isinstance(args, dict) or not args:
        raw = (call.arguments or "").strip()
        return raw[:120] + ("…" if len(raw) > 120 else "")

    if call.name == "write_file":
        path = str(args.get("path") or "?")
        content = args.get("content")
        n = len(content) if isinstance(content, str) else 0
        return clip_summary(f"{path} ({n} 字符)")

    if call.name == "append_file":
        path = str(args.get("path") or "?")
        content = args.get("content")
        n = len(content) if isinstance(content, str) else 0
        return clip_summary(f"{path} (+{n} 字符)")

    if call.name == "insert_file":
        path = str(args.get("path") or "?")
        content = args.get("content")
        n = len(content) if isinstance(content, str) else 0
        pos = args.get("position") or "after"
        anchor = args.get("anchor") or "?"
        anchor_short = anchor if len(str(anchor)) <= 40 else str(anchor)[:39] + "…"
        return clip_summary(f"{path} {pos} {anchor_short!r} (+{n} 字符)")

    if call.name == "delete_file":
        return clip_summary(str(args.get("path") or "?"))

    if call.name == "edit_todo":
        todo = args.get("todo")
        if isinstance(todo, str):
            total = sum(1 for ln in todo.splitlines() if ln.strip())
            done = todo.count("[x] ")
            return clip_summary(f"计划 {done}/{total} 项")
        return "edit_todo"

    if call.name in {"read_file", "download_file", "mineru_convert"}:
        path = args.get("path")
        if isinstance(path, str) and path:
            return clip_summary(f"path={path!r}")

    parts: list[str] = []
    for k, v in list(args.items())[:3]:
        if isinstance(v, str) and len(v) > 80:
            parts.append(f"{k}=({len(v)} 字符)")
        else:
            parts.append(f"{k}={v!r}")
    text = ", ".join(parts)
    if len(text) <= SUMMARY_MAX_LEN:
        return text
    return text[: SUMMARY_MAX_LEN - 1] + "…"


def _unified_diff(old: str, new: str, path: str) -> str:
    lines = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return "".join(lines)


def looks_like_pseudo_tools(text: str) -> bool:
    """正文是否像在模拟工具调用(而非 function calling)."""
    if _PSEUDO_TOOL_LINE_RE.search(text):
        return True
    return bool(_PSEUDO_TOOL_INLINE_RE.search(text))


def strip_pseudo_tool_lines(text: str) -> str:
    kept = [ln for ln in text.splitlines() if not _PSEUDO_TOOL_LINE_RE.match(ln)]
    return "\n".join(kept).strip()


def _record_to_chat_messages(rec: dict[str, Any]) -> list[ChatMessage]:
    """从 JSONL 记录重建 LLM 历史; 工具/编辑/todo 用 user 角色摘要, 避免模型模仿 [工具 xxx] 格式."""
    rtype = rec.get("type")
    if rtype == "user_message":
        return [ChatMessage(role="user", content=str(rec.get("text", "")))]
    if rtype == "agent_text":
        text = str(rec.get("text", ""))
        if looks_like_pseudo_tools(text):
            cleaned = strip_pseudo_tool_lines(text)
            if len(cleaned) >= 80:
                return [ChatMessage(role="assistant", content=cleaned)]
            return [
                ChatMessage(
                    role="user",
                    content="(历史回合) 上轮 Agent 在正文中模拟了工具调用(坏样本, 勿模仿). "
                    "实际变更见后续 file_edit / 工具摘要记录.",
                )
            ]
        return [ChatMessage(role="assistant", content=text)]
    if rtype == "tool_call" and rec.get("status") in {"ok", "error"}:
        tool = rec.get("tool") or "tool"
        args = clip_summary(str(rec.get("args_summary") or ""))
        result = rec.get("result_summary") or ""
        status = rec.get("status") or "ok"
        return [
            ChatMessage(
                role="user",
                content=f"(历史工具记录 · {status}) {tool}({args}) → {result}",
            )
        ]
    if rtype == "file_edit":
        path = rec.get("path") or "?"
        op = rec.get("op") or "modify"
        return [ChatMessage(role="user", content=f"(历史文件编辑) {op} {path}")]
    if rtype == "todo":
        return [ChatMessage(role="user", content=f"(历史计划清单)\n{rec.get('text', '')}")]
    if rtype == "system":
        return [ChatMessage(role="user", content=f"(系统) {rec.get('text', '')}")]
    return []
