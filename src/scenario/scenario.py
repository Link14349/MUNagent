from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from condition.condition import Condition
from scenario.representative import Representative
from scenario.venue import Venue

if TYPE_CHECKING:
    from event.eventlist import EventList, PullUpEvent


class Scenario:
    title: str
    background: str
    targets: list[str]
    description: str
    timezone: str
    start_time: datetime | None
    event_pool: list[PullUpEvent]
    end_conditions: list[Condition]
    venues: list[Venue]
    representatives: list[Representative]
    event_list: EventList | None

    def __init__(self) -> None:
        self.title = ""
        self.background = ""
        self.targets = []
        self.description = ""
        self.timezone = ""
        self.start_time = None
        self.event_pool = []
        self.end_conditions = []
        self.venues = []
        self.representatives = []
        self.event_list = None

    def load(self, scenario_path: str) -> None:
        from scenario.load import populate_scenario

        populate_scenario(self, scenario_path)

    def initialize(self) -> None:
        self.event_list = EventList(self)
