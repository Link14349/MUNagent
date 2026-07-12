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


class RecorderAgent(BaseAgent):
    """书记 Agent: 生成滚动摘要. 见 05§3.4."""

    def __init__(self, llm: LLMClient) -> None:
        super().__init__(llm, max_tokens=2048)

    async def summarize(
        self,
        task: TaskSpec,
        old_summary: str,
        new_events: list[Event],
        level: Literal["venue", "private", "dm-only"] = "venue",
    ) -> str:
        """将旧摘要 + 新事件压缩为新摘要."""
        events_text = "\n".join(render(e) for e in new_events) or "(无新事件)"
        level_desc = {
            "venue": "会场公开记录",
            "private": "该席位私人记忆(含内心盘算)",
            "dm-only": "主席团全量记录(含判定细节)",
        }

        l4 = (
            f"摘要层级: {level_desc.get(level, level)}\n"
            f"<旧摘要>\n{old_summary or '(无)'}\n</旧摘要>\n"
            f"<本期新事件>\n{events_text}\n</本期新事件>\n"
            f"将以上内容合并为一份新的编年体摘要. "
            f"保留立场表态、承诺与背弃、指令及结果、投票结果、关键危机更新. "
            f"丢弃寒暄与重复. 在```json中输出: "
            '{"text": "新摘要正文"}'
        )
        ctx = self.build_context(
            task, g=G_RECORDER, l1="你是会议书记.", l2="", l3="", l4=l4
        )
        result = await self.act(task, ctx, schema_model=SummaryResult)
        if isinstance(result, SummaryResult):
            return result.text
        return old_summary  # fallback: 保留旧摘要
