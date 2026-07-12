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
    build_delegate_g_global,
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
        self._l3_start_seq: dict[str, int] = {}  # viewer -> 纪元起点 seq(11§3)
        self._directive_index: dict[str, dict] = {}  # directive id/title -> payload(投票取正文)

    def _emit_committed(self, events: list[Event]) -> None:
        if self._on_event is not None:
            for e in events:
                self._on_event(e)

    def _make_llm(self, usage_sink=None) -> LLMClient:
        if self._llm is None:
            kwargs: dict = {}
            if self._llm_transport is not None:
                kwargs["transport"] = self._llm_transport
            sinks = []
            if self._usage_sink is not None:
                sinks.append(self._usage_sink)
            if usage_sink is not None:
                sinks.append(usage_sink)
            if sinks:
                def combined_sink(record):
                    for s in sinks:
                        s(record)
                kwargs["usage_sink"] = combined_sink
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

        # 预算追踪(必须在 _make_llm 之前定义)
        total_tokens = 0
        token_budget = self.config.engine.session_max_tokens
        consecutive_failures: dict[str, int] = {}  # role -> 连续失败次数

        def _on_usage(record):
            nonlocal total_tokens
            total_tokens += record.prompt_tokens + record.completion_tokens

        llm = self._make_llm(usage_sink=_on_usage)
        venue_spec = self.scenario.venues[0]
        seat_specs = self.scenario.seats_of(venue_spec.id)
        seat_ids = [s.id for s in seat_specs]
        delegate_g = build_delegate_g_global(self.scenario, venue_spec.id)

        # G 段预热(见 11§6)
        if self.config.engine.cache_warmup:
            await self._warmup_g_segment(llm, delegate_g)

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
            s.id: DelegateAgent(llm, s, delegate_g)
            for s in seat_specs
        }
        chair = ChairAgent(llm, venue_spec.id, seat_ids)
        dm = DMAgent(llm, self.master_seed)
        from munagent.agents.recorder import RecorderAgent, estimate_tokens
        recorder = RecorderAgent(llm)

        # 纪元机制: 每视角追踪摘要(L2)和 L3 累积量
        epoch_threshold = self.config.engine.epoch_l3_max_tokens
        summaries: dict[str, str] = {}  # viewer -> 当前 L2 摘要
        l3_accum: dict[str, list[Event]] = {}  # viewer -> 本纪元 L3 事件
        self._l3_start_seq = {}  # viewer -> 纪元起点 seq(之前的事件已被压进 L2)
        self._directive_index = {}  # directive_id/title -> 指令 payload(投票时取正文)

        # 预算追踪
        consecutive_failures: dict[str, int] = {}  # role -> 连续失败次数

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
                committed = await self._run_mod_step(bus, sm, delegates, chair, dm, venue_spec, seat_ids, summaries)
            elif sm.phase == "UnmoderatedCaucus":
                committed = await self._run_unmod_phase(bus, sm, delegates, chair, venue_spec, seat_ids, summaries)
            elif sm.phase == "Voting":
                committed = await self._run_voting_step(bus, sm, delegates, chair, venue_spec, seat_ids, summaries)
            else:
                break

            all_events.extend(committed)

            # 纪元检查
            await self._check_epochs(
                bus, sm, recorder, summaries, l3_accum, committed, seat_ids, epoch_threshold
            )

            # token 预算熔断
            if total_tokens >= token_budget:
                bus.stage(
                    Event(
                        session_id=self.session_id,
                        story_time=sm.story_time,
                        type="session_control",
                        actor="system",
                        venue_id=sm.venue_id,
                        scope="dm-only",
                        payload={"action": "pause", "detail": f"token 预算耗尽({total_tokens}/{token_budget})"},
                    ),
                )
                await bus.commit_step()
                import sys
                print(f"\n[熔断] token 预算耗尽({total_tokens}/{token_budget}), 推演暂停。", file=sys.stderr)
                break

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

    # --- 纪元过滤 ---

    def _epoch_slice(self, visible: list[Event], viewer: str) -> list[Event]:
        """L3 = 本纪元起点以来的可见事件, 只追加不截断(11§3). 纪元切换前前缀字节级稳定."""
        start = getattr(self, "_l3_start_seq", {}).get(viewer, 0)
        return [e for e in visible if (e.seq or 0) > start]

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
        summaries: dict[str, str] | None = None,
    ) -> str:
        """路由 next_speaker: 有主持席→DelegateAgent, 无→ChairAgent.

        主持席(代表)点名时产生 venue 可见的 speech 事件(大家听到主持者说话);
        中立主席点名不产生事件(游戏层操作).
        """
        presider_id = self._get_presider_id(sm)
        # 主持席是戏内角色, 只能看自己视角; 中立主席才用 chair 视角
        query_viewer = f"seat:{presider_id}" if presider_id else "chair"
        visible = self._epoch_slice(await bus.query(query_viewer, venue=sm.venue_id), query_viewer)
        task = TaskSpec(
            role="delegate" if presider_id else "chair",
            task="next_speaker",
            phase=sm.phase,
            venue_id=sm.venue_id,
        )

        if presider_id:
            agent = delegates[presider_id]
            # 驳回重试: 点了不存在的席位时, 最多重试 2 次
            for attempt in range(3):
                result = await agent.presiding_next_speaker(
                    task, visible, sm.phase, sm.story_time, sm.spoken_this_phase, seat_ids,
                    l2_summary=(summaries or {}).get(f"seat:{presider_id}", ""),
                )
                target = result.seat
                if target in delegates:
                    break
                # 点了不存在的席位, 驳回
                import sys
                print(
                    f"[驳回] 主持席点了不存在的席位 '{target}', "
                    f"可用席位: {', '.join(seat_ids)}, 重试 {attempt+1}/3",
                    file=sys.stderr,
                )
            else:
                # 3 次都点了不存在的人, 保底轮询
                target = seat_ids[0]
                result = PresidingNextSpeaker(seat=target, announcement=f"请{target}发言。")

            # 主持席点名是戏内行为, 产生 venue 可见的 speech 事件
            announcement = result.announcement or f"请{target}发言。"
            speech_ev = bus.stage(
                Event(
                    session_id=self.session_id,
                    story_time=sm.story_time,
                    type="speech",
                    actor=f"seat:{presider_id}",
                    venue_id=sm.venue_id,
                    scope="venue",
                    payload={"text": announcement},
                ),
                venue_seats=seat_ids,
            )
            if result.inner_thought:
                bus.stage(
                    Event(
                        session_id=self.session_id,
                        story_time=sm.story_time,
                        type="speech_thought",
                        actor=f"seat:{presider_id}",
                        venue_id=sm.venue_id,
                        scope="self",
                        payload={"thought": result.inner_thought, "ref_seq": speech_ev.seq},
                    ),
                )
        else:
            for attempt in range(3):
                result = await chair.next_speaker(
                    task, visible, sm.phase, sm.story_time, sm.spoken_this_phase
                )
                target = result.seat
                if target in delegates:
                    break
                import sys
                print(
                    f"[驳回] 主席点了不存在的席位 '{target}', 重试 {attempt+1}/3",
                    file=sys.stderr,
                )
            else:
                target = seat_ids[0]

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
        summaries: dict[str, str] | None = None,
    ) -> list[Event]:
        """一个 ModCaucus 最小步: 点名→代表行动→时钟推进."""
        # 1. 主持者点名
        target_seat = await self._presider_next_speaker(bus, sm, delegates, chair, seat_ids, summaries)
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
            turn_task, self._epoch_slice(delegate_visible, seat_viewer), sm.phase, sm.story_time,
            is_presiding,
            l2_summary=(summaries or {}).get(f"seat:{target_seat}", ""),
        )
        turn_result = await delegate.act(turn_task, ctx)

        # 3. 处理行动
        if turn_result.action == "speech" and turn_result.text:
            await self._handle_speech(bus, sm, delegate, turn_result, target_seat, seat_ids)
        elif turn_result.action == "motion":
            await self._handle_motion(bus, sm, delegates, chair, turn_result, target_seat, seat_ids, venue_spec, summaries)
        elif turn_result.action == "write_directive" and turn_result.directive:
            await self._handle_write_directive(bus, sm, dm, turn_result, target_seat, sm.mod_speech_count, seat_ids)
        elif turn_result.action == "pass":
            # pass 也产生 venue 可见事件, 让用户看到"XX 选择跳过"
            bus.stage(
                Event(
                    session_id=self.session_id,
                    story_time=sm.story_time,
                    type="speech",
                    actor=f"seat:{target_seat}",
                    venue_id=sm.venue_id,
                    scope="venue",
                    payload={"text": f"(选择跳过)"},
                ),
                venue_seats=seat_ids,
            )
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
        summaries: dict[str, str] | None = None,
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
        motion_text = f"{motion_type}: {motion_target} ({turn_result.text})"

        if presider_id:
            pv = f"seat:{presider_id}"
            visible = self._epoch_slice(await bus.query(pv, venue=sm.venue_id), pv)
            agent = delegates[presider_id]
            ruling = await agent.presiding_motion_ruling(
                ruling_task, visible, motion_text, sm.story_time,
                l2_summary=(summaries or {}).get(pv, ""),
            )
        else:
            visible = self._epoch_slice(await bus.query("chair", venue=sm.venue_id), "chair")
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
        visible = self._epoch_slice(await bus.query("chair", venue=sm.venue_id), "chair")
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
        info = {"directive_id": directive_id, "kind": d.kind, "title": d.title,
                "body": d.body, "author": target_seat}
        self._directive_index[directive_id] = info
        if d.title:
            self._directive_index[d.title] = info
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

        # 个人指令直接判定; 危机笔记先判定截获再判定送达; 联合指令/公报需投票(P2 简化: 暂也直接判定)
        if dm is not None and d.kind == "personal":
            await self._adjudicate(bus, dm, directive_id, d.title, d.body, sm, seat_ids)
        elif dm is not None and d.kind == "crisis_note":
            await self._adjudicate_crisis_note(bus, dm, directive_id, d, target_seat, sm, seat_ids)

    # --- Voting 子流程 ---

    async def _run_voting_step(
        self,
        bus: EventBus,
        sm: VenueStateMachine,
        delegates: dict[str, DelegateAgent],
        chair: ChairAgent,
        venue_spec: VenueSpec,
        seat_ids: list[str],
        summaries: dict[str, str] | None = None,
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
            info = self._directive_index.get(directive_id, {})
            ctx = delegate.build_vote_context(
                vote_task,
                self._epoch_slice(visible, voter_viewer),
                info.get("title") or directive_id,
                sm.story_time,
                directive_body=info.get("body", ""),
                l2_summary=(summaries or {}).get(voter_viewer, ""),
            )
            result = await delegate.act(vote_task, ctx, schema_model=DelegateVoteAction)

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

    # --- UnmodCaucus ---

    async def _run_unmod_phase(
        self,
        bus: EventBus,
        sm: VenueStateMachine,
        delegates: dict[str, DelegateAgent],
        chair: ChairAgent,
        venue_spec: VenueSpec,
        seat_ids: list[str],
        summaries: dict[str, str] | None = None,
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
                turn_task,
                self._epoch_slice(visible, f"seat:{seat_id}"),
                "UnmoderatedCaucus", sm.story_time,
                l2_summary=(summaries or {}).get(f"seat:{seat_id}", ""),
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
        visible = self._epoch_slice(await bus.query("chair", venue=sm.venue_id), "chair")
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

    async def _adjudicate_crisis_note(
        self,
        bus: EventBus,
        dm: DMAgent,
        directive_id: str,
        d: Any,
        author_seat: str,
        sm: VenueStateMachine,
        seat_ids: list[str],
    ) -> None:
        """危机笔记: 先判定截获, 再判定送达. 见 06§5."""
        # 截获判定: 程序掷骰, 概率档位默认 30(低频截获)
        seed, roll = dm.roll(directive_id + ":intercept")
        intercept_tier = 30  # 截获概率较低
        margin = intercept_tier - roll
        intercepted = margin >= 10  # 成功档以上才截获

        if intercepted:
            # 截获: 产生 private 事件给主席团
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
                        "kind": "crisis_note_intercept",
                        "outcome": "截获",
                        "narrative_full": f"危机笔记'{d.title}'被截获。内容: {d.body[:100]}",
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
                    payload={"directive_id": directive_id, "status": "intercepted"},
                ),
                private_recipients=[author_seat],
            )
        else:
            # 未截获: 正常送达 + 判定内容效果
            bus.stage(
                Event(
                    session_id=self.session_id,
                    story_time=sm.story_time,
                    type="note_delivered",
                    actor="system",
                    venue_id=sm.venue_id,
                    scope="private",
                    payload={"directive_id": directive_id, "recipient": d.recipient},
                ),
                private_recipients=[author_seat, d.recipient] if d.recipient else [author_seat],
            )
            await self._adjudicate(bus, dm, directive_id, d.title, d.body, sm, seat_ids)

    # --- 纪元机制 ---

    async def _check_epochs(
        self,
        bus: EventBus,
        sm: VenueStateMachine,
        recorder: Any,
        summaries: dict[str, str],
        l3_accum: dict[str, list[Event]],
        new_committed: list[Event],
        seat_ids: list[str],
        threshold: int,
    ) -> None:
        """检查各视角 L3 是否超阈值, 超了则触发摘要. 见 11§3."""
        from munagent.agents.recorder import estimate_tokens

        viewers = [f"seat:{sid}" for sid in seat_ids] + ["chair", "dm"]
        for viewer in viewers:
            # 累积本视角可见的新事件
            for e in new_committed:
                if e.is_visible_to(viewer):
                    l3_accum.setdefault(viewer, []).append(e)

            accum = l3_accum.get(viewer, [])
            if not accum:
                continue

            l3_text = "\n".join(render(e) for e in accum)
            if estimate_tokens(l3_text) < threshold:
                continue

            # 触发纪元切换: 书记压缩
            level = "private" if viewer.startswith("seat:") else "dm-only"
            if viewer == "chair":
                level = "venue"
            old_summary = summaries.get(viewer, "")
            task = TaskSpec(
                role="recorder",
                task="summarize",
                phase=sm.phase,
                venue_id=sm.venue_id,
            )
            new_summary = await recorder.summarize(task, old_summary, accum, level)
            summaries[viewer] = new_summary

            # 产生 summary_written 事件
            bus.stage(
                Event(
                    session_id=self.session_id,
                    story_time=sm.story_time,
                    type="summary_written",
                    actor="recorder",
                    venue_id=sm.venue_id,
                    scope="dm-only",
                    payload={
                        "level": level,
                        "text": new_summary,
                        "viewer": viewer,
                    },
                ),
            )
            committed = await bus.commit_step()
            self._emit_committed(committed)

            # L3 清空, 开始新纪元; 记录起点 seq 供 _epoch_slice 过滤
            if accum:
                self._l3_start_seq[viewer] = max((e.seq or 0) for e in accum)
            l3_accum[viewer] = []

    async def _warmup_g_segment(self, llm: LLMClient, g_global: str) -> None:
        """G 段预热: 会话启动时发一次廉价请求建立缓存. 见 11§6."""
        from munagent.llm.client import ChatMessage, ChatRequest

        request = ChatRequest(
            role="delegate",
            task="warmup",
            messages=[
                ChatMessage(role="system", content=g_global),
                ChatMessage(role="user", content="理解了. 回复ok."),
            ],
            max_tokens=5,
        )
        try:
            await llm.chat(request)
        except Exception:
            pass  # 预热失败不影响推演
