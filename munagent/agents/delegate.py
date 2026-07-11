"""代表 Agent 最小版. 见 05§3.1."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from munagent.agents.base import AgentContext, BaseAgent, TaskSpec
from munagent.core.events import Event
from munagent.core.render import render
from munagent.core.scenario import SeatSpec
from munagent.llm.client import LLMClient


class DirectiveDraft(BaseModel):
    kind: Literal["personal", "crisis_note"] = "personal"
    title: str = ""
    body: str = ""
    uses_powers: list[str] = Field(default_factory=list)
    recipient: str | None = None


class DelegateTurnAction(BaseModel):
    """代表 turn 任务输出 schema. 见 05§3.1."""

    action: Literal["speech", "motion", "write_directive", "pass"]
    text: str = ""
    inner_thought: str = ""
    directive: DirectiveDraft | None = None
    next_move: dict | None = None  # Unmod 末轮用, P1 不用


HONESTY_MAP = [
    (0.8, "你几乎从不说谎, 但可以选择沉默或回避."),
    (0.5, "你可以策略性地隐瞒与误导, 但不会直接违背公开承诺."),
    (0.2, "你可以为达成秘密目标而说谎、开空头支票."),
    (0.0, "你毫无信义可言, 背刺与欺骗是你的常规手段."),
]


def honesty_description(h: float) -> str:
    for threshold, desc in HONESTY_MAP:
        if h >= threshold:
            return desc
    return HONESTY_MAP[-1][1]


# G 段: 所有代表共享
G_GLOBAL = """你正在参加一场模拟联合国历史危机推演. 以下是会议通用规则:
- 发言应简明扼要, 体现角色立场.
- 可选行动: speech(发言)、write_directive(写指令)、pass(跳过).
- 指令类型: personal(个人指令, 凭权力清单行动)、crisis_note(危机笔记, 私信).
- 在```json代码块中按 schema 输出, 包含 action、text、inner_thought 字段.
- inner_thought 是你的内心盘算, 其他角色看不到, 供你自己保持连贯.
"""


class DelegateAgent(BaseAgent):
    """代表 Agent: 扮演某席位, 在点名时行动."""

    def __init__(self, llm: LLMClient, seat: SeatSpec, background_summary: str) -> None:
        super().__init__(llm, schema_model=DelegateTurnAction, max_tokens=512)
        self.seat = seat
        self.background_summary = background_summary

    @property
    def viewer(self) -> str:
        return f"seat:{self.seat.id}"

    def build_l1(self) -> str:
        s = self.seat
        return (
            f"你扮演: {s.name}({s.public.title}), 属于{s.public.faction}.\n"
            f"<人格卡>性格: {s.persona.personality}; 说话风格: {s.persona.speech_style}; "
            f"决策倾向: {s.persona.decision_tendency}; 诚信: {honesty_description(s.persona.honesty)}</人格卡>\n"
            f"<你的秘密信息>目标: {'; '.join(s.private.secret_goals)}</你的秘密信息>\n"
            f"<你的权力清单>{'; '.join(p.power for p in s.portfolio_powers)}</你的权力清单>\n"
            f"<背景>{self.background_summary}</背景>"
        )

    def build_turn_context(
        self,
        task: TaskSpec,
        visible_events: list[Event],
        phase: str,
        story_time: str,
    ) -> AgentContext:
        l3 = "\n".join(render(e) for e in visible_events[-20:]) or "(无近期事件)"
        l4 = (
            f"当前阶段: {phase}\n"
            f"故事时间: {story_time}\n"
            f"现在轮到你({self.seat.name})行动. "
            f"以既定人格做出对你的目标最有利的选择.\n"
            f"在```json中按以下schema输出:\n"
            '{"action": "speech|write_directive|pass", "text": "发言内容", '
            '"inner_thought": "内心盘算", "directive": {"kind":"personal", "title":"", "body":"", "uses_powers":[]}}'
        )
        return self.build_context(
            task,
            g=G_GLOBAL,
            l1=self.build_l1(),
            l2="(P1 摘要尚未实现)",
            l3=l3,
            l4=l4,
        )
