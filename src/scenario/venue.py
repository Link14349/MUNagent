from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from scenario.load_helpers import load_yaml, require_keys

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

    def load(self, venue_path: str) -> None:
        path = Path(venue_path)
        data = load_yaml(path)
        context = f"会场 {path.name}"

        require_keys(
            data,
            {
                "id",
                "name",
                "timezone",
                "description",
                "chair",
                "seats",
                "initial_agenda",
                "agenda",
            },
            context=context,
        )

        self.id = _require_str(data["id"], field=f"{context}.id")
        self.name = _require_str(data["name"], field=f"{context}.name")
        self.timezone = _require_str(data["timezone"], field=f"{context}.timezone")
        self.description = _require_str(data["description"], field=f"{context}.description")
        self.initial_agenda = _require_str(
            data["initial_agenda"],
            field=f"{context}.initial_agenda",
        )

        chair = data["chair"]
        if not isinstance(chair, str) or not chair.strip():
            raise ValueError(f"{context}.chair 须为非空字符串")
        self.chair = chair.strip()

        seats = data["seats"]
        if not isinstance(seats, list) or not seats:
            raise ValueError(f"{context}.seats 须为非空列表")
        self.seats = []
        for index, seat in enumerate(seats):
            if not isinstance(seat, str) or not seat.strip():
                raise ValueError(f"{context}.seats[{index}] 须为非空代表 ID 字符串")
            self.seats.append(seat.strip())

        agenda_raw = data["agenda"]
        if not isinstance(agenda_raw, list) or not agenda_raw:
            raise ValueError(f"{context}.agenda 须为非空列表")

        self.agenda = []
        for index, item in enumerate(agenda_raw):
            item_context = f"{context}.agenda[{index}]"
            if not isinstance(item, dict):
                raise ValueError(f"{item_context} 须为对象")
            require_keys(item, {"id", "title", "questions"}, context=item_context)
            questions = item["questions"]
            if not isinstance(questions, list) or not questions:
                raise ValueError(f"{item_context}.questions 须为非空列表")
            parsed_questions: list[str] = []
            for q_index, question in enumerate(questions):
                if not isinstance(question, str) or not question.strip():
                    raise ValueError(
                        f"{item_context}.questions[{q_index}] 须为非空字符串"
                    )
                parsed_questions.append(question.strip())
            self.agenda.append(
                Agenda(
                    id=_require_str(item["id"], field=f"{item_context}.id"),
                    title=_require_str(item["title"], field=f"{item_context}.title"),
                    questions=parsed_questions,
                )
            )


def _require_str(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 须为非空字符串")
    return value.strip()
