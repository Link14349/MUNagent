"""终局条件证据构建与 LLM 文本裁判。"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
import json
import threading
from typing import Protocol, TYPE_CHECKING

from event.event import InstructionEvent, ResolutionEvent
from filesystem.filesystem import SYSTEM_ACTOR
from llm import ChatMessage, LLMCancelledError, ToolCallsDelta, ToolSpec

if TYPE_CHECKING:
    from llm import LLM
    from scenario.scenario import Scenario


_MAX_EVIDENCE_CHARS = 60_000
_MAX_EVENT_CONTENT_CHARS = 1_200
_MAX_SUBMISSION_PREVIEW_CHARS = 3_000


@dataclass(frozen=True)
class TextEndConditionMatch:
    """文本终局裁判报告的一项已成立条件。"""

    condition_index: int
    reason: str
    evidence_event_ids: tuple[int, ...] = ()


class TextEndConditionEvaluator(Protocol):
    """Simulator 使用的文本终局裁判接口。"""

    def evaluate(
        self,
        conditions: Sequence[tuple[int, str]],
        evidence: str,
    ) -> list[TextEndConditionMatch]: ...

    def stop(self) -> None: ...


class LLMTextEndConditionEvaluator:
    """通过一次强制工具调用批量判断全部文本终局条件。"""

    def __init__(self, llm: LLM) -> None:
        self.llm = llm
        self.__lock = threading.Lock()

    def stop(self) -> None:
        self.llm.stop()

    def evaluate(
        self,
        conditions: Sequence[tuple[int, str]],
        evidence: str,
    ) -> list[TextEndConditionMatch]:
        if not conditions:
            return []
        if not self.__lock.acquire(blocking=False):
            raise RuntimeError("文本终局裁判不能并发执行")
        try:
            return asyncio.run(self._evaluate_async(conditions, evidence))
        finally:
            self.__lock.release()

    async def _evaluate_async(
        self,
        conditions: Sequence[tuple[int, str]],
        evidence: str,
    ) -> list[TextEndConditionMatch]:
        condition_payload = [
            {"condition_index": index, "content": content}
            for index, content in conditions
        ]
        messages = [
            ChatMessage(
                role="system",
                content=(
                    "你是会议终局条件裁判，只根据给出的权威状态和事件证据判断。"
                    "必须保守：证据不足、仅有提议、尚未通过或角色身份不明确时，"
                    "不得判为成立。你不能修改会议，只能调用指定工具报告结果。"
                ),
            ),
            ChatMessage(
                role="user",
                content=(
                    "请批量检查以下终局条件。matched_conditions 只填写已经由证据"
                    "明确满足的条件；若均未满足则提交空数组。\n\n"
                    f"终局条件：\n{json.dumps(condition_payload, ensure_ascii=False)}"
                    f"\n\n权威会议证据：\n{evidence}"
                ),
            ),
        ]
        calls = None
        try:
            async for delta in self.llm.stream(
                messages,
                tools=[_REPORT_TOOL],
                tool_choice={
                    "type": "function",
                    "function": {"name": _REPORT_TOOL.name},
                },
                max_tokens=2_048,
            ):
                if isinstance(delta, ToolCallsDelta):
                    calls = delta.calls
        except LLMCancelledError:
            raise

        if not calls:
            raise RuntimeError("文本终局裁判未调用 report_end_conditions")
        report = next(
            (call for call in calls if call.name == _REPORT_TOOL.name),
            None,
        )
        if report is None:
            raise RuntimeError("文本终局裁判调用了错误工具")
        return _parse_report(report.arguments, conditions)


def build_end_condition_evidence(scenario: Scenario) -> str:
    """构建系统裁判可见的权威会议证据，并限制总上下文长度。"""
    header = json.dumps(
        {
            "story_time": scenario.time.isoformat(),
            "title": scenario.title,
            "venues": [
                {
                    "id": venue.id,
                    "phase": (
                        venue.session_phase.value
                        if venue.session_phase is not None
                        else None
                    ),
                    "current_agenda": (
                        venue.current_agenda.id
                        if venue.current_agenda is not None
                        else None
                    ),
                }
                for venue in scenario.venues
            ],
        },
        ensure_ascii=False,
    )
    event_lines: list[str] = []
    for venue in scenario.venues:
        event_list = venue.event_list
        if event_list is None:
            continue
        for event in event_list.events:
            payload: dict[str, object] = {
                "venue": venue.id,
                "id": event.id,
                "time": event.time.isoformat() if event.time is not None else None,
                "type": event.type.value,
                "status": event.status.value,
                "content": _truncate(event.content, _MAX_EVENT_CONTENT_CHARS),
                "scope": sorted(event.scope),
            }
            actor = getattr(event, "from_rep", None)
            if actor is not None:
                payload["from_rep"] = actor
            actors = getattr(event, "from_reps", None)
            if actors is not None:
                payload["from_reps"] = sorted(actors)
            if isinstance(event, (InstructionEvent, ResolutionEvent)):
                submission = (
                    event.instruction
                    if isinstance(event, InstructionEvent)
                    else event.resolution
                )
                payload["submission_hash"] = submission.content_hash
                payload["submission_preview"] = _truncate(
                    submission.get_content(SYSTEM_ACTOR),
                    _MAX_SUBMISSION_PREVIEW_CHARS,
                )
            target = getattr(event, "target", None)
            if target is not None and getattr(target, "id", None) is not None:
                payload["target_event_id"] = target.id
            passed = getattr(event, "passed", None)
            if passed is not None:
                payload["passed"] = passed
            event_lines.append(json.dumps(payload, ensure_ascii=False))

    budget = max(0, _MAX_EVIDENCE_CHARS - len(header) - 32)
    selected: list[str] = []
    used = 0
    for line in reversed(event_lines):
        needed = len(line) + 1
        if selected and used + needed > budget:
            break
        if needed > budget:
            selected.append(line[-budget:])
            break
        selected.append(line)
        used += needed
    selected.reverse()
    omitted = len(event_lines) - len(selected)
    prefix = f"\n已省略更早事件数：{omitted}\n" if omitted else "\n"
    return header + prefix + "\n".join(selected)


def _parse_report(
    raw_arguments: str,
    conditions: Sequence[tuple[int, str]],
) -> list[TextEndConditionMatch]:
    try:
        payload = json.loads(raw_arguments or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("文本终局裁判返回的工具参数不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("文本终局裁判工具参数须为对象")
    raw_matches = payload.get("matched_conditions")
    if not isinstance(raw_matches, list):
        raise ValueError("matched_conditions 须为数组")

    known_indices = {index for index, _ in conditions}
    seen: set[int] = set()
    matches: list[TextEndConditionMatch] = []
    for item in raw_matches:
        if not isinstance(item, dict):
            raise ValueError("matched_conditions 的元素须为对象")
        index = item.get("condition_index")
        if type(index) is not int or index not in known_indices:
            raise ValueError(f"未知终局条件索引: {index!r}")
        if index in seen:
            raise ValueError(f"终局条件索引重复: {index}")
        reason = item.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"终局条件 #{index} 的 reason 不能为空")
        raw_ids = item.get("evidence_event_ids", [])
        if not isinstance(raw_ids, list) or any(
            type(event_id) is not int or event_id < 0 for event_id in raw_ids
        ):
            raise ValueError(f"终局条件 #{index} 的 evidence_event_ids 无效")
        seen.add(index)
        matches.append(
            TextEndConditionMatch(
                condition_index=index,
                reason=reason.strip(),
                evidence_event_ids=tuple(dict.fromkeys(raw_ids)),
            )
        )
    return matches


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"…（截断 {len(value) - limit} 字符）"


_REPORT_TOOL = ToolSpec(
    name="report_end_conditions",
    description="报告当前证据已经明确满足的终局条件；若没有则提交空数组。",
    parameters={
        "type": "object",
        "properties": {
            "matched_conditions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "condition_index": {"type": "integer", "minimum": 0},
                        "reason": {"type": "string", "minLength": 1},
                        "evidence_event_ids": {
                            "type": "array",
                            "items": {"type": "integer", "minimum": 0},
                        },
                    },
                    "required": [
                        "condition_index",
                        "reason",
                        "evidence_event_ids",
                    ],
                },
            }
        },
        "required": ["matched_conditions"],
    },
)
