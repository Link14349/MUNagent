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


class ClockDecisionAction(BaseModel):
    """危机更新后的跳时决策: advance_to为空=不跳时(小步自然推进)."""

    advance_to: str = ""  # 目标故事时间(ISO带时区), 不得早于当前, 不得跳过在途生效点
    reason: str = ""


class AppealRulingAction(BaseModel):
    ruling: Literal["sustain", "overrule"]  # sustain=维持主持裁决, overrule=推翻
    reason: str = ""


class MotionRulingAction(BaseModel):
    ruling: Literal["accept", "reject"]
    reason: str = ""


G_CHAIR = """你是模拟联合国危机推演的戏外会议主席(中立). 职责:
- 游戏层: 点名(无主持席时)、阶段决策、Crisis Update 播报、时间推进、预算控制.
- 申诉终裁: 代表动议 appeal 申诉主持席裁决时, 由你中立终裁.
- 你没有戏内立场, 不偏袒任何代表.
- 播报文风: 新闻简报体, 克制客观准确——只陈述事实, 不渲染气氛, 不替任何代表编写台词或行动.
- 时间推进: 每次危机更新后, 由你决定故事时间推进到哪个节点——会场空转时跳向下一个压力节点,
  重大转折后小步推进给代表反应空间; 永不回拨, 不跳过在途行动的生效点.
在```json代码块中按指定 schema 输出.
"""


def build_chair_g(scenario) -> str:
    """主席G段: 职责 + 剧情走向设计 + 时间线(主席团专用, 会话内稳定)."""
    from munagent.agents.dm import format_timeline

    parts = [G_CHAIR.rstrip()]
    story_design = getattr(scenario, "story_design", "")
    if story_design.strip():
        parts.append(f"## 剧情走向与时间线设计(导航图, 不是剧本)\n\n{story_design.strip()}")
    tl = format_timeline(scenario)
    if tl:
        parts.append(tl)
    return "\n\n".join(parts)


L1_CHAIR = "你是戏外中立会议主席."


