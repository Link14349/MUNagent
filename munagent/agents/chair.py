"""主席 Agent 最小版. 见 05§3.2."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from munagent.agents.base import AgentContext, BaseAgent, TaskSpec
from munagent.core.events import Event
from munagent.core.render import render
from munagent.llm.client import LLMClient


class NextSpeakerAction(BaseModel):
    seat: str
    reason: str = ""


class PhaseDecisionAction(BaseModel):
    action: Literal["keep", "switch", "adjourn"]
    to_phase: str | None = None
    announcement: str = ""


class BroadcastDecisionAction(BaseModel):
    plan: list[dict] = []  # [{venue, text}]
    withhold: list[str] = []


class AppealRulingAction(BaseModel):
    ruling: Literal["sustain", "overrule"]  # sustain=维持主持裁决, overrule=推翻
    reason: str = ""


class MotionRulingAction(BaseModel):
    ruling: Literal["accept", "reject"]
    reason: str = ""


G_CHAIR = """你是模拟联合国危机推演的戏外会议主席(中立). 职责:
- 游戏层: 点名(无主持席时)、阶段决策、Crisis Update 播报、预算控制.
- 申诉终裁: 代表动议 appeal 申诉主持席裁决时, 由你中立终裁.
- 你没有戏内立场, 不偏袒任何代表.
在```json代码块中按指定 schema 输出.
"""


class ChairAgent(BaseAgent):
    """戏外中立主席 Agent. 见 05§3.2.

    有 presiding_seat 的会场, next_speaker/motion_ruling 路由给主持席;
    ChairAgent 保留 phase_decision/broadcast_decision/appeal_ruling.
    """

    def __init__(self, llm: LLMClient, venue_id: str, seat_ids: list[str]) -> None:
        super().__init__(llm, max_tokens=512)
        self.venue_id = venue_id
        self.seat_ids = seat_ids

    async def next_speaker(
        self,
        task: TaskSpec,
        visible_events: list[Event],
        phase: str,
        story_time: str,
        spoken_seats: list[str],
    ) -> NextSpeakerAction:
        l3 = "\n".join(render(e) for e in visible_events[-15:]) or "(无近期事件)"
        l4 = (
            f"当前阶段: {phase}\n故事时间: {story_time}\n"
            f"会场席位: {', '.join(self.seat_ids)}\n"
            f"本轮已发言: {', '.join(spoken_seats) or '无'}\n"
            f"选择下一位发言的代表. 在```json中输出: "
            '{"seat": "席位id", "reason": "简短理由"}'
        )
        ctx = self.build_context(
            task, g=G_CHAIR, l1="你是会议主席.", l2="", l3=l3, l4=l4
        )
        result = await self.act(task, ctx, schema_model=NextSpeakerAction)
        if isinstance(result, NextSpeakerAction):
            return result
        for sid in self.seat_ids:
            if sid not in spoken_seats:
                return NextSpeakerAction(seat=sid, reason="保底轮询")
        return NextSpeakerAction(seat=self.seat_ids[0], reason="重新轮询")

    async def motion_ruling(
        self,
        task: TaskSpec,
        visible_events: list[Event],
        motion_text: str,
        story_time: str,
    ) -> MotionRulingAction:
        """动议裁决(无主持席的会场). 见 05§3.2."""
        l3 = "\n".join(render(e) for e in visible_events[-10:]) or "(无近期事件)"
        l4 = (
            f"故事时间: {story_time}\n"
            f"收到动议: {motion_text}\n"
            f"作为中立主席, 裁决受理(accept)还是驳回(reject). 在```json中输出: "
            '{"ruling": "accept|reject", "reason": "理由"}'
        )
        ctx = self.build_context(
            task, g=G_CHAIR, l1="你是戏外中立会议主席.", l2="", l3=l3, l4=l4
        )
        result = await self.act(task, ctx, schema_model=MotionRulingAction)
        if isinstance(result, MotionRulingAction):
            return result
        return MotionRulingAction(ruling="accept", reason="fallback")

    async def phase_decision(
        self,
        task: TaskSpec,
        visible_events: list[Event],
        phase: str,
        story_time: str,
        speech_count: int,
        max_speeches: int,
    ) -> PhaseDecisionAction:
        l3 = "\n".join(render(e) for e in visible_events[-15:]) or "(无近期事件)"
        l4 = (
            f"当前阶段: {phase}\n故事时间: {story_time}\n"
            f"本轮已发言次数: {speech_count}/{max_speeches}\n"
            f"决定下一步: keep(继续当前阶段) / switch(切换到 ModeratedCaucus) / adjourn(闭会). "
            f"在```json中输出: "
            '{"action": "keep|switch|adjourn", "to_phase": "目标阶段", "announcement": "说明"}'
        )
        ctx = self.build_context(
            task, g=G_CHAIR, l1="你是会议主席.", l2="", l3=l3, l4=l4
        )
        result = await self.act(task, ctx, schema_model=PhaseDecisionAction)
        if isinstance(result, PhaseDecisionAction):
            return result
        return PhaseDecisionAction(action="keep")

    async def broadcast_decision(
        self,
        task: TaskSpec,
        adjudication_text: str,
        venue_ids: list[str],
    ) -> BroadcastDecisionAction:
        l4 = (
            f"DM 判定结果叙述:\n{adjudication_text}\n"
            f"决定如何向各会场({', '.join(venue_ids)})播报. "
            f"在```json中输出: "
            '{"plan": [{"venue": "会场id", "text": "播报文本"}], "withhold": []}'
        )
        ctx = self.build_context(
            task, g=G_CHAIR, l1="你是会议主席.", l2="", l3="", l4=l4
        )
        result = await self.act(task, ctx, schema_model=BroadcastDecisionAction)
        if isinstance(result, BroadcastDecisionAction):
            return result
        return BroadcastDecisionAction(
            plan=[{"venue": vid, "text": adjudication_text} for vid in venue_ids]
        )

    async def appeal_ruling(
        self,
        task: TaskSpec,
        visible_events: list[Event],
        motion_text: str,
        original_ruling: str,
        story_time: str,
    ) -> AppealRulingAction:
        """申诉终裁: 中立行使. 见 04§3, 05§3.2."""
        l3 = "\n".join(render(e) for e in visible_events[-10:]) or "(无近期事件)"
        l4 = (
            f"故事时间: {story_time}\n"
            f"代表动议申诉: {motion_text}\n"
            f"被申诉的主持裁决: {original_ruling}\n"
            f"你作为戏外中立主席, 终裁是维持(sustain)还是推翻(overrule). "
            f"在```json中输出: "
            '{"ruling": "sustain|overrule", "reason": "理由"}'
        )
        ctx = self.build_context(
            task, g=G_CHAIR, l1="你是戏外中立会议主席.", l2="", l3=l3, l4=l4
        )
        result = await self.act(task, ctx, schema_model=AppealRulingAction)
        if isinstance(result, AppealRulingAction):
            return result
        return AppealRulingAction(ruling="sustain", reason="fallback: 维持原裁决")
