from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scenario.scenario import Scenario


class Condition:
    def __init__(self, type: str, content: str | datetime, scenario: Scenario):
        self.type = type
        self.content = content
        self.scenario = scenario

    def check(self):
        pass
