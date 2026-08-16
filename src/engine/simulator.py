from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent.inbox import (
    Observation,
    ObservationKind,
    ObservationPriority,
)
from agent.chair_agent import ChairAgent
from agent.dm_agent import DMAgent
from agent.rep_agent import AgentStoppedError, RepresentativeAgent
from agent.system_agent import SystemAgentStoppedError
from agent.rep_context import snapshot_event
from engine.end_conditions import (
    TextEndConditionEvaluator,
    build_end_condition_evidence,
)
from engine.venue_engine import VenueEngine
from event.event import (
    EventStatus,
    EventType,
    InstructionEvent,
    MeetingStartEvent,
    PhaseSwitchEvent,
    ResolutionEvent,
)
from llm import LLMCancelledError
from scenario.scenario import Scenario
from scenario.venue import SessionPhase

if TYPE_CHECKING:
    from event.event import Event
    from llm import LLM
    from scenario.representative import Representative
    from scenario.venue import Venue


LLMFactory = Callable[["Representative"], "LLM | None"]
VenueLLMFactory = Callable[["Venue"], "LLM | None"]


@dataclass(frozen=True)
class EndConditionMatch:
    """一次触发自动终局的可审计结果。"""

    condition_index: int
    condition_type: str
    content: str
    story_time: str
    reason: str
    evidence_event_ids: tuple[int, ...] = ()


