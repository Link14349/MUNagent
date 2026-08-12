"""代表事件先提交给 Venue，由 Venue 暂时直接转交 EventList。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

import pytest

from event.event import Event, EventType, MessageEvent
from scenario.scenario import Scenario
from scenario.venue import SessionPhase

TEMPLATE = Path(__file__).resolve().parent.parent / "scenario-template"

CHURCHILL = "winston_churchill"
EDEN = "anthony_eden"


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


def test_venue_submit_event_forwards_to_event_list(scenario: Scenario) -> None:
    venue = scenario.venues[0]
    event = MessageEvent("测试转发", CHURCHILL, venue.id, scenario)

    venue.submit_event(event)

    assert venue.event_list is not None
    assert event.id is not None
    assert event in venue.event_list.get_events(CHURCHILL)


def test_representative_events_are_submitted_through_venue(
    scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    venue = scenario.venues[0]
    churchill = scenario.reps[CHURCHILL]
    forwarded: list[Event] = []
    direct_forward = venue.submit_event

    def record_and_forward(event: Event) -> None:
        forwarded.append(event)
        direct_forward(event)

    monkeypatch.setattr(venue, "submit_event", record_and_forward)

    churchill.send_message("公开发言")
    churchill.pass_note("私下沟通", EDEN)
    churchill.submit_motion_switch("动议自由讨论", SessionPhase.FREE_DISCUSSION)

    instruction = churchill.create_file("instruction.md", "执行内容", "测试指示")
    churchill.submit_instruction("提交指示", {CHURCHILL, EDEN}, instruction)

    resolution = churchill.create_file("resolution.md", "决议内容", "测试决议")
    churchill.submit_resolution("提交决议", {CHURCHILL, EDEN}, resolution)

    assert [event.type for event in forwarded] == [
        EventType.MESSAGE,
        EventType.NOTE,
        EventType.MOTION_SWITCH,
        EventType.INSTRUCTION,
        EventType.RESOLUTION,
    ]
    assert all(event.id is not None for event in forwarded)


def test_concurrent_submissions_are_committed_once_in_venue_engine(
    scenario: Scenario,
) -> None:
    venue = scenario.venues[0]
    assert venue.event_list is not None
    commit_threads: list[str] = []
    venue.event_list.add_listener(
        EventType.MESSAGE,
        lambda event: commit_threads.append(threading.current_thread().name),
    )

    events = [
        MessageEvent(f"并发发言 {index}", CHURCHILL, venue.id, scenario)
        for index in range(100)
    ]
    with ThreadPoolExecutor(max_workers=8) as executor:
        committed = list(executor.map(venue.submit_event, events))

    assert committed == events
    assert sorted(event.id for event in events if event.id is not None) == list(
        range(100)
    )
    assert set(venue.event_list.events) == set(events)
    assert len(commit_threads) == 100
    assert set(commit_threads) == {f"test-venue:{venue.id}"}


def test_submission_error_returns_to_caller_and_engine_continues(
    scenario: Scenario,
) -> None:
    venue = scenario.venues[0]
    invalid = MessageEvent("预设编号", CHURCHILL, venue.id, scenario)
    invalid.id = 9

    with pytest.raises(ValueError, match="应由 EventList._commit_event 设定"):
        venue.submit_event(invalid)

    valid = MessageEvent("错误后继续", CHURCHILL, venue.id, scenario)
    assert venue.submit_event(valid) is valid
    assert valid.id == 0
