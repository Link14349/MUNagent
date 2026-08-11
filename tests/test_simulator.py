"""Simulator:按会场开线程运行 VenueEngine."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.simulator import Simulator
from engine.venue_engine import VenueEngine
from scenario.scenario import Scenario

TEMPLATE = Path(__file__).resolve().parent.parent / "scenario-template"


@pytest.fixture
def scenario(tmp_path: Path) -> Scenario:
    loaded = Scenario()
    loaded.load(str(TEMPLATE))
    loaded.root_path = tmp_path
    (tmp_path / "simulation").mkdir()
    return loaded


def test_simulator_run_starts_venue_threads_and_joins(scenario: Scenario) -> None:
    sim = Simulator(scenario)
    assert scenario.venues
    venue_ids = [venue.id for venue in scenario.venues]

    sim.run()

    assert scenario.filesystem is not None
    assert scenario.event_list is not None
    assert set(sim.venue_engines) == set(venue_ids)
    assert set(sim.venue_threads) == set(venue_ids)
    for venue_id, engine in sim.venue_engines.items():
        assert isinstance(engine, VenueEngine)
        assert engine.venue.id == venue_id
        assert engine.simulator is sim
    for thread in sim.venue_threads.values():
        assert not thread.is_alive()
    assert sim.venue_errors == {}


def test_simulator_start_join_separate(scenario: Scenario) -> None:
    sim = Simulator(scenario)
    sim.start()
    assert scenario.filesystem is not None
    assert len(sim.venue_threads) == len(scenario.venues)
    sim.join()
    assert all(not t.is_alive() for t in sim.venue_threads.values())


def test_simulator_rejects_double_start(scenario: Scenario) -> None:
    sim = Simulator(scenario)
    sim.start()
    with pytest.raises(RuntimeError, match="已启动会场线程"):
        sim.start()
    sim.join()


def test_simulator_join_before_start_fails(scenario: Scenario) -> None:
    sim = Simulator(scenario)
    with pytest.raises(RuntimeError, match="尚未 start"):
        sim.join()


def test_simulator_surfaces_venue_engine_error(scenario: Scenario) -> None:
    sim = Simulator(scenario)

    def boom(self: VenueEngine) -> None:
        raise ValueError(f"会场 {self.venue.id} 故意失败")

    original = VenueEngine.run
    VenueEngine.run = boom  # type: ignore[method-assign]
    try:
        with pytest.raises(RuntimeError, match="VenueEngine 线程异常退出") as caught:
            sim.run()
        assert isinstance(caught.value.__cause__, ValueError)
        assert sim.venue_errors
    finally:
        VenueEngine.run = original  # type: ignore[method-assign]