class Simulator:
    """场景级仿真器:为每个会场 / 代表启动独立线程运行引擎与 Agent."""

    scenario: Scenario
    __venue_engines: dict[str, VenueEngine]
    __venue_threads: dict[str, threading.Thread]
    __venue_errors: dict[str, Exception]
    __agents: dict[str, RepresentativeAgent]
    __agent_threads: dict[str, threading.Thread]
    __agent_errors: dict[str, Exception]
    __chair_agents: dict[str, ChairAgent]
    __chair_threads: dict[str, threading.Thread]
    __chair_errors: dict[str, Exception]
    __dm_agents: dict[str, DMAgent]
    __dm_threads: dict[str, threading.Thread]
    __dm_errors: dict[str, Exception]
    __end_condition_thread: threading.Thread | None
    __end_condition_match: EndConditionMatch | None
    __end_condition_error: Exception | None
    __end_condition_fatal_error: Exception | None
    __end_condition_version: int
    __end_condition_wakeup: threading.Event
    __started: bool
    __stop_event: threading.Event
    __state_lock: threading.RLock
    __llm_factory: LLMFactory | None
    __chair_llm_factory: VenueLLMFactory | None
    __dm_llm_factory: VenueLLMFactory | None
    __dm_random_seed: str
    __text_end_condition_evaluator: TextEndConditionEvaluator | None
    __observation_sequences: dict[str, int]

    def __init__(
        self,
        scenario: Scenario,
        *,
        llm_factory: LLMFactory | None = None,
        chair_llm_factory: VenueLLMFactory | None = None,
        dm_llm_factory: VenueLLMFactory | None = None,
        dm_random_seed: str | int = "0",
        text_end_condition_evaluator: TextEndConditionEvaluator | None = None,
    ) -> None:
        self.scenario = scenario
        self.__venue_engines = {}
        self.__venue_threads = {}
        self.__venue_errors = {}
        self.__agents = {}
        self.__agent_threads = {}
        self.__agent_errors = {}
        self.__chair_agents = {}
        self.__chair_threads = {}
        self.__chair_errors = {}
        self.__dm_agents = {}
        self.__dm_threads = {}
        self.__dm_errors = {}
        self.__end_condition_thread = None
        self.__end_condition_match = None
        self.__end_condition_error = None
        self.__end_condition_fatal_error = None
        self.__end_condition_version = 0
        self.__end_condition_wakeup = threading.Event()
        self.__started = False
        self.__stop_event = threading.Event()
        self.__state_lock = threading.RLock()
        self.__llm_factory = llm_factory
        self.__chair_llm_factory = chair_llm_factory
        self.__dm_llm_factory = dm_llm_factory
        self.__dm_random_seed = str(dm_random_seed)
        self.__text_end_condition_evaluator = text_end_condition_evaluator
        self.__observation_sequences = {}
        self.shutdown_grace_s = 5.0

    @property
    def venue_engines(self) -> dict[str, VenueEngine]:
        """会场引擎句柄(副本;键为 venue id)."""
        with self.__state_lock:
            return dict(self.__venue_engines)

    @property
    def venue_threads(self) -> dict[str, threading.Thread]:
        """会场线程句柄(副本;键为 venue id)."""
        with self.__state_lock:
            return dict(self.__venue_threads)

    @property
    def venue_errors(self) -> dict[str, Exception]:
        """会场线程捕获到的异常(副本;键为 venue id)."""
        with self.__state_lock:
            return dict(self.__venue_errors)

    @property
    def agents(self) -> dict[str, RepresentativeAgent]:
        """代表 Agent 句柄(副本;键为 rep id)."""
        with self.__state_lock:
            return dict(self.__agents)

    @property
    def agent_threads(self) -> dict[str, threading.Thread]:
        """代表 Agent 线程句柄(副本;键为 rep id)."""
        with self.__state_lock:
            return dict(self.__agent_threads)

    @property
    def agent_errors(self) -> dict[str, Exception]:
        """代表 Agent 线程捕获到的异常(副本;键为 rep id)."""
        with self.__state_lock:
            return dict(self.__agent_errors)

    @property
    def chair_agents(self) -> dict[str, ChairAgent]:
        """主席 Agent 句柄（键为 venue id）。"""
        with self.__state_lock:
            return dict(self.__chair_agents)

    @property
    def chair_threads(self) -> dict[str, threading.Thread]:
        with self.__state_lock:
            return dict(self.__chair_threads)

    @property
    def chair_errors(self) -> dict[str, Exception]:
        with self.__state_lock:
            return dict(self.__chair_errors)

    @property
    def dm_agents(self) -> dict[str, DMAgent]:
        """DM Agent 句柄（键为 venue id）。"""
        with self.__state_lock:
            return dict(self.__dm_agents)

    @property
    def dm_threads(self) -> dict[str, threading.Thread]:
        with self.__state_lock:
            return dict(self.__dm_threads)

    @property
    def dm_errors(self) -> dict[str, Exception]:
        with self.__state_lock:
            return dict(self.__dm_errors)

    @property
    def dm_random_seed(self) -> str:
        """本次运行用于 DM 指令投点的原始种子。"""
        return self.__dm_random_seed

    @property
    def end_condition_match(self) -> EndConditionMatch | None:
        with self.__state_lock:
            return self.__end_condition_match

    @property
    def end_condition_error(self) -> Exception | None:
        """最近一次文本终局裁判错误；后续检查成功后会清空。"""
        with self.__state_lock:
            return self.__end_condition_error

    @property
    def end_condition_fatal_error(self) -> Exception | None:
        with self.__state_lock:
            return self.__end_condition_fatal_error

    @property
    def started(self) -> bool:
        with self.__state_lock:
            return self.__started

    @property
    def stop_requested(self) -> bool:
        return self.__stop_event.is_set()

    def run(self) -> None:
        """初始化场景,启动会场与代表线程,并阻塞至全部结束."""
        self.start()
        self.join()

    def start(self) -> None:
        """初始化场景并启动各会场 / 代表线程;不阻塞等待结束."""
        if self.__started:
            raise RuntimeError("Simulator 已启动线程,不能重复 start/run")
        if not self.scenario.venues:
            raise RuntimeError("场景无会场,无法启动 VenueEngine")
        if not self.scenario.representatives:
            raise RuntimeError("场景无代表,无法启动 Agent")

        self.scenario.initialize()
        with self.__state_lock:
            self.__venue_errors = {}
            self.__agent_errors = {}
            self.__chair_errors = {}
            self.__dm_errors = {}
            self.__end_condition_match = None
            self.__end_condition_error = None
            self.__end_condition_fatal_error = None
            self.__end_condition_version = 0
            self.__observation_sequences = {}
        self.__end_condition_wakeup.clear()
        self.__stop_event.clear()
        self.__started = True
        try:
            for venue in self.scenario.venues:
                self._start_venue_thread(venue)
            for rep in self.scenario.representatives:
                self._start_agent_thread(rep)
            for venue in self.scenario.venues:
                self._start_dm_thread(venue)
                self._start_chair_thread(venue)
            if not self.stop_requested:
                self._submit_startup_events()
                self._start_end_condition_thread()
        except BaseException:
            self._request_stop()
            self._join_started_threads(time.monotonic() + self.shutdown_grace_s)
            raise

    def stop(self) -> None:
        """请求所有 Agent 与 VenueEngine 协作停止；可从其他线程调用."""
        if not self.__started:
            raise RuntimeError("Simulator 尚未 start/run,没有可停止的线程")
        self._request_stop()

    def join(self, timeout: float | None = None) -> None:
        """等待全部会场与代表线程结束;任一线程超时或曾抛错则失败."""
        if not self.__started:
            raise RuntimeError("Simulator 尚未 start/run,没有可 join 的线程")

        deadline = None if timeout is None else time.monotonic() + timeout
        shutdown_deadline: float | None = None
        timed_out = False

        while self._alive_threads():
            self._collect_venue_failures()
            if self._has_worker_errors():
                self._request_stop()
            elif not any(thread.is_alive() for thread in self._agent_role_threads()):
                self._request_stop()

            now = time.monotonic()
            if deadline is not None and now >= deadline and not timed_out:
                timed_out = True
                self._request_stop()
            if self.stop_requested and shutdown_deadline is None:
                shutdown_deadline = now + self.shutdown_grace_s
            if shutdown_deadline is not None and now >= shutdown_deadline:
                break

            for thread in self._alive_threads():
                thread.join(timeout=0.01)

        self._collect_venue_failures()
        alive = self._alive_threads()
        venue_errors = self.venue_errors
        agent_errors = self.agent_errors
        chair_errors = self.chair_errors
        dm_errors = self.dm_errors
        end_condition_fatal_error = self.end_condition_fatal_error

        if venue_errors:
            venue_id, exc = next(iter(venue_errors.items()))
            suffix = self._alive_thread_suffix(alive)
            raise RuntimeError(
                f"会场 {venue_id!r} 的 VenueEngine 线程异常退出{suffix}"
            ) from exc
        if agent_errors:
            rep_id, exc = next(iter(agent_errors.items()))
            suffix = self._alive_thread_suffix(alive)
            raise RuntimeError(
                f"代表 {rep_id!r} 的 Agent 线程异常退出{suffix}"
            ) from exc
        if chair_errors:
            venue_id, exc = next(iter(chair_errors.items()))
            suffix = self._alive_thread_suffix(alive)
            raise RuntimeError(
                f"会场 {venue_id!r} 的 ChairAgent 线程异常退出{suffix}"
            ) from exc
        if dm_errors:
            venue_id, exc = next(iter(dm_errors.items()))
            suffix = self._alive_thread_suffix(alive)
            raise RuntimeError(
                f"会场 {venue_id!r} 的 DMAgent 线程异常退出{suffix}"
            ) from exc
        if end_condition_fatal_error is not None:
            suffix = self._alive_thread_suffix(alive)
            raise RuntimeError(f"终局条件监视线程异常退出{suffix}") from (
                end_condition_fatal_error
            )
        if timed_out or alive:
            names = ", ".join(thread.name for thread in alive) or "(已协作退出)"
            raise TimeoutError(f"Simulator 未在期限内结束；仍存活线程: {names}")

    def _start_venue_thread(self, venue: Venue) -> None:
        if venue.id in self.__venue_threads:
            raise RuntimeError(f"会场 {venue.id!r} 的线程已存在,不能重复启动")
        engine = VenueEngine(self, venue)
        thread = threading.Thread(
            target=self._run_venue,
            args=(engine,),
            name=f"venue:{venue.id}",
            daemon=True,
        )
        with self.__state_lock:
            self.__venue_engines[venue.id] = engine
            self.__venue_threads[venue.id] = thread
        thread.start()
        deadline = time.monotonic() + 5.0
        while not engine.wait_until_started(timeout=0.01):
            if not thread.is_alive():
                exc = self.venue_errors.get(venue.id)
                if exc is not None:
                    raise RuntimeError(
                        f"会场 {venue.id!r} 的 VenueEngine 线程异常退出"
                    ) from exc
                raise RuntimeError(
                    f"会场 {venue.id!r} 的 VenueEngine 未启动即退出"
                )
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"会场 {venue.id!r} 的 VenueEngine 未能在期限内启动"
                )

    def _start_agent_thread(self, rep: Representative) -> None:
        if rep.id in self.__agent_threads:
            raise RuntimeError(f"代表 {rep.id!r} 的 Agent 线程已存在,不能重复启动")
        llm = self.__llm_factory(rep) if self.__llm_factory is not None else None
        agent = RepresentativeAgent(
            rep,
            llm=llm,
            stop_event=self.__stop_event,
        )
        thread = threading.Thread(
            target=self._run_agent,
            args=(agent,),
            name=f"agent:{rep.id}",
            daemon=True,
        )
        with self.__state_lock:
            self.__agents[rep.id] = agent
            self.__agent_threads[rep.id] = thread
        thread.start()

    def _start_chair_thread(self, venue: Venue) -> None:
        if venue.id in self.__chair_threads:
            raise RuntimeError(
                f"会场 {venue.id!r} 的 ChairAgent 线程已存在，不能重复启动"
            )
        llm = (
            self.__chair_llm_factory(venue)
            if self.__chair_llm_factory is not None
            else None
        )
        representative_memory = None
        if venue.chair is not None:
            representative = self.__agents.get(venue.chair)
            if representative is None:
                raise RuntimeError(
                    f"会场 {venue.id!r} 的代表主席 {venue.chair!r} 没有 RepresentativeAgent"
                )
            representative_memory = representative.memory
        agent = ChairAgent(
            venue,
            llm=llm,
            representative_memory=representative_memory,
            stop_event=self.__stop_event,
        )
        thread = threading.Thread(
            target=self._run_chair,
            args=(agent,),
            name=f"chair:{venue.id}",
            daemon=True,
        )
        with self.__state_lock:
            self.__chair_agents[venue.id] = agent
            self.__chair_threads[venue.id] = thread
        thread.start()

    def _start_dm_thread(self, venue: Venue) -> None:
        if venue.id in self.__dm_threads:
            raise RuntimeError(
                f"会场 {venue.id!r} 的 DMAgent 线程已存在，不能重复启动"
            )
        llm = (
            self.__dm_llm_factory(venue)
            if self.__dm_llm_factory is not None
            else None
        )
        agent = DMAgent(
            venue,
            llm=llm,
            random_seed=self.__dm_random_seed,
            stop_event=self.__stop_event,
        )
        thread = threading.Thread(
            target=self._run_dm,
            args=(agent,),
            name=f"dm:{venue.id}",
            daemon=True,
        )
        with self.__state_lock:
            self.__dm_agents[venue.id] = agent
            self.__dm_threads[venue.id] = thread
        thread.start()

    def _start_end_condition_thread(self) -> None:
        thread = threading.Thread(
            target=self._run_end_condition_monitor,
            name="end-conditions",
            daemon=True,
        )
        with self.__state_lock:
            self.__end_condition_thread = thread
        thread.start()

    def _submit_startup_events(self) -> None:
        """提交首条权威事件，打破所有角色都等待首个观察的启动互锁。"""
        for venue in self.scenario.venues:
            phase = venue.session_phase
            if phase == SessionPhase.MEETING_ENDED:
                continue
            if phase in {
                SessionPhase.UNCHAIRED_CORE,
                SessionPhase.FREE_DISCUSSION,
            }:
                target_reps = set(venue.seats)
                activates_chair = False
                instruction = "请各代表根据当前议题开始磋商。"
            else:
                target_reps = set()
                activates_chair = True
                instruction = (
                    "请主席立即处理开场程序；有主持阶段应点名首位发言者，"
                    "休会阶段应决定是否继续休会或恢复会议。"
                )
            agenda = venue.current_agenda
            agenda_text = (
                f"当前议题为“{agenda.title}”（{agenda.id}）。"
                if agenda is not None
                else "当前没有议题。"
            )
            venue.submit_event(
                MeetingStartEvent(
                    f"会议开始。{agenda_text}{instruction}",
                    target_reps,
                    activates_chair,
                    venue.id,
                    self.scenario,
                )
            )

    def _publish_event_observation(
        self,
        event: Event,
        kind: ObservationKind,
        *,
        actor_id: str | None = None,
        recipients: set[str] | None = None,
        changed_field: str | None = None,
    ) -> None:
        """按角色可见性将权威状态变化路由给代表、主席与 DM。"""
        snapshot = snapshot_event(event)
        target_ids = set(event.scope) if recipients is None else set(recipients)
        with self.__state_lock:
            sequence = self.__observation_sequences.get(event.venue, 0) + 1
            self.__observation_sequences[event.venue] = sequence
            self.__end_condition_version += 1
            targets = {
                rep_id: self.__agents[rep_id]
                for rep_id in target_ids
                if rep_id in self.__agents
            }
            chair = self.__chair_agents.get(event.venue)
            dm = self.__dm_agents.get(event.venue)
        self.__end_condition_wakeup.set()

        for rep_id, agent in targets.items():
            if isinstance(event, MeetingStartEvent):
                activates_agent = rep_id in event.target_reps
            elif event.type == EventType.CHAIR:
                activates_agent = rep_id in snapshot.target_reps
            else:
                activates_agent = not (
                    kind == ObservationKind.EVENT_CREATED and actor_id == rep_id
                )
            agent.notify(
                Observation(
                    sequence=sequence,
                    kind=kind,
                    priority=self._observation_priority(event.type, kind),
                    activates_agent=activates_agent,
                    event=snapshot,
                    actor_id=actor_id,
                    changed_field=changed_field,
                )
            )

        if (
            chair is not None
            and actor_id != chair.venue.chair_actor_id()
            and (
                not isinstance(event, MeetingStartEvent)
                or event.activates_chair
            )
            and self._chair_can_observe(chair, event)
        ):
            chair.notify(
                Observation(
                    sequence=sequence,
                    kind=kind,
                    priority=self._observation_priority(event.type, kind),
                    activates_agent=True,
                    event=snapshot,
                    actor_id=actor_id,
                    changed_field=changed_field,
                )
            )

        instruction_task = (
            kind == ObservationKind.EVENT_CREATED
            and isinstance(event, InstructionEvent)
            and event.status == EventStatus.PENDING
        )
        resolution_task = (
            kind == ObservationKind.EVENT_STATUS_CHANGED
            and isinstance(event, ResolutionEvent)
            and event.status in {EventStatus.ACCEPTED, EventStatus.REJECTED}
        )
        if dm is not None and (instruction_task or resolution_task):
            dm.notify(
                Observation(
                    sequence=sequence,
                    kind=kind,
                    priority=ObservationPriority.NORMAL,
                    activates_agent=True,
                    event=snapshot,
                    actor_id=actor_id,
                    changed_field=changed_field,
                )
            )

    @staticmethod
    def _chair_can_observe(chair: ChairAgent, event: Event) -> bool:
        """主席不读纸条/私聊；代表主席不因主持身份扩大可见范围。"""
        if event.type in {EventType.NOTE, EventType.CHAT}:
            return False
        if isinstance(event, InstructionEvent):
            return False
        venue = chair.venue
        if venue.chair is not None:
            return venue.chair in event.scope
        if isinstance(event, ResolutionEvent):
            return True
        if event.type == EventType.SYSTEM:
            return event.scope == set(venue.seats)
        return True

    @staticmethod
    def _observation_priority(
        event_type: EventType,
        kind: ObservationKind,
    ) -> ObservationPriority:
        if kind == ObservationKind.EVENT_STATUS_CHANGED:
            return ObservationPriority.URGENT
        if event_type in {
            EventType.MEETING_START,
            EventType.SYSTEM,
            EventType.CHAIR,
            EventType.PHASE_SWITCH,
            EventType.SET_AGENDA,
            EventType.NOTE,
        }:
            return ObservationPriority.URGENT
        return ObservationPriority.NORMAL

    def _run_venue(self, engine: VenueEngine) -> None:
        try:
            engine.run()
        except BaseException as exc:
            failure = engine.venue.event_failure or exc
            error = self._normalize_failure(
                failure,
                f"会场 {engine.venue.id!r} 的 VenueEngine 收到致命异常",
            )
            with self.__state_lock:
                self.__venue_errors[engine.venue.id] = error
            self._request_stop()

    def _run_agent(self, agent: RepresentativeAgent) -> None:
        try:
            agent.run()
        except AgentStoppedError as exc:
            if self.stop_requested:
                return
            with self.__state_lock:
                self.__agent_errors[agent.rep.id] = exc
            self._request_stop()
        except BaseException as exc:
            error = self._normalize_failure(
                exc,
                f"代表 {agent.rep.id!r} 的 Agent 收到致命异常",
            )
            with self.__state_lock:
                self.__agent_errors[agent.rep.id] = error
            self._request_stop()

    def _run_chair(self, agent: ChairAgent) -> None:
        try:
            agent.run()
        except SystemAgentStoppedError as exc:
            if self.stop_requested:
                return
            with self.__state_lock:
                self.__chair_errors[agent.venue.id] = exc
            self._request_stop()
        except BaseException as exc:
            error = self._normalize_failure(
                exc,
                f"会场 {agent.venue.id!r} 的 ChairAgent 收到致命异常",
            )
            with self.__state_lock:
                self.__chair_errors[agent.venue.id] = error
            self._request_stop()

    def _run_dm(self, agent: DMAgent) -> None:
        try:
            agent.run()
        except SystemAgentStoppedError as exc:
            if self.stop_requested:
                return
            with self.__state_lock:
                self.__dm_errors[agent.venue.id] = exc
            self._request_stop()
        except BaseException as exc:
            error = self._normalize_failure(
                exc,
                f"会场 {agent.venue.id!r} 的 DMAgent 收到致命异常",
            )
            with self.__state_lock:
                self.__dm_errors[agent.venue.id] = error
            self._request_stop()

    def _run_end_conditions(self) -> None:
        """时间条件直接判断；文本条件只在权威事件版本变化后批量判断。"""
        evaluated_version = -1
        text_conditions = [
            (index, str(condition.content))
            for index, condition in enumerate(self.scenario.end_conditions)
            if condition.type == "text"
        ]

        while not self.stop_requested:
            for index, condition in enumerate(self.scenario.end_conditions):
                if condition.type != "time" or not condition.check():
                    continue
                self._finish_for_end_condition(
                    EndConditionMatch(
                        condition_index=index,
                        condition_type="time",
                        content=str(condition.content),
                        story_time=self.scenario.time.isoformat(),
                        reason="剧情时间已达到终局条件设定的截止时刻",
                    )
                )
                return

            with self.__state_lock:
                version = self.__end_condition_version
            evaluator = self.__text_end_condition_evaluator
            if evaluator is not None and text_conditions and version != evaluated_version:
                try:
                    evidence = build_end_condition_evidence(self.scenario)
                    matches = evaluator.evaluate(text_conditions, evidence)
                except LLMCancelledError:
                    if self.stop_requested:
                        return
                    raise
                except Exception as exc:
                    with self.__state_lock:
                        self.__end_condition_error = exc
                    # 同一版本在短暂退避后重试；不中止仍可继续运行的会议。
                    self.__end_condition_wakeup.wait(timeout=2.0)
                    self.__end_condition_wakeup.clear()
                    continue
                with self.__state_lock:
                    self.__end_condition_error = None
                evaluated_version = version
                if matches:
                    match = min(matches, key=lambda item: item.condition_index)
                    condition = self.scenario.end_conditions[match.condition_index]
                    self._finish_for_end_condition(
                        EndConditionMatch(
                            condition_index=match.condition_index,
                            condition_type="text",
                            content=str(condition.content),
                            story_time=self.scenario.time.isoformat(),
                            reason=match.reason,
                            evidence_event_ids=match.evidence_event_ids,
                        )
                    )
                    return

            self.__end_condition_wakeup.wait(timeout=0.5)
            self.__end_condition_wakeup.clear()

    def _run_end_condition_monitor(self) -> None:
        try:
            self._run_end_conditions()
        except BaseException as exc:
            error = self._normalize_failure(
                exc,
                "终局条件监视线程收到致命异常",
            )
            with self.__state_lock:
                self.__end_condition_fatal_error = error
            self._request_stop()

    def _finish_for_end_condition(self, match: EndConditionMatch) -> None:
        """记录终局，向各会场发布结束阶段事件，再协作停止全部线程。"""
        with self.__state_lock:
            if self.__end_condition_match is not None or self.stop_requested:
                return
            self.__end_condition_match = match

        for venue in self.scenario.venues:
            if venue.session_phase == SessionPhase.MEETING_ENDED:
                continue
            event = PhaseSwitchEvent(
                f"会议自动结束：终局条件 #{match.condition_index} 已成立。{match.reason}",
                SessionPhase.MEETING_ENDED,
                venue.id,
                set(venue.seats),
                self.scenario,
            )
            try:
                venue.submit_event(event)
            except Exception:
                if not self.stop_requested:
                    raise
        self._request_stop()

    def _request_stop(self) -> None:
        self.__stop_event.set()
        self.__end_condition_wakeup.set()
        with self.__state_lock:
            agents = list(self.__agents.values())
            chair_agents = list(self.__chair_agents.values())
            dm_agents = list(self.__dm_agents.values())
            engines = list(self.__venue_engines.values())
        for agent in agents:
            agent.stop()
        for agent in chair_agents:
            agent.stop()
        for agent in dm_agents:
            agent.stop()
        for engine in engines:
            engine.stop()
        evaluator = self.__text_end_condition_evaluator
        if evaluator is not None:
            evaluator.stop()

    def _collect_venue_failures(self) -> None:
        with self.__state_lock:
            engines = list(self.__venue_engines.values())
        for engine in engines:
            failure = engine.venue.event_failure
            if failure is None:
                continue
            error = self._normalize_failure(
                failure,
                f"会场 {engine.venue.id!r} 的 VenueEngine 收到致命异常",
            )
            with self.__state_lock:
                self.__venue_errors.setdefault(engine.venue.id, error)

    def _has_worker_errors(self) -> bool:
        with self.__state_lock:
            return bool(
                self.__venue_errors
                or self.__agent_errors
                or self.__chair_errors
                or self.__dm_errors
                or self.__end_condition_fatal_error
            )

    def _alive_threads(self) -> list[threading.Thread]:
        with self.__state_lock:
            threads = [
                *self.__venue_threads.values(),
                *self.__agent_threads.values(),
                *self.__chair_threads.values(),
                *self.__dm_threads.values(),
            ]
            if self.__end_condition_thread is not None:
                threads.append(self.__end_condition_thread)
        return [thread for thread in threads if thread.is_alive()]

    def _agent_role_threads(self) -> list[threading.Thread]:
        with self.__state_lock:
            return [
                *self.__agent_threads.values(),
                *self.__chair_threads.values(),
                *self.__dm_threads.values(),
            ]

    def _join_started_threads(self, deadline: float) -> None:
        for thread in self._alive_threads():
            thread.join(timeout=max(0.0, deadline - time.monotonic()))

    @staticmethod
    def _normalize_failure(exc: BaseException, message: str) -> Exception:
        if isinstance(exc, Exception):
            return exc
        error = RuntimeError(message)
        error.__cause__ = exc
        return error

    @staticmethod
    def _alive_thread_suffix(threads: list[threading.Thread]) -> str:
        if not threads:
            return ""
        names = ", ".join(thread.name for thread in threads)
        return f"；协作停止期限后仍存活: {names}"
