"""事件属性编辑权限:PENDING 可改;time/id/type/venue 不可变."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading

import pytest

from event.event import (
    EventStatus,
    EventType,
    MessageEvent,
    MotionSwitchEvent,
    VoteEvent,
    VotePassMode,
)
from scenario.scenario import Scenario
from scenario.venue import EventEdit, EventStatusUpdate, SessionPhase

TEMPLATE = Path(__file__).resolve().parent.parent / "scenario-template"


@pytest.fixture
def scenario(tmp_path: Path, venue_engine_runner) -> Scenario:
    loaded = Scenario()
    loaded.load(str(TEMPLATE))
    loaded.root_path = tmp_path
    (tmp_path / "simulation").mkdir()
    loaded.initialize()
    for venue in loaded.venues:
        venue_engine_runner.start(venue)
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
    venue = scenario.venues[0]
    assert venue.event_list is not None
    event = MotionSwitchEvent(
        "动议",
        SessionPhase.FREE_DISCUSSION,
        venue_id,
        {rep.id for rep in scenario.representatives},
        scenario,
    )
    venue.submit_event(event)
    assert event.time == scenario.start_time == scenario.time
    assert event.id == 0

    with pytest.raises(ValueError, match="应由 EventList._commit_event 设定"):
        venue.event_list._commit_event(event)


def test_event_list_time_pass(scenario: Scenario) -> None:
    assert scenario.start_time is not None
    start = scenario.start_time
    scenario.time_pass(timedelta(minutes=30))
    assert scenario.time == start + timedelta(minutes=30)

    with pytest.raises(ValueError, match="不可为负"):
        scenario.time_pass(timedelta(seconds=-1))
    with pytest.raises(TypeError, match="timedelta"):
        scenario.time_pass(30)  # type: ignore[arg-type]


def test_submitted_event_edit_runs_in_venue_engine(
    scenario: Scenario,
    venue_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    venue = scenario.venues[0]
    event = MotionSwitchEvent(
        "原始动议",
        SessionPhase.FREE_DISCUSSION,
        venue_id,
        {rep.id for rep in scenario.representatives},
        scenario,
    )
    venue.submit_event(event)
    edit_threads: list[str] = []
    original = venue._commit_event_edit

    def record(edit: EventEdit) -> None:
        edit_threads.append(threading.current_thread().name)
        original(edit)

    monkeypatch.setattr(venue, "_commit_event_edit", record)
    event.content = "队列更新后的动议"

    assert event.content == "队列更新后的动议"
    assert edit_threads == [f"test-venue:{venue.id}"]


def test_status_and_field_edit_follow_same_queue_order(
    scenario: Scenario,
    venue_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    venue = scenario.venues[0]
    assert venue.event_list is not None
    event = MotionSwitchEvent(
        "保持不变",
        SessionPhase.FREE_DISCUSSION,
        venue_id,
        {rep.id for rep in scenario.representatives},
        scenario,
    )
    venue.submit_event(event)

    entered = threading.Event()
    release = threading.Event()
    status_queued = threading.Event()
    edit_queued = threading.Event()

    def block(blocking_event) -> None:
        if blocking_event.content == "占用 VenueEngine":
            entered.set()
            release.wait(timeout=2.0)

    venue.event_list.add_listener(EventType.MESSAGE, block)
    original_submit = venue._submit_command

    def record_submit(command) -> None:
        original_submit(command)
        if isinstance(command, EventStatusUpdate):
            status_queued.set()
        elif isinstance(command, EventEdit):
            edit_queued.set()

    monkeypatch.setattr(venue, "_submit_command", record_submit)

    with ThreadPoolExecutor(max_workers=3) as executor:
        blocker = executor.submit(
            venue.submit_event,
            MessageEvent("占用 VenueEngine", "winston_churchill", venue.id, scenario),
        )
        assert entered.wait(timeout=2.0)
        status_result = executor.submit(
            setattr,
            event,
            "status",
            EventStatus.COMPLETED,
        )
        assert status_queued.wait(timeout=2.0)
        edit_result = executor.submit(setattr, event, "content", "不应写入")
        assert edit_queued.wait(timeout=2.0)
        release.set()

        blocker.result(timeout=2.0)
        status_result.result(timeout=2.0)
        with pytest.raises(PermissionError, match="不能修改 content"):
            edit_result.result(timeout=2.0)

    assert event.status == EventStatus.COMPLETED
    assert event.content == "保持不变"
