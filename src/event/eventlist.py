from __future__ import annotations

from condition.condition import Condition
from event.event import Event
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scenario.scenario import Scenario


class EventList:
    def __init__(self, scenario: Scenario):
        self.scenario = scenario
        self.events = []
        if scenario.time is None:
            raise ValueError("场景尚未初始化剧情时间")
        self.time = scenario.time

    def add_event(self, event: Event):
        if event.time < self.time:
            raise ValueError("Wrong time order error")
        event.id = len(self.events)
        self.events.append(event)

    def get_event(self, id: int):
        if id < 0 or id >= len(self.events):
            return None
        return self.events[id]
    
class PullUpEvent:
    def __init__(self, condition: Condition, content: str, scenario: Scenario):
        self.condition = condition
        self.content = content
        self.scenario = scenario