class ChairAgent(BaseAgent):
    """戏外中立主席 Agent. 见 05§3.2.

    有 presiding_seat 的会场, next_speaker/motion_ruling 路由给主持席;
    ChairAgent 保留 phase_decision/broadcast_decision/appeal_ruling.
    """

    def __init__(self, llm: LLMClient, venue_id: str, seat_ids: list[str], g_chair: str = G_CHAIR) -> None:
        super().__init__(llm, max_tokens=4096)
        self.venue_id = venue_id
        self.seat_ids = seat_ids
        self._g = g_chair

    async def next_speaker(
        self,
        task: TaskSpec,
        visible_events: list[Event],
        phase: str,
        story_time: str,
        spoken_seats: list[str],
    ) -> NextSpeakerAction:
        l3 = "\n".join(render(e) for e in visible_events) or "(无近期事件)"
        l4 = (
            f"当前阶段: {phase}\n故事时间: {story_time}\n"
            f"会场席位: {', '.join(self.seat_ids)}\n"
            f"本轮已发言: {', '.join(spoken_seats) or '无'}\n"
            f"选择下一位发言的代表. 在```json中输出: "
            '{"seat": "席位id", "reason": "简短理由"}'
        )
        ctx = self.build_context(
            task, g=self._g, l1=L1_CHAIR, l2="", l3=l3, l4=l4
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
        l3 = "\n".join(render(e) for e in visible_events) or "(无近期事件)"
        l4 = (
            f"故事时间: {story_time}\n"
            f"收到动议: {motion_text}\n"
            f"作为中立主席, 裁决受理(accept)还是驳回(reject). 在```json中输出: "
            '{"ruling": "accept|reject", "reason": "理由"}'
        )
        ctx = self.build_context(
            task, g=self._g, l1=L1_CHAIR, l2="", l3=l3, l4=l4
        )
        result = await self.act(task, ctx, schema_model=MotionRulingAction)
        if isinstance(result, MotionRulingAction):
            return result
        return MotionRulingAction(ruling="reject", reason="fallback: 保守驳回(可appeal)")

    async def phase_decision(
        self,
        task: TaskSpec,
        visible_events: list[Event],
        phase: str,
        story_time: str,
        speech_count: int,
        max_speeches: int,
        directives_submitted: int = -1,
    ) -> PhaseDecisionAction:
        l3 = "\n".join(render(e) for e in visible_events) or "(无近期事件)"
        progress_hint = ""
        if directives_submitted >= 0:
            progress_hint = f"本场已提交指令数: {directives_submitted}\n"
            if directives_submitted == 0:
                progress_hint += (
                    "注意: 会场讨论至今没有产出任何指令. 若你判断代表间已形成共识却无人落笔, "
                    "应在 announcement 中**公开催办**——点名请最接近共识文本的代表把共识写成联合指令提交, "
                    "并提醒提交后即可动议表决. 会议的产出是指令, 不是发言记录.\n"
                )
        l4 = (
            f"当前阶段: {phase}\n故事时间: {story_time}\n"
            f"本轮已发言次数: {speech_count}/{max_speeches}\n"
            f"{progress_hint}"
            f"决定下一步: keep(继续当前阶段) / switch(切换磋商形式, to_phase填ModeratedCaucus或UnmoderatedCaucus) / adjourn(闭会). "
            f"announcement 是你当众宣布的话(催办、程序说明等), keep 时同样会向全场播报. "
            f"在```json中输出: "
            '{"action": "keep|switch|adjourn", "to_phase": "目标阶段", "announcement": "当众宣布的话"}'
        )
        ctx = self.build_context(
            task, g=self._g, l1=L1_CHAIR, l2="", l3=l3, l4=l4
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
            task, g=self._g, l1=L1_CHAIR, l2="", l3="", l4=l4
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
        l3 = "\n".join(render(e) for e in visible_events) or "(无近期事件)"
        l4 = (
            f"故事时间: {story_time}\n"
            f"代表动议申诉: {motion_text}\n"
            f"被申诉的主持裁决: {original_ruling}\n"
            f"你作为戏外中立主席, 终裁是维持(sustain)还是推翻(overrule). "
            f"在```json中输出: "
            '{"ruling": "sustain|overrule", "reason": "理由"}'
        )
        ctx = self.build_context(
            task, g=self._g, l1=L1_CHAIR, l2="", l3=l3, l4=l4
        )
        result = await self.act(task, ctx, schema_model=AppealRulingAction)
        if isinstance(result, AppealRulingAction):
            return result
        return AppealRulingAction(ruling="sustain", reason="fallback: 维持原裁决")

    async def clock_decision(
        self,
        task: TaskSpec,
        story_time: str,
        crisis_text: str,
        pending_effects: str = "",
    ) -> ClockDecisionAction:
        """危机更新后的跳时决策. 见 04§5."""
        pending_part = f"在途行动生效点(不得跳过):\n{pending_effects}\n" if pending_effects else ""
        l4 = (
            f"当前故事时间: {story_time}\n"
            f"刚播报的危机更新:\n{crisis_text}\n"
            f"{pending_part}"
            f"决定故事时间是否向前推进: 参考系统消息中的时间线节点与跳时指引——"
            f"会场空转跳向下一个压力节点, 重大转折后小步推进(或不跳). "
            f"在```json中输出: "
            '{"advance_to": "目标时间ISO格式带时区(不跳时则留空)", "reason": "一句话理由"}'
        )
        ctx = self.build_context(task, g=self._g, l1=L1_CHAIR, l2="", l3="", l4=l4)
        result = await self.act(task, ctx, schema_model=ClockDecisionAction)
        if isinstance(result, ClockDecisionAction):
            return result
        return ClockDecisionAction()
