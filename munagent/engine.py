"""推演引擎(P2): 完整会议机制.

支持: Mod/Unmod/Voting 三阶段、主持席路由、动议处理、四类指令、DM 判定完整五步.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from munagent.agents.base import TaskSpec
from munagent.agents.chair import AppealRulingAction, ChairAgent
from munagent.agents.delegate import (
    DelegateAgent,
    DelegateTurnAction,
    DelegateVoteAction,
    PresidingCaucusSwitch,
    PresidingMotionRuling,
    PresidingNextSpeaker,
)
from munagent.agents.dm import DMAgent, outcome_tier
from munagent.config.models import MunagentConfig
from munagent.core.bus import EventBus
from munagent.core.events import Event
from munagent.core.render import render
from munagent.core.scenario import Scenario, SeatSpec, VenueSpec
from munagent.core.state_machine import GroupState, VenueStateMachine
from munagent.llm.client import LLMClient


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
    """P2 推演引擎: 单会场完整会议机制 + 主持席路由."""

    def __init__(
        self,
        scenario: Scenario,
        config: MunagentConfig,
        *,
        master_seed: int | None = None,
        max_steps: int = 30,
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
            initial_phase="Opening",  # 统一从 Opening 开始, 再转到 initial_phase
            start_story_time=self.scenario.manifest.start_story_time,
            per_mod_speech=venue_spec.clock_rate.per_mod_speech,
            per_unmod_round=venue_spec.clock_rate.per_unmod_round,
            max_speeches=self.config.engine.mod_max_speeches,
            unmod_rounds=self.config.engine.unmod_rounds,
            presiding_seat=venue_spec.presiding_seat,
        )

        delegates = {
            s.id: DelegateAgent(llm, s, self.scenario.background[:500])
            for s in seat_specs
        }
        chair = ChairAgent(llm, venue_spec.id, seat_ids)
        dm = DMAgent(llm, self.master_seed)

        all_events: list[Event] = []
        step = 0

        # Opening → 初始阶段
        initial = venue_spec.initial_phase
        bus.stage(
            Event(
                session_id=self.session_id,
                story_time=sm.story_time,
                type="phase_change",
                actor="chair",
                venue_id=sm.venue_id,
                scope="venue",
                payload={"from": "Opening", "to": initial, "reason": "会议开始"},
            ),
            venue_seats=seat_ids,
        )
        committed = await bus.commit_step()
        all_events.extend(committed)
        self._emit_committed(committed)
        sm.transition(initial)

        while step < self.max_steps and sm.phase != "Adjourned":
            step += 1
            if sm.phase == "ModeratedCaucus":
                committed = await self._run_mod_step(bus, sm, delegates, chair, dm, venue_spec, seat_ids)
            elif sm.phase == "UnmoderatedCaucus":
                committed = await self._run_unmod_phase(bus, sm, delegates, chair, venue_spec, seat_ids)
            elif sm.phase == "Voting":
                committed = await self._run_voting_step(bus, sm, delegates, chair, venue_spec, seat_ids)
            else:
                break

            all_events.extend(committed)

            # 预算检查
            if sm.phase == "ModeratedCaucus" and sm.budget_exceeded:
                committed = await self._chair_phase_decision(bus, sm, chair, seat_ids)
                all_events.extend(committed)

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

    # --- 主持者路由 ---

    def _get_presider_id(self, sm: VenueStateMachine) -> str | None:
        """返回当前主持席 id, 无则 None(走中立主席)."""
        ps = sm.presiding_seat
        if ps and ps in sm.seat_ids:
            return ps
        return None

    async def _presider_next_speaker(
        self,
        bus: EventBus,
        sm: VenueStateMachine,
        delegates: dict[str, DelegateAgent],
        chair: ChairAgent,
        seat_ids: list[str],
    ) -> str:
        """路由 next_speaker: 有主持席→DelegateAgent, 无→ChairAgent."""
        presider_id = self._get_presider_id(sm)
        visible = await bus.query("chair", venue=sm.venue_id)
        task = TaskSpec(
            role="delegate" if presider_id else "chair",
            task="next_speaker",
            phase=sm.phase,
            venue_id=sm.venue_id,
        )

        if presider_id:
            agent = delegates[presider_id]
            result = await agent.presiding_next_speaker(
                task, visible, sm.phase, sm.story_time, sm.spoken_this_phase, seat_ids
            )
            target = result.seat
        else:
            result = await chair.next_speaker(
                task, visible, sm.phase, sm.story_time, sm.spoken_this_phase
            )
            target = result.seat

        # 保底轮询覆盖
        if sm.floor_rotation_due:
            forced = sm.next_for_floor_rotation()
            if forced:
                target = forced

        if target not in delegates:
            target = seat_ids[0]
        return target

    # --- ModCaucus ---

    async def _run_mod_step(
        self,
        bus: EventBus,
        sm: VenueStateMachine,
        delegates: dict[str, DelegateAgent],
        chair: ChairAgent,
        dm: DMAgent,
        venue_spec: VenueSpec,
        seat_ids: list[str],
    ) -> list[Event]:
        """一个 ModCaucus 最小步: 点名→代表行动→时钟推进."""
        # 1. 主持者点名
        target_seat = await self._presider_next_speaker(bus, sm, delegates, chair, seat_ids)
        delegate = delegates[target_seat]

        # 2. 代表行动
        seat_viewer = f"seat:{target_seat}"
        delegate_visible = await bus.query(seat_viewer, venue=sm.venue_id)
        is_presiding = (target_seat == sm.presiding_seat)
        turn_task = TaskSpec(
            role="delegate",
            task="turn",
            phase=sm.phase,
            scope="venue",
            venue_id=sm.venue_id,
            seat_id=target_seat,
        )
        ctx = delegate.build_turn_context(
            turn_task, delegate_visible, sm.phase, sm.story_time, is_presiding
        )
        turn_result = await delegate.act(turn_task, ctx)

        # 3. 处理行动
        if turn_result.action == "speech" and turn_result.text:
            await self._handle_speech(bus, sm, delegate, turn_result, target_seat, seat_ids)
        elif turn_result.action == "motion":
            await self._handle_motion(bus, sm, delegates, chair, turn_result, target_seat, seat_ids, venue_spec)
        elif turn_result.action == "write_directive" and turn_result.directive:
            await self._handle_write_directive(bus, sm, dm, turn_result, target_seat, sm.mod_speech_count, seat_ids)
        elif turn_result.action == "pass":
            sm.record_no_speech()

        # 4. 时钟推进
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
        self._emit_committed(committed)
        return committed

    async def _handle_speech(
        self,
        bus: EventBus,
        sm: VenueStateMachine,
        delegate: DelegateAgent,
        turn_result: DelegateTurnAction,
        target_seat: str,
        seat_ids: list[str],
    ) -> None:
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

    async def _handle_motion(
        self,
        bus: EventBus,
        sm: VenueStateMachine,
        delegates: dict[str, DelegateAgent],
        chair: ChairAgent,
        turn_result: DelegateTurnAction,
        target_seat: str,
        seat_ids: list[str],
        venue_spec: VenueSpec,
    ) -> None:
        motion_type = turn_result.motion_type or "caucus_switch"
        motion_target = turn_result.motion_target or ""

        # 产生 motion 事件
        motion_ev = bus.stage(
            Event(
                session_id=self.session_id,
                story_time=sm.story_time,
                type="motion",
                actor=f"seat:{target_seat}",
                venue_id=sm.venue_id,
                scope="venue",
                payload={"motion_type": motion_type, "target": motion_target, "text": turn_result.text},
            ),
            venue_seats=seat_ids,
        )

        # appeal 动议 → 戏外主席终裁
        if motion_type == "appeal":
            await self._handle_appeal(bus, sm, chair, turn_result, motion_ev, seat_ids)
            return

        # 其他动议 → 主持者裁决
        presider_id = self._get_presider_id(sm)
        ruling_task = TaskSpec(
            role="delegate" if presider_id else "chair",
            task="motion_ruling",
            phase=sm.phase,
            venue_id=sm.venue_id,
        )
        visible = await bus.query("chair", venue=sm.venue_id)
        motion_text = f"{motion_type}: {motion_target} ({turn_result.text})"

        if presider_id:
            agent = delegates[presider_id]
            ruling = await agent.presiding_motion_ruling(
                ruling_task, visible, motion_text, sm.story_time
            )
        else:
            ruling_result = await chair.motion_ruling(
                ruling_task, visible, motion_text, sm.story_time
            )
            class _R:
                def __init__(self, r, reason):
                    self.ruling = r
                    self.reason = reason
                    self.inner_thought = ""
            ruling = _R(ruling_result.ruling, ruling_result.reason)

        # motion_ruling 事件
        bus.stage(
            Event(
                session_id=self.session_id,
                story_time=sm.story_time,
                type="motion_ruling",
                actor=f"seat:{presider_id}" if presider_id else "chair",
                venue_id=sm.venue_id,
                scope="venue",
                payload={
                    "motion_seq": motion_ev.seq,
                    "ruling": ruling.ruling,
                    "reason": ruling.reason,
                },
            ),
            venue_seats=seat_ids,
        )

        # 受理 → 执行动议后果
        if ruling.ruling == "accept":
            if motion_type == "caucus_switch":
                # 切磋商形式
                target_phase = "UnmoderatedCaucus" if sm.phase == "ModeratedCaucus" else "ModeratedCaucus"
                sm.transition(target_phase)
                bus.stage(
                    Event(
                        session_id=self.session_id,
                        story_time=sm.story_time,
                        type="phase_change",
                        actor=f"seat:{presider_id}" if presider_id else "chair",
                        venue_id=sm.venue_id,
                        scope="venue",
                        payload={"from": "ModeratedCaucus" if target_phase == "UnmoderatedCaucus" else "UnmoderatedCaucus", "to": target_phase, "reason": turn_result.text or "动议通过"},
                    ),
                    venue_seats=seat_ids,
                )
            elif motion_type == "vote_directive":
                # 进入 Voting 子流程
                sm.transition("Voting", interrupted_from="ModeratedCaucus")
                # vote_call 事件
                bus.stage(
                    Event(
                        session_id=self.session_id,
                        story_time=sm.story_time,
                        type="vote_call",
                        actor=f"seat:{presider_id}" if presider_id else "chair",
                        venue_id=sm.venue_id,
                        scope="venue",
                        payload={"directive_id": motion_target},
                    ),
                    venue_seats=seat_ids,
                )

    async def _handle_appeal(
        self,
        bus: EventBus,
        sm: VenueStateMachine,
        chair: ChairAgent,
        turn_result: DelegateTurnAction,
        motion_ev: Event,
        seat_ids: list[str],
    ) -> None:
        """appeal 动议 → 戏外主席终裁."""
        visible = await bus.query("chair", venue=sm.venue_id)
        task = TaskSpec(
            role="chair",
            task="appeal_ruling",
            phase=sm.phase,
            venue_id=sm.venue_id,
        )
        result = await chair.appeal_ruling(
            task, visible, turn_result.text, turn_result.motion_target, sm.story_time
        )
        bus.stage(
            Event(
                session_id=self.session_id,
                story_time=sm.story_time,
                type="motion_ruling",
                actor="chair",
                venue_id=sm.venue_id,
                scope="venue",
                payload={
                    "motion_seq": motion_ev.seq,
                    "ruling": "accept" if result.ruling == "overrule" else "reject",
                    "reason": f"申诉终裁: {result.reason}",
                },
            ),
            venue_seats=seat_ids,
        )

    async def _handle_write_directive(
        self,
        bus: EventBus,
        sm: VenueStateMachine,
        dm: DMAgent | None,
        delegate_result: DelegateTurnAction,
        target_seat: str,
        step: int,
        seat_ids: list[str],
    ) -> None:
        d = delegate_result.directive
        if d is None:
            return
        directive_id = f"d-{self.session_id}-{step}"
        scope = "private" if d.kind in ("personal", "crisis_note") else "venue"
        recipients = [target_seat] if d.kind in ("personal", "crisis_note") else seat_ids

        bus.stage(
            Event(
                session_id=self.session_id,
                story_time=sm.story_time,
                type="directive_submitted",
                actor=f"seat:{target_seat}",
                venue_id=sm.venue_id,
                scope=scope,
                payload={
                    "directive_id": directive_id,
                    "kind": d.kind,
                    "title": d.title,
                    "body": d.body,
                    "uses_powers": d.uses_powers,
                    "author": target_seat,
                    "co_sponsors": d.co_sponsors,
                    "recipient": d.recipient,
                },
            ),
            venue_seats=recipients if scope == "venue" else None,
            private_recipients=recipients if scope == "private" else None,
        )

        # 个人指令/危机笔记直接入后场判定; 联合指令/公报需投票(P2 简化: 暂也直接判定)
        if dm is not None and d.kind in ("personal", "crisis_note"):
            await self._adjudicate(bus, dm, directive_id, d.title, d.body, sm, seat_ids)

    # --- Voting 子流程 ---

    async def _run_voting_step(
        self,
        bus: EventBus,
        sm: VenueStateMachine,
        delegates: dict[str, DelegateAgent],
        chair: ChairAgent,
        venue_spec: VenueSpec,
        seat_ids: list[str],
    ) -> list[Event]:
        """Voting 子流程: 逐席位投票 → 计票 → 返回."""
        if sm.active_vote_directive_id is None:
            # 初始化投票顺序
            sm.start_vote(sm.active_vote_directive_id or "", seat_ids)

        # 逐席位投票
        while not sm.voting_finished:
            voter = sm.next_voter()
            if voter is None:
                break
            if voter not in delegates:
                sm.record_vote(voter, "abstain")
                continue

            delegate = delegates[voter]
            voter_viewer = f"seat:{voter}"
            visible = await bus.query(voter_viewer, venue=sm.venue_id)
            vote_task = TaskSpec(
                role="delegate",
                task="vote",
                phase="Voting",
                venue_id=sm.venue_id,
                seat_id=voter,
            )
            directive_id = sm.active_vote_directive_id or ""
            ctx = delegate.build_vote_context(vote_task, visible, directive_id, sm.story_time)
            self._schema_model_override(delegate, DelegateVoteAction)
            result = await delegate.act(vote_task, ctx)

            choice = result.choice if isinstance(result, DelegateVoteAction) else "abstain"
            sm.record_vote(voter, choice)
            bus.stage(
                Event(
                    session_id=self.session_id,
                    story_time=sm.story_time,
                    type="vote_cast",
                    actor=f"seat:{voter}",
                    venue_id=sm.venue_id,
                    scope="venue",
                    payload={"directive_id": directive_id, "choice": choice},
                ),
                venue_seats=seat_ids,
            )

        # 计票
        result_str, tally = sm.tally_votes(
            venue_spec.decision_rule.pass_threshold,
            venue_spec.decision_rule.veto_seats,
        )
        directive_id = sm.active_vote_directive_id or ""
        bus.stage(
            Event(
                session_id=self.session_id,
                story_time=sm.story_time,
                type="vote_result",
                actor="system",
                venue_id=sm.venue_id,
                scope="venue",
                payload={
                    "directive_id": directive_id,
                    "result": result_str,
                    "tally": str(tally),
                },
            ),
            venue_seats=seat_ids,
        )

        # 指令状态更新
        bus.stage(
            Event(
                session_id=self.session_id,
                story_time=sm.story_time,
                type="directive_status",
                actor="system",
                venue_id=sm.venue_id,
                scope="venue",
                payload={"directive_id": directive_id, "status": result_str},
            ),
            venue_seats=seat_ids,
        )

        # 返回被打断的阶段
        return_phase = sm.end_vote()
        sm.transition(return_phase)
        bus.stage(
            Event(
                session_id=self.session_id,
                story_time=sm.story_time,
                type="phase_change",
                actor="chair",
                venue_id=sm.venue_id,
                scope="venue",
                payload={"from": "Voting", "to": return_phase, "reason": "表决完毕"},
            ),
            venue_seats=seat_ids,
        )

        committed = await bus.commit_step()
        self._emit_committed(committed)
        return committed

    def _schema_model_override(self, agent: DelegateAgent, model: type) -> None:
        agent._schema_model = model

    # --- UnmodCaucus ---

    async def _run_unmod_phase(
        self,
        bus: EventBus,
        sm: VenueStateMachine,
        delegates: dict[str, DelegateAgent],
        chair: ChairAgent,
        venue_spec: VenueSpec,
        seat_ids: list[str],
    ) -> list[Event]:
        """Unmod: 分组→小轮并行→屏障结算. P2 简化版(单轮, 无闭门)."""
        if not sm.groups:
            # 初始分组: 每人表达意愿, 简化为全体一组
            sm.init_groups([GroupState("g1", list(seat_ids))])

        # 跑一轮: 每人发言一次
        for seat_id in seat_ids:
            delegate = delegates[seat_id]
            visible = await bus.query(f"seat:{seat_id}", venue=sm.venue_id, group="g1")
            turn_task = TaskSpec(
                role="delegate",
                task="turn",
                phase="UnmoderatedCaucus",
                scope="group",
                venue_id=sm.venue_id,
                seat_id=seat_id,
            )
            ctx = delegate.build_turn_context(
                turn_task, visible, "UnmoderatedCaucus", sm.story_time
            )
            turn_result = await delegate.act(turn_task, ctx)

            if turn_result.action == "speech" and turn_result.text:
                bus.stage(
                    Event(
                        session_id=self.session_id,
                        story_time=sm.story_time,
                        type="speech",
                        actor=f"seat:{seat_id}",
                        venue_id=sm.venue_id,
                        group_id="g1",
                        scope="group",
                        payload={"text": turn_result.text},
                    ),
                    group_members=seat_ids,
                )
                if turn_result.inner_thought:
                    bus.stage(
                        Event(
                            session_id=self.session_id,
                            story_time=sm.story_time,
                            type="speech_thought",
                            actor=f"seat:{seat_id}",
                            venue_id=sm.venue_id,
                            scope="self",
                            payload={"thought": turn_result.inner_thought},
                        ),
                    )

        sm.next_unmod_round()
        sm.advance_clock(unmod=True)
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

        # 小轮跑完 → 主席决定返回 Mod
        if sm.unmod_finished:
            sm.transition("ModeratedCaucus")
            bus.stage(
                Event(
                    session_id=self.session_id,
                    story_time=sm.story_time,
                    type="phase_change",
                    actor="chair",
                    venue_id=sm.venue_id,
                    scope="venue",
                    payload={"from": "UnmoderatedCaucus", "to": "ModeratedCaucus", "reason": "非正式磋商结束"},
                ),
                venue_seats=seat_ids,
            )

        committed = await bus.commit_step()
        self._emit_committed(committed)
        return committed

    # --- 阶段决策 ---

    async def _chair_phase_decision(
        self,
        bus: EventBus,
        sm: VenueStateMachine,
        chair: ChairAgent,
        seat_ids: list[str],
    ) -> list[Event]:
        visible = await bus.query("chair", venue=sm.venue_id)
        task = TaskSpec(
            role="chair",
            task="phase_decision",
            phase=sm.phase,
            venue_id=sm.venue_id,
        )
        decision = await chair.phase_decision(
            task, visible, sm.phase, sm.story_time, sm.mod_speech_count, sm.max_speeches
        )

        events_to_commit: list[Event] = []
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
                    payload={"from": sm.phase, "to": "Adjourned", "reason": decision.announcement or "闭会"},
                ),
                venue_seats=seat_ids,
            )
        elif decision.action == "switch" and decision.to_phase:
            if sm.can_transition(decision.to_phase):
                old_phase = sm.phase
                sm.transition(decision.to_phase)
                bus.stage(
                    Event(
                        session_id=self.session_id,
                        story_time=sm.story_time,
                        type="phase_change",
                        actor="chair",
                        venue_id=sm.venue_id,
                        scope="venue",
                        payload={"from": old_phase, "to": decision.to_phase, "reason": decision.announcement},
                    ),
                    venue_seats=seat_ids,
                )

        committed = await bus.commit_step()
        self._emit_committed(committed)
        return committed

    # --- DM 判定 ---

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
        directive_text = f"标题: {title}\n内容: {body}"
        context_summary = self.scenario.background[:300]

        assess_task = TaskSpec(role="dm", task="adjudicate", phase=sm.phase, venue_id=sm.venue_id)
        assessment = await dm.assess_feasibility(assess_task, directive_text, context_summary)

        seed, roll = dm.roll(directive_id)
        margin = assessment.probability_tier - roll
        outcome = outcome_tier(margin)

        result_task = TaskSpec(role="dm", task="adjudicate", phase=sm.phase, venue_id=sm.venue_id)
        result = await dm.write_result(
            result_task, directive_text, assessment.probability_tier, roll, outcome, context_summary
        )

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
                payload={"text": broadcast_text, "source_directive_ids": [directive_id]},
            ),
        )
