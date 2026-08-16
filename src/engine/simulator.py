from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from agent.inbox import (
    Observation,
    ObservationKind,
    ObservationPriority,
)
from agent.rep_agent import AgentStoppedError, RepresentativeAgent
from agent.rep_context import snapshot_event
from engine.venue_engine import VenueEngine
from event.event import EventType
from scenario.scenario import Scenario

if TYPE_CHECKING:
    from event.event import Event
    from llm import LLM
    from scenario.representative import Representative
    from scenario.venue import Venue


LLMFactory = Callable[["Representative"], "LLM | None"]


class Simulator:
    """场景级仿真器:为每个会场 / 代表启动独立线程运行引擎与 Agent."""

    scenario: Scenario
    __venue_engines: dict[str, VenueEngine]
    __venue_threads: dict[str, threading.Thread]
    __venue_errors: dict[str, Exception]
    __agents: dict[str, RepresentativeAgent]
    __agent_threads: dict[str, threading.Thread]
    __agent_errors: dict[str, Exception]
    __started: bool
    __stop_event: threading.Event
    __state_lock: threading.RLock
    __llm_factory: LLMFactory | None
    __observation_sequences: dict[str, int]

    def __init__(
        self,
        scenario: Scenario,
        *,
        llm_factory: LLMFactory | None = None,
    ) -> None:
        self.scenario = scenario
        self.__venue_engines = {}
        self.__venue_threads = {}
        self.__venue_errors = {}
        self.__agents = {}
        self.__agent_threads = {}
        self.__agent_errors = {}
        self.__started = False
        self.__stop_event = threading.Event()
        self.__state_lock = threading.RLock()
        self.__llm_factory = llm_factory
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
            self.__observation_sequences = {}
        self.__stop_event.clear()
        self.__started = True
        try:
            for venue in self.scenario.venues:
                self._start_venue_thread(venue)
            for rep in self.scenario.representatives:
                self._start_agent_thread(rep)
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
            elif not any(thread.is_alive() for thread in self.agent_threads.values()):
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

    def _publish_event_observation(
        self,
        event: Event,
        kind: ObservationKind,
        *,
        actor_id: str | None = None,
        recipients: set[str] | None = None,
        changed_field: str | None = None,
    ) -> None:
        """将一次已提交的权威状态变化投递给当时可见的代表。"""
        snapshot = snapshot_event(event)
        target_ids = set(event.scope) if recipients is None else set(recipients)
        with self.__state_lock:
            sequence = self.__observation_sequences.get(event.venue, 0) + 1
            self.__observation_sequences[event.venue] = sequence
            targets = {
                rep_id: self.__agents[rep_id]
                for rep_id in target_ids
                if rep_id in self.__agents
            }

        for rep_id, agent in targets.items():
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

    @staticmethod
    def _observation_priority(
        event_type: EventType,
        kind: ObservationKind,
    ) -> ObservationPriority:
        if kind == ObservationKind.EVENT_STATUS_CHANGED:
            return ObservationPriority.URGENT
        if event_type in {
            EventType.SYSTEM,
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

    def _request_stop(self) -> None:
        self.__stop_event.set()
        with self.__state_lock:
            agents = list(self.__agents.values())
            engines = list(self.__venue_engines.values())
        for agent in agents:
            agent.stop()
        for engine in engines:
            engine.stop()

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
            return bool(self.__venue_errors or self.__agent_errors)

    def _alive_threads(self) -> list[threading.Thread]:
        with self.__state_lock:
            threads = [
                *self.__venue_threads.values(),
                *self.__agent_threads.values(),
            ]
        return [thread for thread in threads if thread.is_alive()]

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
