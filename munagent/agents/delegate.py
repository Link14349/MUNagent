"""代表 Agent. 见 05§3.1.

支持两类任务:
- 代表行动: turn(发言/动议/写指令/pass)、vote、express_grouping、quick_decide
- 主持类(带*): next_speaker、motion_ruling、caucus_switch — 仅当席位为 presiding_seat 时启用
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from munagent.agents.base import AgentContext, BaseAgent, TaskSpec
from munagent.core.events import Event
from munagent.core.render import render
from munagent.core.scenario import SeatSpec
from munagent.llm.client import LLMClient


# --- 输出 schema ---

class DirectiveDraft(BaseModel):
    kind: Literal["personal", "crisis_note", "directive", "communique"] = "personal"
    title: str = ""
    body: str = ""
    uses_powers: list[str] = Field(default_factory=list)
    recipient: str | None = None
    co_sponsors: list[str] = Field(default_factory=list)


class NextMove(BaseModel):
    type: Literal["stay", "join", "new_group", "solo"] = "stay"
    target: str | None = None
    members: list[str] = Field(default_factory=list)
    closed: bool = False


class DelegateTurnAction(BaseModel):
    """代表 turn 任务输出 schema. 见 05§3.1."""

    action: Literal["speech", "motion", "write_directive", "pass"]
    text: str = ""
    inner_thought: str = ""
    directive: DirectiveDraft | None = None
    motion_type: str = ""  # 切磋商/表决指令/appeal申诉
    motion_target: str = ""  # 表决对象(指令id) 或切磋商目标
    next_move: NextMove | None = None  # Unmod 末轮用


class DelegateVoteAction(BaseModel):
    choice: Literal["aye", "nay", "abstain"]
    inner_thought: str = ""


# 主持类任务 schema(与 ChairAgent 同名任务一致, 但带 inner_thought)
class PresidingNextSpeaker(BaseModel):
    seat: str
    reason: str = ""
    inner_thought: str = ""


class PresidingMotionRuling(BaseModel):
    ruling: Literal["accept", "reject"]
    reason: str = ""
    inner_thought: str = ""


class PresidingCaucusSwitch(BaseModel):
    action: Literal["keep", "switch"]
    to_phase: str = ""
    announcement: str = ""
    inner_thought: str = ""


# --- 诚信映射 ---

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


G_GLOBAL = """你正在参加一场模拟联合国历史危机推演. 以下是会议通用规则:
- 发言应简明扼要, 体现角色立场.
- 可选行动: speech(发言)、motion(动议)、write_directive(写指令)、pass(跳过).
- 动议类型: caucus_switch(切磋商形式)、vote_directive(表决指令)、appeal(申诉主持裁决).
- 指令类型: personal(个人指令)、crisis_note(危机笔记)、directive(联合指令)、communique(公报).
- 在```json代码块中按 schema 输出, 包含 action、text、inner_thought 字段.
- inner_thought 是你的内心盘算, 其他角色看不到, 供你自己保持连贯.
"""


class DelegateAgent(BaseAgent):
    """代表 Agent: 扮演某席位, 在点名时行动; 任主持席时兼做程序性主持."""

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

    def _build_ctx(self, task: TaskSpec, l3: str, l4: str) -> AgentContext:
        return self.build_context(
            task,
            g=G_GLOBAL,
            l1=self.build_l1(),
            l2="(摘要尚未实现)",
            l3=l3,
            l4=l4,
        )

    # --- 代表行动任务 ---

    def build_turn_context(
        self,
        task: TaskSpec,
        visible_events: list[Event],
        phase: str,
        story_time: str,
        is_presiding: bool = False,
    ) -> AgentContext:
        l3 = "\n".join(render(e) for e in visible_events[-20:]) or "(无近期事件)"
        presiding_hint = (
            "\n你同时是本会场的主持者, 可以利用程序性权力偏心(不点政敌、拖延不利议程)."
            if is_presiding
            else ""
        )
        l4 = (
            f"当前阶段: {phase}\n"
            f"故事时间: {story_time}\n"
            f"现在轮到你({self.seat.name})行动.{presiding_hint}\n"
            f"以既定人格做出对你的目标最有利的选择.\n"
            f"在```json中按以下schema输出:\n"
            '{"action": "speech|motion|write_directive|pass", "text": "发言内容", '
            '"inner_thought": "内心盘算", "motion_type": "caucus_switch|vote_directive|appeal", '
            '"motion_target": "目标", "directive": {"kind":"personal","title":"","body":"","uses_powers":[]}}'
        )
        return self._build_ctx(task, l3, l4)

    def build_vote_context(
        self,
        task: TaskSpec,
        visible_events: list[Event],
        directive_title: str,
        story_time: str,
    ) -> AgentContext:
        l3 = "\n".join(render(e) for e in visible_events[-10:]) or "(无近期事件)"
        l4 = (
            f"故事时间: {story_time}\n"
            f"正在表决指令: {directive_title}\n"
            f"以既定人格投票. 在```json中输出: "
            '{"choice": "aye|nay|abstain", "inner_thought": "内心盘算"}'
        )
        return self._build_ctx(task, l3, l4)

    # --- 主持类任务(带*) ---

    async def presiding_next_speaker(
        self,
        task: TaskSpec,
        visible_events: list[Event],
        phase: str,
        story_time: str,
        spoken_seats: list[str],
        all_seat_ids: list[str],
    ) -> PresidingNextSpeaker:
        l3 = "\n".join(render(e) for e in visible_events[-15:]) or "(无近期事件)"
        l4 = (
            f"当前阶段: {phase}\n故事时间: {story_time}\n"
            f"你是本会场主持者({self.seat.name}). "
            f"会场席位: {', '.join(all_seat_ids)}\n"
            f"本轮已发言: {', '.join(spoken_seats) or '无'}\n"
            f"以你的立场选择下一位发言者(可以偏心). 在```json中输出: "
            '{"seat": "席位id", "reason": "理由", "inner_thought": "你的盘算"}'
        )
        ctx = self._build_ctx(task, l3, l4)
        self._schema_model = PresidingNextSpeaker
        result = await self.act(task, ctx)
        if isinstance(result, PresidingNextSpeaker):
            return result
        # fallback: 保底轮询
        for sid in all_seat_ids:
            if sid not in spoken_seats:
                return PresidingNextSpeaker(seat=sid, reason="保底轮询")
        return PresidingNextSpeaker(seat=all_seat_ids[0], reason="重新轮询")

    async def presiding_motion_ruling(
        self,
        task: TaskSpec,
        visible_events: list[Event],
        motion_text: str,
        story_time: str,
    ) -> PresidingMotionRuling:
        l3 = "\n".join(render(e) for e in visible_events[-10:]) or "(无近期事件)"
        l4 = (
            f"故事时间: {story_time}\n"
            f"你是本会场主持者({self.seat.name}).\n"
            f"收到动议: {motion_text}\n"
            f"以你的立场裁决(受理或驳回, 可以偏心). 在```json中输出: "
            '{"ruling": "accept|reject", "reason": "理由", "inner_thought": "你的盘算"}'
        )
        ctx = self._build_ctx(task, l3, l4)
        self._schema_model = PresidingMotionRuling
        result = await self.act(task, ctx)
        if isinstance(result, PresidingMotionRuling):
            return result
        return PresidingMotionRuling(ruling="reject", reason="fallback")

    async def presiding_caucus_switch(
        self,
        task: TaskSpec,
        visible_events: list[Event],
        phase: str,
        story_time: str,
    ) -> PresidingCaucusSwitch:
        l3 = "\n".join(render(e) for e in visible_events[-15:]) or "(无近期事件)"
        l4 = (
            f"当前阶段: {phase}\n故事时间: {story_time}\n"
            f"你是本会场主持者({self.seat.name}). "
            f"决定是否切换磋商形式(Mod⇄Unmod)或保持当前. 在```json中输出: "
            '{"action": "keep|switch", "to_phase": "ModeratedCaucus|UnmoderatedCaucus", '
            '"announcement": "宣布内容", "inner_thought": "你的盘算"}'
        )
        ctx = self._build_ctx(task, l3, l4)
        self._schema_model = PresidingCaucusSwitch
        result = await self.act(task, ctx)
        if isinstance(result, PresidingCaucusSwitch):
            return result
        return PresidingCaucusSwitch(action="keep")
