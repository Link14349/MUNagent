from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scenario.scenario import Scenario


class Agenda:
    id: str
    title: str
    questions: list[str]

    def __init__(self, id: str, title: str, questions: list[str]):
        self.id = id
        self.title = title
        self.questions = questions


class Venue:
    id: str
    name: str
    description: str
    timezone: str
    scenario: Scenario
    chair: str | None
    seats: list[str]
    initial_agenda: str
    agenda: list[Agenda]

    def __init__(self, scenario: Scenario):
        self.id = ""
        self.name = ""
        self.description = ""
        self.timezone = ""
        self.scenario = scenario
        self.chair = None
        self.seats = []
        self.initial_agenda = ""
        self.agenda = []
