"""事件属性编辑权限：PENDING 可改；time/id/type/venue 不可变。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from event.event import (
    EventStatus,
    EventType,
    MotionSwitchEvent,
    VoteEvent,
    VotePassMode,
)
from event.eventlist import EventList
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


def test_pending_event_allows_edits(scenario: Scenario, venue_id: str) -> None:
    event = MotionSwitchEvent(
        "动议",
        SessionPhase.FREE_DISCUSSION,
        venue_id,
        {rep.id for rep in scenario.representatives},
        scenario,
    )
    assert event.status == EventStatus.PENDING
    assert event.venue == venue_id
    assert event.time is None
    event.content = "更新后的动议说明"
    event.target_phase = SessionPhase.RECESS
    event.status = EventStatus.COMPLETED
    assert event.content == "更新后的动议说明"
    assert event.target_phase == SessionPhase.RECESS


def test_non_pending_rejects_edits(scenario: Scenario, venue_id: str) -> None:
    event = MotionSwitchEvent(
        "动议",
        SessionPhase.FREE_DISCUSSION,
        venue_id,
        {rep.id for rep in scenario.representatives},
        scenario,
    )
    event.status = EventStatus.COMPLETED
    with pytest.raises(PermissionError, match="不能修改 content"):
        event.content = "再改"
    with pytest.raises(PermissionError, match="不能修改 target_phase"):
        event.target_phase = SessionPhase.RECESS
    with pytest.raises(PermissionError, match="不能修改 status"):
        event.status = EventStatus.PENDING


def test_time_type_venue_immutable_id_assign_once(scenario: Scenario, venue_id: str) -> None:
    event = MotionSwitchEvent(
        "动议",
        SessionPhase.FREE_DISCUSSION,
        venue_id,
        {rep.id for rep in scenario.representatives},
        scenario,
    )
    assert event.type == EventType.MOTION_SWITCH
    assert event.venue == venue_id
    assert event.time is None
    assert event.id is None

    stamped = datetime(1944, 10, 9, 22, 0, tzinfo=timezone.utc)
    event.time = stamped
    assert event.time == stamped
    with pytest.raises(PermissionError, match="time 不可修改"):
        event.time = datetime(1944, 10, 10, tzinfo=timezone.utc)

    with pytest.raises(AttributeError):
        event.type = EventType.VOTE  # type: ignore[misc]
    with pytest.raises(AttributeError):
        event.venue = "other_venue"  # type: ignore[misc]

    event.id = 0
    assert event.id == 0
    with pytest.raises(PermissionError, match="id 不可修改"):
        event.id = 1

    done = VoteEvent(
        "表决",
        venue_id,
        {rep.id for rep in scenario.representatives},
        event,
        valid_votes=1,
        pass_mode=VotePassMode.UNANIMOUS,
        scenario=scenario,
        supporters=["winston_churchill"],
        passed=True,
    )
    assert done.status == EventStatus.COMPLETED
    assert done.venue == venue_id
    assert done.time is None
    done.id = 7
    with pytest.raises(PermissionError, match="id 不可修改"):
        done.id = 8


def test_event_list_add_stamps_time_and_id(scenario: Scenario, venue_id: str) -> None:
    events = EventList(scenario)
    event = MotionSwitchEvent(
        "动议",
        SessionPhase.FREE_DISCUSSION,
        venue_id,
        {rep.id for rep in scenario.representatives},
        scenario,
    )
    events.submit_event(event)
    assert event.time == scenario.start_time == events.time
    assert event.id == 0

    with pytest.raises(ValueError, match="应由 EventList.submit_event 设定"):
        events.submit_event(event)


def test_event_list_time_pass(scenario: Scenario) -> None:
    events = EventList(scenario)
    assert scenario.start_time is not None
    start = scenario.start_time
    events.time_pass(timedelta(minutes=30))
    assert events.time == start + timedelta(minutes=30)

    with pytest.raises(ValueError, match="不可为负"):
        events.time_pass(timedelta(seconds=-1))
    with pytest.raises(TypeError, match="timedelta"):
        events.time_pass(30)  # type: ignore[arg-type]
