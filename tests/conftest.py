from __future__ import annotations

import threading
from typing import TYPE_CHECKING, cast

import pytest

from engine.venue_engine import VenueEngine
from scenario.venue import Venue

if TYPE_CHECKING:
    from engine.simulator import Simulator


class VenueEngineRunner:
    """为不经过 Simulator 的单元测试管理 VenueEngine 线程."""

    def __init__(self) -> None:
        self.engines: list[VenueEngine] = []
        self.threads: list[threading.Thread] = []

    def start(self, venue: Venue) -> VenueEngine:
        engine = VenueEngine(cast("Simulator", None), venue)
        thread = threading.Thread(
            target=engine.run,
            name=f"test-venue:{venue.id}",
            daemon=False,
        )
        self.engines.append(engine)
        self.threads.append(thread)
        thread.start()
        if not engine.wait_until_started(timeout=2.0):
            raise TimeoutError(f"测试 VenueEngine {venue.id!r} 启动超时")
        return engine

    def close(self) -> None:
        for engine in self.engines:
            engine.stop()
        for thread in self.threads:
            thread.join(timeout=2.0)
            if thread.is_alive():
                raise TimeoutError(f"测试 VenueEngine {thread.name!r} 停止超时")


@pytest.fixture
def venue_engine_runner() -> VenueEngineRunner:
    runner = VenueEngineRunner()
    try:
        yield runner
    finally:
        runner.close()
