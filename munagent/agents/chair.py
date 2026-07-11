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


G_CHAIR = """你是模拟联合国危机推演的会议主席. 职责:
- 点名让代表发言, 确保各席位都有机会表态.
- 控制会议节奏, 必要时切换阶段或宣布闭会.
- 在 DM 判定指令后, 决定如何向各会场播报.
在```json代码块中按指定 schema 输出.
"""


class ChairAgent(BaseAgent):
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
        self._schema_model = NextSpeakerAction
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
        result = await self.act(task, ctx)
        if isinstance(result, NextSpeakerAction):
            return result
        # fallback: 选第一个未发言的
        for sid in self.seat_ids:
            if sid not in spoken_seats:
                return NextSpeakerAction(seat=sid, reason="保底轮询")
        return NextSpeakerAction(seat=self.seat_ids[0], reason="重新轮询")

    async def phase_decision(
        self,
        task: TaskSpec,
        visible_events: list[Event],
        phase: str,
        story_time: str,
        speech_count: int,
        max_speeches: int,
    ) -> PhaseDecisionAction:
        self._schema_model = PhaseDecisionAction
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
        result = await self.act(task, ctx)
        if isinstance(result, PhaseDecisionAction):
            return result
        return PhaseDecisionAction(action="keep")

    async def broadcast_decision(
        self,
        task: TaskSpec,
        adjudication_text: str,
        venue_ids: list[str],
    ) -> BroadcastDecisionAction:
        self._schema_model = BroadcastDecisionAction
        l4 = (
            f"DM 判定结果叙述:\n{adjudication_text}\n"
            f"决定如何向各会场({', '.join(venue_ids)})播报. "
            f"在```json中输出: "
            '{"plan": [{"venue": "会场id", "text": "播报文本"}], "withhold": []}'
        )
        ctx = self.build_context(
            task, g=G_CHAIR, l1="你是会议主席.", l2="", l3="", l4=l4
        )
        result = await self.act(task, ctx)
        if isinstance(result, BroadcastDecisionAction):
            return result
        return BroadcastDecisionAction(
            plan=[{"venue": vid, "text": adjudication_text} for vid in venue_ids]
        )
