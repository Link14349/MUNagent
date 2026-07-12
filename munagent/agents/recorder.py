"""书记 Agent: 滚动摘要. 见 05§3.4.

三层摘要:
- venue: 会场公开记录摘要(全体可见事件)
- private: 每席位私人记忆摘要(仅该席位可见事件)
- dm-only: 主席团全量摘要

触发: 纪元机制——某视角 L3 累积超过阈值时, 书记将旧摘要+新事件压缩进新版摘要.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from munagent.agents.base import AgentContext, BaseAgent, TaskSpec
from munagent.core.events import Event
from munagent.core.render import render
from munagent.llm.client import LLMClient

# 送入 LLM 的输入预算(防 prompt 过长); 输出侧由 max_tokens 控制
SUMMARIZE_MAX_INPUT_TOKENS = 12_000
SUMMARIZE_MAX_SPEECH_CHARS = 400
SUMMARIZE_MAX_OLD_SUMMARY_CHARS = 4_000


class SummaryResult(BaseModel):
    text: str


G_RECORDER = """你是模拟联合国危机联动推演的会议书记. 职责:
- 将近期事件压缩为编年体摘要.
- 保留: 立场表态、承诺与背弃、指令及结果、投票结果、关键危机更新.
- 丢弃: 寒暄、重复表态、无关细节.
- 按故事时间排列, 简明扼要.
在```json代码块中输出: {"text": "摘要正文"}
"""


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数: 中文约 1 字 = 1.5 token, 英文约 1 词 = 1.3 token."""
    chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    other_chars = len(text) - chinese_chars
    return int(chinese_chars * 1.5 + other_chars * 0.4)


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def render_for_summarize(event: Event, *, max_text_chars: int = SUMMARIZE_MAX_SPEECH_CHARS) -> str:
    """摘要专用渲染: 截断过长发言/盘算, 降低 Recorder 输入与输出压力."""
    line = render(event)
    if event.type not in ("speech", "speech_thought"):
        return line
    payload = event.payload
    key = "text" if event.type == "speech" else "thought"
    raw = payload.get(key, "")
    if len(raw) <= max_text_chars:
        return line
    short = _truncate_text(raw, max_text_chars)
    return line.replace(raw, short, 1)


def _trim_old_summary(old_summary: str) -> str:
    if not old_summary:
        return "(无)"
    if len(old_summary) <= SUMMARIZE_MAX_OLD_SUMMARY_CHARS:
        return old_summary
    head = old_summary[: SUMMARIZE_MAX_OLD_SUMMARY_CHARS // 2]
    tail = old_summary[-SUMMARIZE_MAX_OLD_SUMMARY_CHARS // 2 :]
    return f"{head}\n...(旧摘要过长, 中部省略)...\n{tail}"


def _trim_events_for_input(events: list[Event], budget_tokens: int) -> list[Event]:
    """在 token 预算内保留尽可能多的近期事件(优先丢最旧)."""
    if not events:
        return events
    kept: list[Event] = []
    for e in reversed(events):
        trial = list(reversed([e, *kept]))
        text = "\n".join(render_for_summarize(ev) for ev in trial)
        if estimate_tokens(text) > budget_tokens and kept:
            break
        kept.insert(0, e)
    if not kept:
        return events[-1:]
    if len(kept) < len(events):
        # 书记仍能看到被省略的事件数量, 避免静默丢信息
        kept.insert(
            0,
            Event(
                session_id=events[0].session_id,
                story_time=events[0].story_time,
                type="session_control",
                actor="system",
                scope="dm-only",
                payload={
                    "action": "summarize_trim",
                    "detail": f"本期 {len(events) - len(kept)} 条较早事件已省略细节, 仅保留近期条目",
                },
            ),
        )
    return kept


def build_summarize_prompt(
    old_summary: str,
    new_events: list[Event],
    level: Literal["venue", "private", "dm-only"],
) -> tuple[str, list[Event]]:
    """组装 L4 任务段, 并在输入 token 预算内裁剪事件."""
    level_desc = {
        "venue": "会场公开记录",
        "private": "该席位私人记忆(含内心盘算)",
        "dm-only": "主席团全量记录(含判定细节)",
    }
    trimmed_old = _trim_old_summary(old_summary)
    events_for_prompt = _trim_events_for_input(
        new_events,
        SUMMARIZE_MAX_INPUT_TOKENS - estimate_tokens(trimmed_old) - 200,
    )
    events_text = "\n".join(render_for_summarize(e) for e in events_for_prompt) or "(无新事件)"
    l4 = (
        f"摘要层级: {level_desc.get(level, level)}\n"
        f"<旧摘要>\n{trimmed_old}\n</旧摘要>\n"
        f"<本期新事件>\n{events_text}\n</本期新事件>\n"
        f"将以上内容合并为一份新的编年体摘要. "
        f"保留立场表态、承诺与背弃、指令及结果、投票结果、关键危机更新. "
        f"丢弃寒暄与重复. 在```json中输出: "
        '{"text": "新摘要正文"}'
    )
    return l4, events_for_prompt


class RecorderAgent(BaseAgent):
    """书记 Agent: 生成滚动摘要. 见 05§3.4."""

    def __init__(self, llm: LLMClient) -> None:
        super().__init__(llm, max_tokens=16384)

    async def summarize(
        self,
        task: TaskSpec,
        old_summary: str,
        new_events: list[Event],
        level: Literal["venue", "private", "dm-only"] = "venue",
    ) -> str:
        """将旧摘要 + 新事件压缩为新摘要."""
        l4, _ = build_summarize_prompt(old_summary, new_events, level)
        ctx = self.build_context(
            task, g=G_RECORDER, l1="你是会议书记.", l2="", l3="", l4=l4
        )
        result = await self.act(task, ctx, schema_model=SummaryResult)
        if isinstance(result, SummaryResult):
            return result.text
        return old_summary  # fallback: 保留旧摘要
