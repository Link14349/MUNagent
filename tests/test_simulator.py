"""Simulator:按会场 / 代表开线程运行 VenueEngine 与 Agent."""

from __future__ import annotations

from pathlib import Path
import threading

import pytest

from agent.rep_agent import RepresentativeAgent
from agent.chair_agent import ChairAgent
from agent.inbox import ObservationKind, ObservationPriority
from engine.simulator import Simulator
from engine.venue_engine import VenueEngine
from scenario.scenario import Scenario
from scenario.venue import SessionPhase, Venue, VenueEngineStoppedError

TEMPLATE = Path(__file__).resolve().parent.parent / "scenario-template"


@pytest.fixture
def scenario(tmp_path: Path) -> Scenario:
    loaded = Scenario()
    loaded.load(str(TEMPLATE))
    loaded.root_path = tmp_path
    (tmp_path / "simulation").mkdir()
    return loaded


def test_simulator_run_starts_venue_and_agent_threads(scenario: Scenario) -> None:
    sim = Simulator(scenario)
    assert scenario.venues
    assert scenario.representatives
    venue_ids = [venue.id for venue in scenario.venues]
    rep_ids = [rep.id for rep in scenario.representatives]

    sim.run()

    assert scenario.filesystem is not None
    assert all(venue.event_list is not None for venue in scenario.venues)
    assert set(sim.venue_engines) == set(venue_ids)
    assert set(sim.venue_threads) == set(venue_ids)
    assert set(sim.agents) == set(rep_ids)
    assert set(sim.agent_threads) == set(rep_ids)
    for venue_id, engine in sim.venue_engines.items():
        assert isinstance(engine, VenueEngine)
        assert engine.venue.id == venue_id
        assert engine.simulator is sim
    for rep_id, agent in sim.agents.items():
        assert isinstance(agent, RepresentativeAgent)
        assert agent.rep.id == rep_id
    for thread in (*sim.venue_threads.values(), *sim.agent_threads.values()):
        assert not thread.is_alive()
    assert sim.venue_errors == {}
    assert sim.agent_errors == {}


def test_simulator_start_join_separate(scenario: Scenario) -> None:
    sim = Simulator(scenario)
    sim.start()
    assert scenario.filesystem is not None
    assert len(sim.venue_threads) == len(scenario.venues)
    assert len(sim.agent_threads) == len(scenario.representatives)
    sim.join()
    assert all(not t.is_alive() for t in sim.venue_threads.values())
    assert all(not t.is_alive() for t in sim.agent_threads.values())


def test_simulator_agents_submit_through_running_venue_engine(
    scenario: Scenario,
) -> None:
    sim = Simulator(scenario)

    def submit_message(self: RepresentativeAgent) -> None:
        self.rep.send_message(f"{self.rep.id} 线程发言")

    original = RepresentativeAgent.run
    RepresentativeAgent.run = submit_message  # type: ignore[method-assign]
    try:
        sim.run()
    finally:
        RepresentativeAgent.run = original  # type: ignore[method-assign]

    event_list = scenario.venues[0].event_list
    assert event_list is not None
    events = event_list.get_events("__GOD__")
    messages = [event for event in events if event.type.value == "message"]
    startup = [event for event in events if event.type.value == "meeting_start"]
    assert len(messages) == len(scenario.representatives)
    assert len(startup) == 1
    assert sorted(event.id for event in events if event.id is not None) == list(
        range(len(scenario.representatives) + 1)
    )


