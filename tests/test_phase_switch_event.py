"""PhaseSwitchEvent：真正切换会场阶段；区别于 MotionSwitch 动议。"""

from __future__ import annotations

from pathlib import Path

import pytest

from event.event import (
    EventStatus,
    EventType,
    MotionSwitchEvent,
    PhaseSwitchEvent,
)
from scenario.scenario import Scenario
from scenario.venue import SessionPhase

TEMPLATE = Path(__file__).resolve().parent.parent / "scenario-template"


@pytest.fixture
def scenario() -> Scenario:
    loaded = Scenario()
    loaded.load(str(TEMPLATE))
    return loaded


@pytest.fixture
def venue_id(scenario: Scenario) -> str:
    return scenario.venues[0].id


def test_motion_switch_does_not_change_phase(
    scenario: Scenario, venue_id: str
) -> None:
    venue = scenario.venues[0]
    before = venue.session_phase
    motion = MotionSwitchEvent(
        "动议进入自由讨论",
        SessionPhase.FREE_DISCUSSION,
        venue_id,
        {rep.id for rep in scenario.representatives},
        scenario,
    )
    assert motion.type == EventType.MOTION_SWITCH
    assert motion.status == EventStatus.PENDING
    assert motion.target_phase == SessionPhase.FREE_DISCUSSION
    assert venue.session_phase == before


def test_phase_switch_applies_immediately(
    scenario: Scenario, venue_id: str
) -> None:
    venue = scenario.venues[0]
    before = venue.session_phase
    event = PhaseSwitchEvent(
        "进入自由讨论",
        SessionPhase.FREE_DISCUSSION,
        venue_id,
        {rep.id for rep in scenario.representatives},
        scenario,
    )
    assert event.type == EventType.PHASE_SWITCH
    assert event.status == EventStatus.COMPLETED
    assert event.previous_phase == before
    assert event.target_phase == SessionPhase.FREE_DISCUSSION
    assert venue.session_phase == SessionPhase.FREE_DISCUSSION
    assert event.time is None


def test_phase_switch_records_chain(scenario: Scenario, venue_id: str) -> None:
    venue = scenario.venues[0]
    first = PhaseSwitchEvent(
        "进入自由讨论",
        SessionPhase.FREE_DISCUSSION,
        venue_id,
        {rep.id for rep in scenario.representatives},
        scenario,
    )
    second = PhaseSwitchEvent(
        "休会",
        SessionPhase.RECESS,
        venue_id,
        {rep.id for rep in scenario.representatives},
        scenario,
    )
    assert first.target_phase == SessionPhase.FREE_DISCUSSION
    assert second.previous_phase == SessionPhase.FREE_DISCUSSION
    assert second.target_phase == SessionPhase.RECESS
    assert venue.session_phase == SessionPhase.RECESS


def test_phase_switch_completed_is_immutable(
    scenario: Scenario, venue_id: str
) -> None:
    event = PhaseSwitchEvent(
        "休会",
        SessionPhase.RECESS,
        venue_id,
        {rep.id for rep in scenario.representatives},
        scenario,
    )
    with pytest.raises(PermissionError, match="不能修改 content"):
        event.content = "篡改"
    with pytest.raises(PermissionError, match="不能修改 scope"):
        event.scope = set()
