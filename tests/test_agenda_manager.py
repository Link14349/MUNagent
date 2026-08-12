"""AgendaManager / Venue 议题接口与主席权限."""

from __future__ import annotations

from pathlib import Path

import pytest

from agenda.agenda import Agenda
from event.event import AddAgendaEvent, EventType, SetAgendaEvent
from scenario.scenario import Scenario

TEMPLATE = Path(__file__).resolve().parent.parent / "scenario-template"

CHURCHILL = "winston_churchill"
STALIN = "joseph_stalin"


@pytest.fixture
def scenario(tmp_path: Path) -> Scenario:
    loaded = Scenario()
    loaded.load(str(TEMPLATE))
    loaded.root_path = tmp_path
    (tmp_path / "simulation").mkdir()
    loaded.initialize()
    return loaded


def test_load_sets_current_from_initial_agenda(scenario: Scenario) -> None:
    venue = scenario.venues[0]
    assert venue.initial_agenda == "meaning_of_percentages"
    assert venue.current_agenda is not None
    assert venue.current_agenda.id == venue.initial_agenda
    assert venue.initial_agenda not in {item.id for item in venue.todo_agenda}
    assert venue.finished_agenda == []


def test_set_current_agenda_requires_chair(scenario: Scenario) -> None:
    venue = scenario.venues[0]
    assert venue.current_agenda is not None
    second = venue.todo_agenda[0]

    with pytest.raises(PermissionError, match="系统主席"):
        venue.set_current_agenda(CHURCHILL, second)

    venue.chair = CHURCHILL
    with pytest.raises(PermissionError, match="不是会场"):
        venue.set_current_agenda(STALIN, second)

    first = venue.current_agenda
    venue.set_current_agenda(CHURCHILL, second, finished=False)
    assert venue.current_agenda is second
    assert first in venue.todo_agenda
    assert first not in venue.finished_agenda
    assert venue.event_list is not None
    set_events = [
        e for e in venue.event_list.get_events("__GOD__") if isinstance(e, SetAgendaEvent)
    ]
    assert len(set_events) == 1
    assert set_events[0].agenda is second
    assert set_events[0].previous is first
    assert set_events[0].finished is False
    assert set_events[0].from_rep == CHURCHILL
    assert set_events[0].type == EventType.SET_AGENDA

    third = next(item for item in venue.todo_agenda if item is not first)
    venue.set_current_agenda(CHURCHILL, third, finished=True)
    assert venue.current_agenda is third
    assert second in venue.finished_agenda
    assert second not in venue.todo_agenda
    set_events = [
        e for e in venue.event_list.get_events("__GOD__") if isinstance(e, SetAgendaEvent)
    ]
    assert len(set_events) == 2
    assert set_events[-1].finished is True
    assert set_events[-1].previous is second


def test_set_current_rejects_unknown_and_allows_noop(scenario: Scenario) -> None:
    venue = scenario.venues[0]
    venue.chair = CHURCHILL
    assert venue.current_agenda is not None
    assert venue.event_list is not None
    before = len(venue.event_list.get_events("__GOD__"))

    venue.set_current_agenda(CHURCHILL, venue.current_agenda)
    assert venue.finished_agenda == []
    assert len(venue.event_list.get_events("__GOD__")) == before

    outsider = Agenda("not_in_list", "外部议题", ["?"])
    with pytest.raises(ValueError, match="不在"):
        venue.set_current_agenda(CHURCHILL, outsider)


def test_add_agenda_requires_chair_and_rejects_duplicate(
    scenario: Scenario,
) -> None:
    venue = scenario.venues[0]
    fresh = Agenda("extra_topic", "追加议题", ["如何处理?"])

    with pytest.raises(PermissionError, match="系统主席"):
        venue.add_agenda(CHURCHILL, fresh)

    venue.chair = CHURCHILL
    with pytest.raises(PermissionError, match="不是会场"):
        venue.add_agenda(STALIN, fresh)

    venue.add_agenda(CHURCHILL, fresh)
    assert fresh in venue.todo_agenda
    assert venue.get_agenda("extra_topic") is fresh
    assert venue.event_list is not None
    add_events = [
        e for e in venue.event_list.get_events("__GOD__") if isinstance(e, AddAgendaEvent)
    ]
    assert len(add_events) == 1
    assert add_events[0].agenda is fresh
    assert add_events[0].from_rep == CHURCHILL
    assert add_events[0].type == EventType.ADD_AGENDA
    assert add_events[0].scope == set(venue.seats)

    assert venue.current_agenda is not None
    with pytest.raises(ValueError, match="已存在议题 ID"):
        venue.add_agenda(
            CHURCHILL,
            Agenda(venue.current_agenda.id, "重复", ["x"]),
        )


def test_agenda_list_properties_return_copies(scenario: Scenario) -> None:
    venue = scenario.venues[0]
    todo = venue.todo_agenda
    finished = venue.finished_agenda
    todo.clear()
    finished.append(Agenda("ghost", "幽灵", ["?"]))
    assert venue.todo_agenda
    assert venue.finished_agenda == []


def test_representative_agenda_api(scenario: Scenario) -> None:
    venue = scenario.venues[0]
    churchill = scenario.reps[CHURCHILL]
    stalin = scenario.reps[STALIN]

    assert churchill.current_agenda is venue.current_agenda
    assert [item.id for item in churchill.todo_agenda] == [
        item.id for item in venue.todo_agenda
    ]

    second = churchill.todo_agenda[0]
    with pytest.raises(PermissionError, match="系统主席"):
        churchill.set_current_agenda(second)

    venue.chair = CHURCHILL
    with pytest.raises(PermissionError, match="不是会场"):
        stalin.set_current_agenda(second)

    first = churchill.current_agenda
    churchill.set_current_agenda(second, finished=True)
    assert churchill.current_agenda is second
    assert first in churchill.finished_agenda

    fresh = Agenda("rep_extra", "代表追加", ["?"])
    churchill.add_agenda(fresh)
    assert churchill.get_agenda("rep_extra") is fresh
    assert fresh in churchill.todo_agenda
