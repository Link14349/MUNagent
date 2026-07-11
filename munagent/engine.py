"""推演引擎(P1 最小版): 驱动单会场状态机 + 三 Agent 闭环.

P1 闭环: 点名发言 → (可选)个人指令 → DM 判定 → 主席播报 Crisis Update.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from munagent.agents.base import TaskSpec
from munagent.agents.chair import ChairAgent
from munagent.agents.delegate import DelegateAgent
from munagent.agents.dm import DMAgent, outcome_tier
from munagent.config.models import MunagentConfig
from munagent.core.bus import EventBus
from munagent.core.events import Event
from munagent.core.render import render
from munagent.core.scenario import Scenario
from munagent.core.state_machine import VenueStateMachine
from munagent.llm.client import LLMClient


@dataclass
class EngineEvent:
    """引擎向 CLI 输出的彩色事件行."""

    text: str
    color: str = "white"


ANSI_COLORS = {
    "white": "\033[97m",
    "green": "\033[92m",
    "yellow": "\033[93m",
    "red": "\033[91m",
    "cyan": "\033[96m",
    "magenta": "\033[95m",
    "dim": "\033[90m",
    "reset": "\033[0m",
}


def colorize(text: str, color: str) -> str:
    return f"{ANSI_COLORS.get(color, '')}{text}{ANSI_COLORS['reset']}"


@dataclass
class RunResult:
    session_id: str
    total_steps: int
    events: list[Event] = field(default_factory=list)


class Engine:
    """P1 推演引擎: 单会场 + 三 Agent 闭环."""

    def __init__(
        self,
        scenario: Scenario,
        config: MunagentConfig,
        *,
        master_seed: int | None = None,
        max_steps: int = 20,
        db_path: str = "munagent.db",
        usage_sink: Any = None,
        llm_transport: Any = None,
        on_event: Any = None,
    ) -> None:
        self.scenario = scenario
        self.config = config
        self.master_seed = master_seed if master_seed is not None else secrets.randbits(63)
        self.max_steps = max_steps
        self.db_path = db_path
        self.session_id = f"{scenario.id}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
        self._llm: LLMClient | None = None
        self._llm_transport = llm_transport
        self._usage_sink = usage_sink
        self._on_event = on_event

    def _emit_committed(self, events: list[Event]) -> None:
        """commit 后立即把新事件推给 on_event 回调(实时输出)."""
        if self._on_event is not None:
            for e in events:
                self._on_event(e)

    def _make_llm(self) -> LLMClient:
        if self._llm is None:
            kwargs: dict = {}
            if self._llm_transport is not None:
                kwargs["transport"] = self._llm_transport
            if self._usage_sink is not None:
                kwargs["usage_sink"] = self._usage_sink
            self._llm = LLMClient(self.config, **kwargs)
        return self._llm

    async def run(self) -> RunResult:
        """执行推演, 返回全部事件."""
        bus = EventBus(self.db_path, self.session_id)
        await bus.init_db()
        await bus.create_session(
            self.scenario.id,
            master_seed=self.master_seed,
            config={"max_steps": self.max_steps},
        )

        llm = self._make_llm()
        venue_spec = self.scenario.venues[0]
        seat_specs = self.scenario.seats_of(venue_spec.id)
        seat_ids = [s.id for s in seat_specs]

        sm = VenueStateMachine(
            venue_id=venue_spec.id,
            seat_ids=seat_ids,
            initial_phase=venue_spec.initial_phase,
            start_story_time=self.scenario.manifest.start_story_time,
            per_mod_speech=venue_spec.clock_rate.per_mod_speech,
            max_speeches=self.config.engine.mod_max_speeches,
        )

        delegates = {
            s.id: DelegateAgent(llm, s, self.scenario.background[:500])
            for s in seat_specs
        }
        chair = ChairAgent(llm, venue_spec.id, seat_ids)
        dm = DMAgent(llm, self.master_seed)

        all_events: list[Event] = []
        step = 0

        # Opening → ModeratedCaucus
        bus.stage(
            Event(
                session_id=self.session_id,
                story_time=sm.story_time,
                type="phase_change",
                actor="chair",
                venue_id=sm.venue_id,
                scope="venue",
                payload={"from": "Opening", "to": "ModeratedCaucus", "reason": "会议开始"},
            ),
            venue_seats=seat_ids,
        )
        committed = await bus.commit_step()
        self._emit_committed(committed)

        while step < self.max_steps and sm.phase != "Adjourned":
            step += 1

            # 1. 主席点名
            visible = await bus.query("chair", venue=sm.venue_id)
            speaker_task = TaskSpec(
                role="chair",
                task="next_speaker",
                phase=sm.phase,
                venue_id=sm.venue_id,
            )
            speaker_action = await chair.next_speaker(
                speaker_task, visible, sm.phase, sm.story_time, sm.spoken_this_phase
            )

            target_seat = speaker_action.seat
            # 保底轮询覆盖
            if sm.floor_rotation_due:
                forced = sm.next_for_floor_rotation()
                if forced:
                    target_seat = forced

            if target_seat not in delegates:
                target_seat = seat_ids[0]

            delegate = delegates[target_seat]

            # 2. 代表行动
            seat_viewer = f"seat:{target_seat}"
            delegate_visible = await bus.query(seat_viewer, venue=sm.venue_id)
            turn_task = TaskSpec(
                role="delegate",
                task="turn",
                phase=sm.phase,
                scope="venue",
                venue_id=sm.venue_id,
                seat_id=target_seat,
            )
            action = delegate.build_turn_context(
                turn_task, delegate_visible, sm.phase, sm.story_time
            )
            turn_result = await delegate.act(turn_task, action)

            # 3. 产生事件
            if turn_result.action == "speech" and turn_result.text:
                # speech 事件(venue 可见)
                speech_ev = bus.stage(
                    Event(
                        session_id=self.session_id,
                        story_time=sm.story_time,
                        type="speech",
                        actor=f"seat:{target_seat}",
                        venue_id=sm.venue_id,
                        scope="venue",
                        payload={"text": turn_result.text},
                    ),
                    venue_seats=seat_ids,
                )
                # speech_thought 事件(self 可见)
                if turn_result.inner_thought:
                    bus.stage(
                        Event(
                            session_id=self.session_id,
                            story_time=sm.story_time,
                            type="speech_thought",
                            actor=f"seat:{target_seat}",
                            venue_id=sm.venue_id,
                            scope="self",
                            payload={
                                "thought": turn_result.inner_thought,
                                "ref_seq": speech_ev.seq,
                            },
                        ),
                    )
                sm.record_speech(target_seat)

            elif turn_result.action == "write_directive" and turn_result.directive:
                d = turn_result.directive
                directive_id = f"d-{self.session_id}-{step}"
                bus.stage(
                    Event(
                        session_id=self.session_id,
                        story_time=sm.story_time,
                        type="directive_submitted",
                        actor=f"seat:{target_seat}",
                        venue_id=sm.venue_id,
                        scope="private",
                        payload={
                            "directive_id": directive_id,
                            "kind": d.kind,
                            "title": d.title,
                            "body": d.body,
                            "uses_powers": d.uses_powers,
                            "author": target_seat,
                        },
                    ),
                    private_recipients=[target_seat],
                )
                # 个人指令直接入后场判定(P1 简化: 立即判定)
                await self._adjudicate(
                    bus, dm, directive_id, d.title, d.body, sm, seat_ids
                )

            elif turn_result.action == "pass":
                sm.record_no_speech()

            # 推进时钟
            sm.advance_clock()
            bus.stage(
                Event(
                    session_id=self.session_id,
                    story_time=sm.story_time,
                    type="clock_advance",
                    actor="system",
                    venue_id=sm.venue_id,
                    scope="venue",
                    payload={"from": "", "to": sm.story_time},
                ),
                venue_seats=seat_ids,
            )

            committed = await bus.commit_step()
            all_events.extend(committed)
            self._emit_committed(committed)

            # 4. 阶段预算检查
            if sm.budget_exceeded:
                phase_task = TaskSpec(
                    role="chair",
                    task="phase_decision",
                    phase=sm.phase,
                    venue_id=sm.venue_id,
                )
                visible = await bus.query("chair", venue=sm.venue_id)
                decision = await chair.phase_decision(
                    phase_task,
                    visible,
                    sm.phase,
                    sm.story_time,
                    sm.mod_speech_count,
                    sm.max_speeches,
                )
                if decision.action == "adjourn":
                    sm.transition("Adjourned")
                    bus.stage(
                        Event(
                            session_id=self.session_id,
                            story_time=sm.story_time,
                            type="phase_change",
                            actor="chair",
                            venue_id=sm.venue_id,
                            scope="venue",
                            payload={
                                "from": "ModeratedCaucus",
                                "to": "Adjourned",
                                "reason": decision.announcement or "闭会",
                            },
                        ),
                        venue_seats=seat_ids,
                    )
                    final_committed = await bus.commit_step()
                    all_events.extend(final_committed)
                    self._emit_committed(final_committed)
                    break

        await bus.set_session_status("ended")
        all_committed = await bus.query("god")
        await bus.close()
        if self._llm is not None:
            await self._llm.aclose()
        return RunResult(
            session_id=self.session_id,
            total_steps=step,
            events=all_committed,
        )

    async def _adjudicate(
        self,
        bus: EventBus,
        dm: DMAgent,
        directive_id: str,
        title: str,
        body: str,
        sm: VenueStateMachine,
        seat_ids: list[str],
    ) -> None:
        """DM 判定流水线 ②④ + ③程序掷骰. 见 06§3."""
        directive_text = f"标题: {title}\n内容: {body}"
        context_summary = self.scenario.background[:300]

        # ② 可行性评估
        assess_task = TaskSpec(
            role="dm",
            task="adjudicate",
            phase=sm.phase,
            venue_id=sm.venue_id,
        )
        assessment = await dm.assess_feasibility(
            assess_task, directive_text, context_summary
        )

        # ③ 程序掷骰
        seed, roll = dm.roll(directive_id)
        margin = assessment.probability_tier - roll
        outcome = outcome_tier(margin)

        # ④ 结果撰写
        result_task = TaskSpec(
            role="dm",
            task="adjudicate",
            phase=sm.phase,
            venue_id=sm.venue_id,
        )
        result = await dm.write_result(
            result_task,
            directive_text,
            assessment.probability_tier,
            roll,
            outcome,
            context_summary,
        )

        # adjudication 事件(dm-only)
        bus.stage(
            Event(
                session_id=self.session_id,
                story_time=sm.story_time,
                type="adjudication",
                actor="dm",
                venue_id=sm.venue_id,
                scope="dm-only",
                payload={
                    "directive_id": directive_id,
                    "probability_tier": assessment.probability_tier,
                    "roll": roll,
                    "outcome": outcome,
                    "narrative_full": result.narrative_full,
                },
                rng={"seed": seed, "rolls": [roll]},
            ),
        )

        # directive_status → resolved
        bus.stage(
            Event(
                session_id=self.session_id,
                story_time=sm.story_time,
                type="directive_status",
                actor="system",
                venue_id=sm.venue_id,
                scope="private",
                payload={"directive_id": directive_id, "status": "resolved"},
            ),
            private_recipients=[],
        )

        # crisis_update(global, 简化: 直接播报)
        broadcast_text = (
            result.per_venue_visible[0]["text"]
            if result.per_venue_visible
            else result.narrative_full
        )
        bus.stage(
            Event(
                session_id=self.session_id,
                story_time=sm.story_time,
                type="crisis_update",
                actor="chair",
                venue_id=sm.venue_id,
                scope="global",
                payload={
                    "text": broadcast_text,
                    "source_directive_ids": [directive_id],
                },
            ),
        )
