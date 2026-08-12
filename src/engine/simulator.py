from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from agent.rep_agent import RepresentativeAgent
from engine.venue_engine import VenueEngine
from scenario.scenario import Scenario

if TYPE_CHECKING:
    from scenario.representative import Representative
    from scenario.venue import Venue


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

    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
        self.__venue_engines = {}
        self.__venue_threads = {}
        self.__venue_errors = {}
        self.__agents = {}
        self.__agent_threads = {}
        self.__agent_errors = {}
        self.__started = False

    @property
    def venue_engines(self) -> dict[str, VenueEngine]:
        """会场引擎句柄(副本;键为 venue id)."""
        return dict(self.__venue_engines)

    @property
    def venue_threads(self) -> dict[str, threading.Thread]:
        """会场线程句柄(副本;键为 venue id)."""
        return dict(self.__venue_threads)

    @property
    def venue_errors(self) -> dict[str, Exception]:
        """会场线程捕获到的异常(副本;键为 venue id)."""
        return dict(self.__venue_errors)

    @property
    def agents(self) -> dict[str, RepresentativeAgent]:
        """代表 Agent 句柄(副本;键为 rep id)."""
        return dict(self.__agents)

    @property
    def agent_threads(self) -> dict[str, threading.Thread]:
        """代表 Agent 线程句柄(副本;键为 rep id)."""
        return dict(self.__agent_threads)

    @property
    def agent_errors(self) -> dict[str, Exception]:
        """代表 Agent 线程捕获到的异常(副本;键为 rep id)."""
        return dict(self.__agent_errors)

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
        self.__venue_errors = {}
        self.__agent_errors = {}
        for venue in self.scenario.venues:
            self._start_venue_thread(venue)
        for rep in self.scenario.representatives:
            self._start_agent_thread(rep)
        self.__started = True

    def join(self, timeout: float | None = None) -> None:
        """等待全部会场与代表线程结束;任一线程超时或曾抛错则失败."""
        if not self.__started:
            raise RuntimeError("Simulator 尚未 start/run,没有可 join 的线程")

        deadline = None if timeout is None else time.monotonic() + timeout
        self._join_threads(self.__agent_threads, kind="rep", deadline=deadline)
        for engine in self.__venue_engines.values():
            engine.stop()
        self._join_threads(self.__venue_threads, kind="venue", deadline=deadline)

        if self.__venue_errors:
            venue_id, exc = next(iter(self.__venue_errors.items()))
            raise RuntimeError(
                f"会场 {venue_id!r} 的 VenueEngine 线程异常退出"
            ) from exc
        if self.__agent_errors:
            rep_id, exc = next(iter(self.__agent_errors.items()))
            raise RuntimeError(
                f"代表 {rep_id!r} 的 Agent 线程异常退出"
            ) from exc

    def _join_threads(
        self,
        threads: dict[str, threading.Thread],
        *,
        kind: str,
        deadline: float | None,
    ) -> None:
        for key, thread in threads.items():
            remaining = None
            if deadline is not None:
                remaining = max(0.0, deadline - time.monotonic())
            thread.join(timeout=remaining)
            if thread.is_alive():
                raise TimeoutError(
                    f"{kind} thread {key!r}(name={thread.name!r}) "
                    f"did not finish before deadline"
                )

    def _start_venue_thread(self, venue: Venue) -> None:
        if venue.id in self.__venue_threads:
            raise RuntimeError(f"会场 {venue.id!r} 的线程已存在,不能重复启动")
        engine = VenueEngine(self, venue)
        thread = threading.Thread(
            target=self._run_venue,
            args=(engine,),
            name=f"venue:{venue.id}",
            daemon=False,
        )
        self.__venue_engines[venue.id] = engine
        self.__venue_threads[venue.id] = thread
        thread.start()
        deadline = time.monotonic() + 5.0
        while not engine.wait_until_started(timeout=0.01):
            if not thread.is_alive():
                exc = self.__venue_errors.get(venue.id)
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
        agent = RepresentativeAgent(rep)
        thread = threading.Thread(
            target=self._run_agent,
            args=(agent,),
            name=f"agent:{rep.id}",
            daemon=False,
        )
        self.__agents[rep.id] = agent
        self.__agent_threads[rep.id] = thread
        thread.start()

    def _run_venue(self, engine: VenueEngine) -> None:
        try:
            engine.run()
        except Exception as exc:
            self.__venue_errors[engine.venue.id] = exc

    def _run_agent(self, agent: RepresentativeAgent) -> None:
        try:
            agent.run()
        except Exception as exc:
            self.__agent_errors[agent.rep.id] = exc