def test_venue_engine_publishes_observations_without_self_activation(
    scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received = []

    def record(self: RepresentativeAgent, observation) -> bool:
        received.append((self.rep.id, observation))
        return True

    monkeypatch.setattr(RepresentativeAgent, "notify", record)
    sim = Simulator(scenario)
    sim.start()

    event = scenario.reps["winston_churchill"].submit_motion_switch(
        "提议进入无主持核心磋商",
        "unchaired_core",
    )
    event.content = "修订：提议立即进入无主持核心磋商"
    event.status = "accepted"
    sim.stop()
    sim.join(timeout=2.0)

    created = [
        item
        for item in received
        if item[1].kind == ObservationKind.EVENT_CREATED
        and item[1].event.id == event.id
    ]
    status_updates = [
        item
        for item in received
        if item[1].kind == ObservationKind.EVENT_STATUS_CHANGED
    ]
    edits = [
        item for item in received if item[1].kind == ObservationKind.EVENT_EDITED
    ]
    assert {rep_id for rep_id, _ in created} == set(scenario.venues[0].seats)
    assert len({observation.sequence for _, observation in created}) == 1
    own = next(
        observation
        for rep_id, observation in created
        if rep_id == "winston_churchill"
    )
    assert own.actor_id == "winston_churchill"
    assert own.activates_agent is False
    assert all(
        observation.activates_agent
        for rep_id, observation in created
        if rep_id != "winston_churchill"
    )
    assert len(edits) == len(scenario.venues[0].seats)
    assert all(observation.changed_field == "content" for _, observation in edits)
    assert all("修订" in observation.event.content for _, observation in edits)
    assert len(status_updates) == len(scenario.venues[0].seats)
    assert all(
        observation.priority == ObservationPriority.URGENT
        for _, observation in status_updates
    )


def test_unchaired_startup_event_activates_all_representatives_only(
    scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rep_received = []
    chair_received = []

    monkeypatch.setattr(
        RepresentativeAgent,
        "notify",
        lambda self, observation: rep_received.append((self.rep.id, observation))
        or True,
    )
    monkeypatch.setattr(
        ChairAgent,
        "notify",
        lambda self, observation: chair_received.append(observation) or True,
    )
    simulator = Simulator(scenario)

    simulator.start()
    simulator.join(timeout=2.0)

    startup = [
        (rep_id, observation)
        for rep_id, observation in rep_received
        if observation.event.event_type == "meeting_start"
    ]
    assert {rep_id for rep_id, _ in startup} == set(scenario.venues[0].seats)
    assert all(observation.activates_agent for _, observation in startup)
    assert all(
        observation.event.event_type != "meeting_start"
        for observation in chair_received
    )


def test_chaired_startup_event_activates_chair_not_representatives(
    scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario.venues[0].switch_phase(SessionPhase.CHAIRED_CORE)
    rep_received = []
    chair_received = []

    monkeypatch.setattr(
        RepresentativeAgent,
        "notify",
        lambda self, observation: rep_received.append((self.rep.id, observation))
        or True,
    )
    monkeypatch.setattr(
        ChairAgent,
        "notify",
        lambda self, observation: chair_received.append(observation) or True,
    )
    simulator = Simulator(scenario)

    simulator.start()
    simulator.join(timeout=2.0)

    startup_reps = [
        observation
        for _, observation in rep_received
        if observation.event.event_type == "meeting_start"
    ]
    startup_chair = [
        observation
        for observation in chair_received
        if observation.event.event_type == "meeting_start"
    ]
    assert len(startup_reps) == len(scenario.venues[0].seats)
    assert all(not observation.activates_agent for observation in startup_reps)
    assert len(startup_chair) == 1
    assert startup_chair[0].activates_agent is True


def test_simulator_rejects_double_start(scenario: Scenario) -> None:
    sim = Simulator(scenario)
    sim.start()
    with pytest.raises(RuntimeError, match="已启动线程"):
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


def test_simulator_surfaces_agent_error(scenario: Scenario) -> None:
    sim = Simulator(scenario)

    def boom(self: RepresentativeAgent) -> None:
        raise ValueError(f"代表 {self.rep.id} 故意失败")

    original = RepresentativeAgent.run
    RepresentativeAgent.run = boom  # type: ignore[method-assign]
    try:
        with pytest.raises(RuntimeError, match="Agent 线程异常退出") as caught:
            sim.run()
        assert isinstance(caught.value.__cause__, ValueError)
        assert sim.agent_errors
    finally:
        RepresentativeAgent.run = original  # type: ignore[method-assign]


def test_venue_failure_unblocks_agents_and_ends_simulation(
    scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FatalVenueFailure(BaseException):
        pass

    fatal = FatalVenueFailure("VenueEngine 致命故障")

    def fail_commit(self: Venue, submission) -> None:
        raise fatal

    def submit_message(self: RepresentativeAgent) -> None:
        self.rep.send_message(f"{self.rep.id} 等待故障结果")

    monkeypatch.setattr(Venue, "_commit_event", fail_commit)
    monkeypatch.setattr(RepresentativeAgent, "run", submit_message)
    sim = Simulator(scenario)
    sim.start()

    with pytest.raises(RuntimeError, match="VenueEngine 线程异常退出"):
        sim.join(timeout=3.0)

    assert all(not thread.is_alive() for thread in sim.venue_threads.values())
    assert all(not thread.is_alive() for thread in sim.agent_threads.values())
    assert sim.venue_errors
    assert len(sim.agent_errors) == len(scenario.representatives)
    assert all(
        isinstance(error, VenueEngineStoppedError)
        for error in sim.agent_errors.values()
    )


def test_agent_failure_requests_global_cooperative_stop(
    scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def run_until_stopped(self: RepresentativeAgent) -> None:
        if self.rep.id == "winston_churchill":
            raise ValueError("Agent 主循环故意失败")
        if not self.wait_until_stopped(timeout=2.0):
            raise TimeoutError("未收到 Simulator 全局停止信号")

    monkeypatch.setattr(RepresentativeAgent, "run", run_until_stopped)
    sim = Simulator(scenario)

    with pytest.raises(RuntimeError, match="Agent 线程异常退出"):
        sim.run()

    assert sim.stop_requested
    assert all(not thread.is_alive() for thread in sim.agent_threads.values())
    assert all(not thread.is_alive() for thread in sim.venue_threads.values())


def test_simulator_stop_wakes_waiting_agents(
    scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def run_until_stopped(self: RepresentativeAgent) -> None:
        if not self.wait_until_stopped(timeout=2.0):
            raise TimeoutError("未收到 Simulator.stop 信号")

    monkeypatch.setattr(RepresentativeAgent, "run", run_until_stopped)
    sim = Simulator(scenario)
    sim.start()
    sim.stop()
    sim.join(timeout=2.0)

    assert sim.stop_requested
    assert sim.agent_errors == {}
    assert sim.venue_errors == {}


def test_join_timeout_still_requests_cleanup(
    scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()

    def ignore_stop_temporarily(self: RepresentativeAgent) -> None:
        release.wait(timeout=2.0)

    monkeypatch.setattr(RepresentativeAgent, "run", ignore_stop_temporarily)
    sim = Simulator(scenario)
    sim.shutdown_grace_s = 0.05
    sim.start()

    with pytest.raises(TimeoutError, match="未在期限内结束"):
        sim.join(timeout=0.01)

    assert sim.stop_requested
    assert all(not thread.is_alive() for thread in sim.venue_threads.values())
    release.set()
    for thread in sim.agent_threads.values():
        thread.join(timeout=2.0)
