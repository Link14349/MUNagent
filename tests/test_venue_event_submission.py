"""代表事件先提交给 Venue，由 Venue 暂时直接转交 EventList。"""

from __future__ import annotations

from pathlib import Path

import pytest

from event.event import Event, EventType, MessageEvent
from scenario.scenario import Scenario
from scenario.venue import SessionPhase

TEMPLATE = Path(__file__).resolve().parent.parent / "scenario-template"

CHURCHILL = "winston_churchill"
EDEN = "anthony_eden"


@pytest.fixture
def scenario(tmp_path: Path) -> Scenario:
    loaded = Scenario()
    loaded.load(str(TEMPLATE))
    loaded.root_path = tmp_path
    (tmp_path / "simulation").mkdir()
    loaded.initialize()
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
