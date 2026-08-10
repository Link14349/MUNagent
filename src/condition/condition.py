from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scenario.scenario import Scenario


class Condition:
    type: str
    content: str | datetime
    scenario: Scenario
    time: datetime | None

    def __init__(self, type: str, content: str | datetime, scenario: Scenario):
        self.type = type
        self.content = content
        self.scenario = scenario
        self.time = None
        if type == "time":
            if not isinstance(content, datetime):
                raise TypeError("time 条件的 content 须为 datetime")
            self.time = content

    def check(self) -> bool:
        pass
