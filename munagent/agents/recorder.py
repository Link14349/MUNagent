"""书记 Agent: 章节追加摘要. 见 05§3.4.

三层摘要:
- venue: 会场公开记录摘要(全体可见事件)
- private: 每席位私人记忆摘要(仅该席位可见事件)
- dm-only: 主席团全量摘要

模型(章节追加, 非滚动重写):
- 每纪元只把本期新事件压缩为**一章**, 程序追加到该视角的章节列表尾部——旧章节
  不经LLM之手, 杜绝"合并时静默丢失早期记忆"; L2只从尾部生长, 缓存前缀更稳;
- 章节总量超阈值时做一次低频**合并**(squash): 全部章节压成一章, 明确要求覆盖
  全部时间范围.
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


class SummaryResult(BaseModel):
    text: str


JSON_TEXT_OUTPUT_RULES = """## JSON 输出纪律
- 只输出一个 ```json 代码块, 不要附加说明文字.
- 键名与字符串值的**边界引号**必须是半角 ASCII 双引号 (键盘 Shift+'), 即 " 而不是弯引号 "" 或全角 ＂.
- 摘要正文里引述用语请用单引号 '…' 或「…」, 不要用弯双引号作为 JSON 的闭合引号.
- 段落之间用 \\n 连接, 不要在 JSON 字符串里写裸换行.
示例: {"text": "09:00 外长发言。\\n09:05 防长回应。"}
"""


G_RECORDER = f"""你是模拟联合国危机联动推演的会议书记. 职责:
- 将近期事件压缩为编年体摘要.
- 保留: 立场表态、承诺与背弃、指令及结果、投票结果、关键危机更新.
- 丢弃: 寒暄、重复表态、无关细节.
- 按故事时间排列, 简明扼要.
{JSON_TEXT_OUTPUT_RULES}
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


_LEVEL_DESC = {
    "venue": "会场公开记录",
    "private": "该席位私人记忆(含内心盘算)",
    "dm-only": "主席团全量记录(含判定细节)",
}


def build_chapter_prompt(
    new_events: list[Event],
    level: Literal["venue", "private", "dm-only"],
) -> tuple[str, list[Event]]:
    """摘章 L4: 只压缩本期新事件为一章(旧章节不经LLM之手, 由程序拼接)."""
    events_for_prompt = _trim_events_for_input(
        new_events, SUMMARIZE_MAX_INPUT_TOKENS - 200,
    )
    events_text = "\n".join(render_for_summarize(e) for e in events_for_prompt) or "(无新事件)"
    l4 = (
        f"摘要层级: {_LEVEL_DESC.get(level, level)}\n"
        f"<本期新事件>\n{events_text}\n</本期新事件>\n"
        f"将本期新事件压缩为一章编年体摘要(只写本期, 不要虚构此前的内容). "
        f"保留立场表态、承诺与背弃、指令及结果、投票结果、关键危机更新. "
        f"丢弃寒暄与重复. 在```json中输出, 边界引号必须用 ASCII 双引号: "
        '{"text": "本章摘要正文"}'
    )
    return l4, events_for_prompt


def build_consolidate_prompt(
    chapters: list[str],
    level: Literal["venue", "private", "dm-only"],
) -> str:
    """合并 L4: 全部章节压成一章(低频squash), 必须覆盖全部时间范围."""
    joined = "\n\n".join(
        f"<第{i}章>\n{c}\n</第{i}章>" for i, c in enumerate(chapters, 1)
    )
    return (
        f"摘要层级: {_LEVEL_DESC.get(level, level)}\n"
        f"{joined}\n"
        f"将以上全部章节合并压缩为一份更精炼的编年体摘要. "
        f"**必须覆盖全部章节的时间范围, 从最早记录开始**——只输出后期内容视为错误. "
        f"保留立场表态、承诺与背弃、指令及结果、投票结果、关键危机更新. "
        f"在```json中输出, 边界引号必须用 ASCII 双引号: "
        '{"text": "合并后的摘要正文"}'
    )


class RecorderAgent(BaseAgent):
    """书记 Agent: 章节追加摘要. 见 05§3.4."""

    def __init__(self, llm: LLMClient) -> None:
        super().__init__(llm, max_tokens=16384)

    async def summarize_chapter(
        self,
        task: TaskSpec,
        new_events: list[Event],
        level: Literal["venue", "private", "dm-only"] = "venue",
    ) -> str:
        """本期新事件 → 一章摘要(追加到章节列表由引擎负责)."""
        l4, _ = build_chapter_prompt(new_events, level)
        ctx = self.build_context(
            task, g=G_RECORDER, l1="你是会议书记.", l2="", l3="", l4=l4
        )
        result = await self.act(task, ctx, schema_model=SummaryResult)
        if isinstance(result, SummaryResult):
            return result.text
        return ""  # fallback: 本章缺失, 旧章节不受影响

    async def consolidate(
        self,
        task: TaskSpec,
        chapters: list[str],
        level: Literal["venue", "private", "dm-only"] = "venue",
    ) -> str:
        """低频squash: 全部章节合并为一章; 失败时保留原章节拼接."""
        l4 = build_consolidate_prompt(chapters, level)
        ctx = self.build_context(
            task, g=G_RECORDER, l1="你是会议书记.", l2="", l3="", l4=l4
        )
        result = await self.act(task, ctx, schema_model=SummaryResult)
        if isinstance(result, SummaryResult) and result.text.strip():
            return result.text
        return "\n\n".join(chapters)
