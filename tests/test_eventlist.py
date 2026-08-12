"""Scenario 统一时钟与 Venue 私有 EventList 的运行时边界。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from condition.condition import Condition
from event.event import (
    Event,
    EventStatus,
    EventType,
    InstructionEvent,
    MessageEvent,
    MotionSwitchEvent,
    NoteEvent,
    SystemEvent,
)
from event.eventlist import EventList, PullUpEvent
from scenario.scenario import Scenario
from scenario.venue import SessionPhase, Venue

TEMPLATE = Path(__file__).resolve().parent.parent / "scenario-template"

CHURCHILL = "winston_churchill"
STALIN = "joseph_stalin"
EDEN = "anthony_eden"
MOLOTOV = "vyacheslav_molotov"


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
def venue(scenario: Scenario) -> Venue:
    return scenario.venues[0]


@pytest.fixture
def events(venue: Venue) -> EventList:
    assert venue.event_list is not None
    return venue.event_list


def test_initialize_binds_time_and_event_list_per_venue(scenario: Scenario) -> None:
    time_pool = [event for event in scenario.event_pool if event.condition.type == "time"]

    assert scenario.time == scenario.start_time
    assert len(time_pool) == 3
    assert scenario.pullup_events == time_pool
    for venue in scenario.venues:
        assert venue.event_list is not None
        assert venue.event_list.venue is venue
        assert venue.event_list.events == []


def test_event_list_public_submit_uses_venue_queue(
    scenario: Scenario,
    venue: Venue,
    events: EventList,
) -> None:
    submitted = MessageEvent("经事件表入口提交", CHURCHILL, venue.id, scenario)

    result = events.submit_event(submitted)

    assert result is submitted
    assert submitted.id == 0
    assert submitted.time == scenario.time == scenario.start_time


def test_venue_rejects_preassigned_time_and_event_list_rejects_id(
    scenario: Scenario,
    venue: Venue,
    events: EventList,
) -> None:
    stamped = SystemEvent("预设时间", [], venue.id, {CHURCHILL}, scenario)
    stamped.time = scenario.time
    with pytest.raises(ValueError, match="应由 Scenario 设定"):
        venue.submit_event(stamped)

    numbered = SystemEvent("预设编号", [], venue.id, {CHURCHILL}, scenario)
    numbered.time = scenario.time
    numbered.id = 99
    with pytest.raises(ValueError, match="应由 EventList._commit_event 设定"):
        events._commit_event(numbered)


def test_venue_initialize_rejects_reentry(venue: Venue) -> None:
    with pytest.raises(RuntimeError, match="不能重复初始化"):
        venue.initialize()


def test_submit_event_notifies_local_listeners_in_order(
    scenario: Scenario,
    venue: Venue,
    events: EventList,
) -> None:
    seen_notes: list[Event] = []
    order: list[str] = []
    events.add_listener(EventType.NOTE, lambda event: seen_notes.append(event))
    events.add_listener(EventType.NOTE, lambda event: order.append("a"))
    events.add_listener(EventType.NOTE, lambda event: order.append("b"))

    note = NoteEvent("私下试探", CHURCHILL, {EDEN}, venue.id, scenario)
    venue.submit_event(note)

    assert seen_notes == [note]
    assert order == ["a", "b"]


def test_event_list_rejects_event_from_another_venue(
    scenario: Scenario,
    events: EventList,
    venue_engine_runner,
) -> None:
    side = _add_side_venue(scenario, venue_engine_runner)
    foreign = MessageEvent("侧会场发言", CHURCHILL, side.id, scenario)

    with pytest.raises(ValueError, match="不能提交给会场"):
        events.submit_event(foreign)


def test_get_events_filters_by_scope(
    scenario: Scenario,
    venue: Venue,
    events: EventList,
) -> None:
    public = SystemEvent(
        "全员通报",
        [],
        venue.id,
        {CHURCHILL, STALIN, EDEN, MOLOTOV},
        scenario,
    )
    private = NoteEvent("仅丘艾可见", CHURCHILL, {EDEN}, venue.id, scenario)
    secret = NoteEvent("仅丘斯可见", CHURCHILL, {STALIN}, venue.id, scenario)
    for event in (public, private, secret):
        venue.submit_event(event)

    assert [event.content for event in events.get_events(CHURCHILL)] == [
        "全员通报",
        "仅丘艾可见",
        "仅丘斯可见",
    ]
    assert [event.content for event in events.get_events(EDEN)] == [
        "全员通报",
        "仅丘艾可见",
    ]
    assert [event.content for event in events.get_events(STALIN)] == [
        "全员通报",
        "仅丘斯可见",
    ]
    assert [event.content for event in events.get_events(MOLOTOV)] == ["全员通报"]
    assert events.get_events("__GOD__") == [public, private, secret]


def test_scenario_pull_up_rejects_non_time_and_skips_past(
    scenario: Scenario,
) -> None:
    text_pull = PullUpEvent(
        Condition("text", "会场已形成草案", scenario),
        "不该挂载",
        scenario,
    )
    with pytest.raises(ValueError, match="time condition"):
        scenario.pull_up_event(text_pull)

    past = PullUpEvent(
        Condition("time", scenario.time - timedelta(minutes=1), scenario),
        "过期事件",
        scenario,
    )
    before = scenario.pullup_events
    scenario.pull_up_event(past)
    assert scenario.pullup_events == before


def test_scenario_time_fires_due_events_into_each_venue(
    scenario: Scenario,
    venue: Venue,
    venue_engine_runner,
) -> None:
    side = _add_side_venue(scenario, venue_engine_runner)
    moscow = ZoneInfo("Europe/Moscow")
    first_due = datetime(1944, 10, 9, 22, 45, tzinfo=moscow)

    scenario.update_time(first_due)

    assert scenario.time == first_due
    assert len(scenario.pullup_events) == 2
    for current in (venue, side):
        assert current.event_list is not None
        fired = current.event_list.get_events("__GOD__")
        assert len(fired) == 1
        assert fired[0].type == EventType.SYSTEM
        assert fired[0].status == EventStatus.COMPLETED
        assert fired[0].time == first_due
        assert "红军" in fired[0].content
        assert fired[0].scope == set(current.seats)

    scenario.time_pass(timedelta(hours=1))
    assert scenario.time == datetime(1944, 10, 9, 23, 45, tzinfo=moscow)
    assert len(scenario.pullup_events) == 1


def test_scenario_time_cannot_go_backwards(scenario: Scenario) -> None:
    later = scenario.time + timedelta(minutes=10)
    scenario.update_time(later)

    with pytest.raises(ValueError, match="不可倒退"):
        scenario.update_time(later - timedelta(seconds=1))
    with pytest.raises(ValueError, match="不可为负"):
        scenario.time_pass(timedelta(minutes=-5))


def test_concurrent_relative_time_updates_are_not_lost(scenario: Scenario) -> None:
    start = scenario.time

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda _: scenario.time_pass(timedelta(seconds=1)), range(20)))

    assert scenario.time == start + timedelta(seconds=20)


def test_event_edit_permissions_after_submit(
    scenario: Scenario,
    venue: Venue,
    events: EventList,
) -> None:
    pending = MotionSwitchEvent(
        "动议",
        SessionPhase.FREE_DISCUSSION,
        venue.id,
        {CHURCHILL},
        scenario,
    )
    venue.submit_event(pending)
    assert events.pending_event_ids == [pending.id]

    pending.content = "更新说明"
    pending.scope = {CHURCHILL, EDEN}
    assert pending.content == "更新说明"
    assert pending.scope == {CHURCHILL, EDEN}

    with pytest.raises(PermissionError, match="time 不可修改"):
        pending.time = scenario.time + timedelta(minutes=1)
    with pytest.raises(PermissionError, match="id 不可修改"):
        pending.id = 99

    pending.status = EventStatus.COMPLETED
    assert events.pending_event_ids == []
    with pytest.raises(PermissionError, match="不能修改 content"):
        pending.content = "终态再改"
    with pytest.raises(PermissionError, match="不能修改 scope"):
        pending.scope = {STALIN}


def test_pending_properties_return_copies(
    scenario: Scenario,
    venue: Venue,
    events: EventList,
) -> None:
    motion = MotionSwitchEvent(
        "动议",
        SessionPhase.RECESS,
        venue.id,
        {CHURCHILL},
        scenario,
    )
    venue.submit_event(motion)

    pending_ids = events.pending_event_ids
    pending_events = events.pending_events
    pending_ids.clear()
    pending_events.clear()

    assert events.pending_event_ids == [motion.id]
    assert events.pending_events == [motion]


def test_pending_queue_is_local_and_status_callback_uses_venue_list(
    scenario: Scenario,
    venue: Venue,
    events: EventList,
    venue_engine_runner,
) -> None:
    side = _add_side_venue(scenario, venue_engine_runner)
    assert side.event_list is not None
    main_motion = MotionSwitchEvent(
        "主会场动议",
        SessionPhase.FREE_DISCUSSION,
        venue.id,
        {CHURCHILL},
        scenario,
    )
    side_motion = MotionSwitchEvent(
        "侧会场动议",
        SessionPhase.RECESS,
        side.id,
        {STALIN},
        scenario,
    )
    venue.submit_event(main_motion)
    side.submit_event(side_motion)

    assert main_motion.id == side_motion.id == 0
    assert events.pending_events == [main_motion]
    assert side.event_list.pending_events == [side_motion]

    main_motion.status = EventStatus.ACCEPTED
    assert events.pending_events == []
    assert side.event_list.pending_events == [side_motion]

    side_motion.status = EventStatus.REJECTED
    assert side.event_list.pending_events == []


def test_completed_note_and_message_permissions(
    scenario: Scenario,
    venue: Venue,
) -> None:
    note = NoteEvent("密信", CHURCHILL, {EDEN}, venue.id, scenario)
    venue.submit_event(note)
    assert note.status == EventStatus.COMPLETED
    with pytest.raises(PermissionError, match="不能修改 content"):
        note.content = "篡改密信"
    with pytest.raises(PermissionError, match="不能修改 from_rep"):
        note.from_rep = STALIN

    message = MessageEvent("公开发言", CHURCHILL, venue.id, scenario)
    venue.submit_event(message)
    assert message.scope == set(venue.seats)
    with pytest.raises(PermissionError, match="不能修改 content"):
        message.content = "篡改发言"
    with pytest.raises(PermissionError, match="不能修改 from_rep"):
        message.from_rep = STALIN


def test_instruction_is_visible_only_through_venue_event_list(
    scenario: Scenario,
    venue: Venue,
    events: EventList,
) -> None:
    assert scenario.filesystem is not None
    draft = scenario.filesystem.create_rep_file(
        CHURCHILL,
        "instruction.md",
        "请外长核对希腊条款",
    )
    submitted = draft.submit(CHURCHILL)
    instruction = InstructionEvent(
        "外长指示",
        {CHURCHILL, EDEN},
        submitted,
        venue.id,
        scenario,
    )
    venue.submit_event(instruction)

    visible = events.get_events(EDEN)
    assert visible == [instruction]
    assert visible[0].instruction is submitted
    assert events.get_events(STALIN) == []

    rel = submitted.path.relative_to(scenario.filesystem.path).as_posix()
    with pytest.raises(PermissionError):
        scenario.filesystem.read(rel, STALIN)
    with pytest.raises(PermissionError):
        scenario.filesystem.read(rel, EDEN)


def test_venue_event_lists_have_independent_ids_and_shared_time(
    scenario: Scenario,
    venue: Venue,
    venue_engine_runner,
) -> None:
    side = _add_side_venue(scenario, venue_engine_runner)
    main_note = NoteEvent("主会场纸条", CHURCHILL, {EDEN}, venue.id, scenario)
    side_note = NoteEvent("侧会场纸条", CHURCHILL, {EDEN}, side.id, scenario)

    venue.submit_event(main_note)
    side.submit_event(side_note)

    assert venue.event_list is not None
    assert side.event_list is not None
    assert venue.event_list is not side.event_list
    assert main_note.id == side_note.id == 0
    assert main_note.time == side_note.time == scenario.time
    assert venue.event_list.events == [main_note]
    assert side.event_list.events == [side_note]


def _add_side_venue(scenario: Scenario, venue_engine_runner) -> Venue:
    side = Venue(scenario)
    side.id = "side_chamber"
    side.seats = list(scenario.venues[0].seats)
    scenario.venues.append(side)
    side.initialize()
    venue_engine_runner.start(side)
    return side
