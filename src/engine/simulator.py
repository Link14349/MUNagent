from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from engine.venue_engine import VenueEngine
from scenario.scenario import Scenario

if TYPE_CHECKING:
    from scenario.venue import Venue


class Simulator:
    """场景级仿真器:为每个会场启动独立线程运行 ``VenueEngine``."""

    scenario: Scenario
    __venue_engines: dict[str, VenueEngine]
    __venue_threads: dict[str, threading.Thread]
    __venue_errors: dict[str, Exception]
    __started: bool

    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
        self.__venue_engines = {}
        self.__venue_threads = {}
        self.__venue_errors = {}
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

    def run(self) -> None:
        """初始化场景,为每个会场开线程跑 ``VenueEngine.run``,并阻塞至全部结束."""
        self.start()
        self.join()

    def start(self) -> None:
        """初始化场景并启动各会场线程;不阻塞等待结束."""
        if self.__started:
            raise RuntimeError("Simulator 已启动会场线程,不能重复 start/run")
        if not self.scenario.venues:
            raise RuntimeError("场景无会场,无法启动 VenueEngine")

        self.scenario.initialize()
        self.__venue_errors = {}
        for venue in self.scenario.venues:
            self._start_venue_thread(venue)
        self.__started = True

    def join(self, timeout: float | None = None) -> None:
        """等待全部会场线程结束;任一线程超时或曾抛错则失败."""
        if not self.__started:
            raise RuntimeError("Simulator 尚未 start/run,没有可 join 的会场线程")

        deadline = None if timeout is None else time.monotonic() + timeout
        for venue_id, thread in self.__venue_threads.items():
            remaining = None
            if deadline is not None:
                remaining = max(0.0, deadline - time.monotonic())
            thread.join(timeout=remaining)
            if thread.is_alive():
                raise TimeoutError(
                    f"会场线程 {venue_id!r}(name={thread.name!r}) "
                    f"在 timeout={timeout!r} 内未结束"
                )

        if self.__venue_errors:
            venue_id, exc = next(iter(self.__venue_errors.items()))
            raise RuntimeError(
                f"会场 {venue_id!r} 的 VenueEngine 线程异常退出"
            ) from exc

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

    def _run_venue(self, engine: VenueEngine) -> None:
        try:
            engine.run()
        except Exception as exc:
            self.__venue_errors[engine.venue.id] = exc
