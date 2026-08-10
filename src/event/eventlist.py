from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from condition.condition import Condition
from event.event import Event, SystemEvent

if TYPE_CHECKING:
    from scenario.scenario import Scenario


class EventList:
    scenario: Scenario
    pullup_events: list[PullUpEvent]
    __events: list[Event]
    __time: datetime

    def __init__(self, scenario: Scenario):
        self.scenario = scenario
        self.__events = []
        self.pullup_events = []
        if scenario.start_time is None:
            raise ValueError("场景尚未初始化开场时间")
        self.__time = scenario.start_time

    @property
    def time(self) -> datetime:
        return self.__time

    def pull_up_event(self, pullup: PullUpEvent):
        if pullup.condition.type != "time":
            raise ValueError("Pull up event must be a time condition")
        if pullup.condition.time < self.time:
            return
        self.pullup_events.append(pullup)

    def update_time(self, time: datetime):
        if time < self.__time:
            raise ValueError("Wrong time order error")
        self.__time = time
        due = [
            pullup
            for pullup in self.pullup_events
            if pullup.condition.time is not None and pullup.condition.time <= self.time
        ]
        for pullup in due:
            venue_id = self.scenario.venues[0].id
            self.add_event(
                SystemEvent(
                    self.time,
                    pullup.content,
                    [],
                    venue_id,
                    {rep.id for rep in self.scenario.representatives},
                    self.scenario,
                )
            )
        due_set = set(due)
        self.pullup_events = [pullup for pullup in self.pullup_events if pullup not in due_set]

    def add_event(self, event: Event):
        if event.time < self.__time:
            raise ValueError("Wrong time order error")
        event.id = len(self.__events)
        self.__events.append(event)
        self.__time = event.time

    def get_events(self, rep: str) -> list[Event]:
        """返回对 ``rep`` 可见的事件。

        代表获知 submission 文件的唯一正规途径：可见事件（如 Instruction / Resolution）
        上绑定的 ``File`` 引用；不得依赖 FileSystem 对 submissions/ 的直接枚举。
        """
        if rep == "__GOD__":
            return [event for event in self.__events]
        return [event for event in self.__events if rep in event.scope]


class PullUpEvent:
    condition: Condition
    content: str
    scenario: Scenario

    def __init__(self, condition: Condition, content: str, scenario: Scenario):
        self.condition = condition
        self.content = content
        self.scenario = scenario
