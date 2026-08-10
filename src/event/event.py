from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scenario.scenario import Scenario


class Event:
    def __init__(self, time: datetime, content: str, scope: set[str], scenario: Scenario):
        # self.from_rep = None
        # self.to = None
        self.time: datetime = time
        self.__content = ""
        self.scenario = scenario
        self.id = None
        self.scope = scope

class SystemEvent(Event):
    def __init__(
        self,
        time: datetime,
        content: str,
        action: list[str],
        scope: set[str],
        scenario: Scenario,
    ):
        super().__init__(time, content, scope, scenario)
        self.type = "system"
        self.__action = action

class InstructionEvent(Event):
    def __init__(
        self,
        time: datetime,
        content: str,
        fr: set[str],
        action: list[str],
        scenario: Scenario,
    ):
        super().__init__(time, content, fr, scenario)
        self.type = "instruction"
        self.__action = action
        self.__from = fr

class NoteEvent(Event):
    def __init__(
        self,
        time: datetime,
        content: str,
        fr: set[str],
        to: set[str],
        scenario: Scenario,
    ):
        super().__init__(time, content, fr | to, scenario)
        self.type = "note"
        self.__from = fr
        self.__to = to