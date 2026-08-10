from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from condition.condition import Condition
from scenario.representative import Representative
from scenario.venue import Venue

if TYPE_CHECKING:
    from event.eventlist import EventList, PullUpEvent
    from filesystem.filesystem import FileSystem


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
    root_path: Path | None
    filesystem: FileSystem | None

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
        self.root_path = None
        self.filesystem = None

    def load(self, scenario_path: str) -> None:
        from scenario.load import populate_scenario

        populate_scenario(self, scenario_path)

    def initialize(self) -> None:
        """准备一次推演运行：事件表 + 挂载 time 条件外部事件 + 绑定新建的 FileSystem。"""
        from event.eventlist import EventList
        from filesystem.filesystem import FileSystem

        if self.filesystem is not None:
            raise RuntimeError("Scenario 已绑定 FileSystem，不能重复 initialize")

        self.event_list = EventList(self)
        for pullup in self.event_pool:
            if pullup.condition.type == "time":
                self.event_list.pull_up_event(pullup)

        self.filesystem = FileSystem.create_for_scenario(self)
