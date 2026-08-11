"""EventList:入表盖戳,可见性过滤,pull-up 触发与权限边界."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from condition.condition import Condition
from event.event import (
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
from scenario.venue import SessionPhase

TEMPLATE = Path(__file__).resolve().parent.parent / "scenario-template"

CHURCHILL = "winston_churchill"
STALIN = "joseph_stalin"
EDEN = "anthony_eden"
MOLOTOV = "vyacheslav_molotov"


@pytest.fixture
def scenario(tmp_path: Path) -> Scenario:
    loaded = Scenario()
    loaded.load(str(TEMPLATE))
    loaded.root_path = tmp_path
    (tmp_path / "simulation").mkdir()
    loaded.initialize()
    return loaded


@pytest.fixture
def events(scenario: Scenario) -> EventList:
    assert scenario.event_list is not None
    return scenario.event_list


@pytest.fixture
def venue_id(scenario: Scenario) -> str:
    return scenario.venues[0].id


def test_initialize_pulls_up_time_events_from_pool(scenario: Scenario, events: EventList) -> None:
    time_pool = [e for e in scenario.event_pool if e.condition.type == "time"]
    assert len(time_pool) == 3
    assert len(events.pullup_events) == len(time_pool)
    assert events.time == scenario.start_time
    assert events.get_events("__GOD__") == []


def test_submit_event_stamps_time_and_id(
    scenario: Scenario, events: EventList, venue_id: str
) -> None:
    motion = MotionSwitchEvent(
        "进入自由讨论",
        SessionPhase.FREE_DISCUSSION,
        venue_id,
        {CHURCHILL, STALIN},
        scenario,
    )
    assert motion.time is None
    assert motion.id is None

    events.submit_event(motion)
    assert motion.time == scenario.start_time == events.time
    assert motion.id == 0

    note = NoteEvent("私下试探", CHURCHILL, {EDEN}, venue_id, scenario)
    events.submit_event(note)
    assert note.time == events.time
    assert note.id == 1


def test_submit_event_notifies_listeners_by_type(
    scenario: Scenario, events: EventList, venue_id: str
) -> None:
    from event.event import Event

    seen_notes: list[Event] = []
    seen_motions: list[Event] = []
    order: list[str] = []

    events.add_listener(EventType.NOTE, lambda e: seen_notes.append(e))
    events.add_listener(EventType.NOTE, lambda e: order.append("note-a"))
    events.add_listener(EventType.NOTE, lambda e: order.append("note-b"))
    events.add_listener(EventType.MOTION_SWITCH, lambda e: seen_motions.append(e))

    note = NoteEvent("私下试探", CHURCHILL, {EDEN}, venue_id, scenario)
    events.submit_event(note)
    motion = MotionSwitchEvent(
        "进入自由讨论",
        SessionPhase.FREE_DISCUSSION,
        venue_id,
        {CHURCHILL, STALIN},
        scenario,
    )
    events.submit_event(motion)

    assert seen_notes == [note]
    assert seen_motions == [motion]
    assert order == ["note-a", "note-b"]
    assert note.id is not None
    assert motion.id is not None


def test_submit_event_listeners_filter_by_venue(
    scenario: Scenario, events: EventList, venue_id: str
) -> None:
    from event.event import Event

    global_seen: list[Event] = []
    matched_seen: list[Event] = []
    other_seen: list[Event] = []

    events.add_listener(EventType.NOTE, lambda e: global_seen.append(e), venue=None)
    events.add_listener(
        EventType.NOTE, lambda e: matched_seen.append(e), venue=venue_id
    )
    events.add_listener(
        EventType.NOTE, lambda e: other_seen.append(e), venue="other_venue"
    )

    note = NoteEvent("私下试探", CHURCHILL, {EDEN}, venue_id, scenario)
    events.submit_event(note)

    assert global_seen == [note]
    assert matched_seen == [note]
    assert other_seen == []


def test_submit_event_rejects_preassigned_time_or_id(
    scenario: Scenario, events: EventList, venue_id: str
) -> None:
    stamped = SystemEvent("已盖戳", [], venue_id, {CHURCHILL}, scenario)
    stamped.time = events.time
    with pytest.raises(ValueError, match="应由 EventList.submit_event 设定"):
        events.submit_event(stamped)

    numbered = SystemEvent("已编号", [], venue_id, {CHURCHILL}, scenario)
    numbered.id = 99
    with pytest.raises(ValueError, match="应由 EventList.submit_event 设定"):
        events.submit_event(numbered)


def test_get_events_filters_by_scope(
    scenario: Scenario, events: EventList, venue_id: str
) -> None:
    public = SystemEvent(
        "全员通报",
        [],
        venue_id,
        {CHURCHILL, STALIN, EDEN, MOLOTOV},
        scenario,
    )
    private = NoteEvent("仅丘艾可见", CHURCHILL, {EDEN}, venue_id, scenario)
    secret = NoteEvent("仅丘斯可见", CHURCHILL, {STALIN}, venue_id, scenario)
    events.submit_event(public)
    events.submit_event(private)
    events.submit_event(secret)

    churchill = events.get_events(CHURCHILL)
    assert [e.content for e in churchill] == [
        "全员通报",
        "仅丘艾可见",
        "仅丘斯可见",
    ]

    eden = events.get_events(EDEN)
    assert [e.content for e in eden] == ["全员通报", "仅丘艾可见"]

    stalin = events.get_events(STALIN)
    assert [e.content for e in stalin] == ["全员通报", "仅丘斯可见"]

    molotov = events.get_events(MOLOTOV)
    assert [e.content for e in molotov] == ["全员通报"]

    god = events.get_events("__GOD__")
    assert len(god) == 3
    assert [e.content for e in god] == ["全员通报", "仅丘艾可见", "仅丘斯可见"]


def test_pull_up_rejects_non_time_and_skips_past(
    scenario: Scenario, events: EventList
) -> None:
    text_pull = PullUpEvent(
        Condition("text", "会场已形成草案", scenario),
        "不该挂载",
        scenario,
    )
    with pytest.raises(ValueError, match="time condition"):
        events.pull_up_event(text_pull)

    assert scenario.start_time is not None
    past = PullUpEvent(
        Condition(
            "time",
            scenario.start_time - timedelta(minutes=1),
            scenario,
        ),
        "过期事件",
        scenario,
    )
    before = len(events.pullup_events)
    events.pull_up_event(past)
    assert len(events.pullup_events) == before


def test_update_time_and_time_pass_fire_due_pullups(
    scenario: Scenario, events: EventList
) -> None:
    moscow = ZoneInfo("Europe/Moscow")
    first_due = datetime(1944, 10, 9, 22, 45, tzinfo=moscow)
    second_due = datetime(1944, 10, 9, 23, 45, tzinfo=moscow)
    third_due = datetime(1944, 10, 10, 1, 30, tzinfo=moscow)

    assert len(events.pullup_events) == 3

    events.update_time(first_due)
    fired = events.get_events("__GOD__")
    assert len(fired) == 1
    assert fired[0].type == EventType.SYSTEM
    assert fired[0].status == EventStatus.COMPLETED
    assert fired[0].time == first_due
    assert "红军" in fired[0].content
    assert set(fired[0].scope) == {rep.id for rep in scenario.representatives}
    assert len(events.pullup_events) == 2

    assert len(events.get_events(CHURCHILL)) == 1
    assert len(events.get_events(STALIN)) == 1

    events.time_pass(timedelta(hours=1))  # 22:45 -> 23:45
    assert events.time == second_due
    fired = events.get_events("__GOD__")
    assert len(fired) == 2
    assert "希腊" in fired[1].content
    assert len(events.pullup_events) == 1

    events.update_time(third_due)
    fired = events.get_events("__GOD__")
    assert len(fired) == 3
    assert "哈里曼" in fired[2].content
    assert events.pullup_events == []


def test_time_cannot_go_backwards(events: EventList) -> None:
    later = events.time + timedelta(minutes=10)
    events.update_time(later)
    with pytest.raises(ValueError, match="Wrong time order"):
        events.update_time(later - timedelta(seconds=1))
    with pytest.raises(ValueError, match="不可为负"):
        events.time_pass(timedelta(minutes=-5))


def test_event_edit_permissions_after_add(
    scenario: Scenario, events: EventList, venue_id: str
) -> None:
    pending = MotionSwitchEvent(
        "动议",
        SessionPhase.FREE_DISCUSSION,
        venue_id,
        {CHURCHILL},
        scenario,
    )
    events.submit_event(pending)
    assert events.pending_event_ids == [pending.id]
    pending.content = "更新说明"
    pending.scope = {CHURCHILL, EDEN}
    assert pending.content == "更新说明"
    assert pending.scope == {CHURCHILL, EDEN}

    with pytest.raises(PermissionError, match="time 不可修改"):
        pending.time = events.time + timedelta(minutes=1)
    with pytest.raises(PermissionError, match="id 不可修改"):
        pending.id = 99

    pending.status = EventStatus.COMPLETED
    assert events.pending_event_ids == []
    with pytest.raises(PermissionError, match="不能修改 content"):
        pending.content = "终态再改"
    with pytest.raises(PermissionError, match="不能修改 scope"):
        pending.scope = {STALIN}


def test_pending_queue_on_submit_and_status_leave(
    scenario: Scenario, events: EventList, venue_id: str
) -> None:
    first = MotionSwitchEvent(
        "动议一",
        SessionPhase.FREE_DISCUSSION,
        venue_id,
        {CHURCHILL},
        scenario,
    )
    second = MotionSwitchEvent(
        "动议二",
        SessionPhase.RECESS,
        venue_id,
        {STALIN},
        scenario,
    )
    done = SystemEvent("系统广播", [], venue_id, {CHURCHILL, STALIN}, scenario)

    events.submit_event(first)
    events.submit_event(second)
    events.submit_event(done)
    assert events.pending_event_ids == [first.id, second.id]
    pending_snapshot = events.pending_events
    assert pending_snapshot == [first, second]
    pending_snapshot.clear()
    assert events.pending_event_ids == [first.id, second.id]
    assert events.pending_events == [first, second]

    first.status = EventStatus.ACCEPTED
    assert events.pending_event_ids == [second.id]
    assert events.pending_events == [second]

    second.status = EventStatus.REJECTED
    assert events.pending_event_ids == []

    with pytest.raises(ValueError, match="不在 pending 队列中"):
        events._event_updated(first)

    outsider = MotionSwitchEvent(
        "未入表动议",
        SessionPhase.FREE_DISCUSSION,
        venue_id,
        {CHURCHILL},
        scenario,
    )
    outsider.id = 0
    with pytest.raises(ValueError, match="不属于会场"):
        events._event_updated(outsider)


def test_completed_note_and_message_permissions(
    scenario: Scenario, events: EventList, venue_id: str
) -> None:
    note = NoteEvent("密信", CHURCHILL, {EDEN}, venue_id, scenario)
    events.submit_event(note)
    assert note.status == EventStatus.COMPLETED
    with pytest.raises(PermissionError, match="不能修改 content"):
        note.content = "篡改密信"
    with pytest.raises(PermissionError, match="不能修改 from_rep"):
        note.from_rep = STALIN

    msg = MessageEvent(
        "公开发言",
        CHURCHILL,
        venue_id,
        scenario,
    )
    events.submit_event(msg)
    assert set(msg.scope) == {rep.id for rep in scenario.representatives}
    with pytest.raises(PermissionError, match="不能修改 content"):
        msg.content = "篡改发言"
    with pytest.raises(PermissionError, match="不能修改 from_rep"):
        msg.from_rep = STALIN


def test_instruction_event_is_only_visible_via_scope(
    scenario: Scenario, events: EventList, venue_id: str
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
        venue_id,
        scenario,
    )
    events.submit_event(instruction)

    visible_to_eden = events.get_events(EDEN)
    assert len(visible_to_eden) == 1
    assert isinstance(visible_to_eden[0], InstructionEvent)
    assert visible_to_eden[0].instruction is submitted

    assert events.get_events(STALIN) == []
    # submission 本身仍不可被代表直接读取;只能经事件索引获知
    assert scenario.filesystem is not None
    rel = submitted.path.relative_to(scenario.filesystem.path).as_posix()
    with pytest.raises(PermissionError):
        scenario.filesystem.read(rel, STALIN)
    with pytest.raises(PermissionError):
        scenario.filesystem.read(rel, EDEN)


def test_eventlist_creates_store_per_venue(scenario: Scenario, events: EventList) -> None:
    venue_ids = [venue.id for venue in scenario.venues]
    assert venue_ids
    for venue_id in venue_ids:
        store = events.for_venue(venue_id)
        assert store.venue_id == venue_id
        assert store.events == []
    with pytest.raises(ValueError, match="未知会场"):
        events.for_venue("not_a_venue")


def test_submit_event_routes_to_venue_store(
    scenario: Scenario, events: EventList, venue_id: str
) -> None:
    from scenario.venue import Venue

    other = Venue(scenario)
    other.id = "side_chamber"
    other.seats = list(scenario.venues[0].seats)
    scenario.venues.append(other)
    # 重建事件表以包含新会场容器,并挂回 scenario 供 Event.status 回调
    isolated = EventList(scenario)
    scenario.event_list = isolated

    main_note = NoteEvent("主会场纸条", CHURCHILL, {EDEN}, venue_id, scenario)
    side_note = NoteEvent(
        "侧室纸条", CHURCHILL, {EDEN}, "side_chamber", scenario
    )
    isolated.submit_event(main_note)
    isolated.submit_event(side_note)

    main_store = isolated.for_venue(venue_id)
    side_store = isolated.for_venue("side_chamber")
    assert main_store.events == [main_note]
    assert side_store.events == [side_note]
    assert main_note.id == 0
    assert side_note.id == 0  # id 仅在会场内唯一
    assert isolated.get_events("__GOD__") == [main_note, side_note]
    assert isolated.get_events(EDEN) == [main_note, side_note]

    # pending 也按会场隔离
    from scenario.venue import SessionPhase

    main_motion = MotionSwitchEvent(
        "主会场动议",
        SessionPhase.FREE_DISCUSSION,
        venue_id,
        {CHURCHILL, EDEN},
        scenario,
    )
    side_motion = MotionSwitchEvent(
        "侧室动议",
        SessionPhase.RECESS,
        "side_chamber",
        {CHURCHILL, EDEN},
        scenario,
    )
    isolated.submit_event(main_motion)
    isolated.submit_event(side_motion)
    assert main_store.pending_events == [main_motion]
    assert side_store.pending_events == [side_motion]
    assert isolated.pending_events == [main_motion, side_motion]

    main_motion.status = EventStatus.COMPLETED
    assert main_store.pending_events == []
    assert side_store.pending_events == [side_motion]
