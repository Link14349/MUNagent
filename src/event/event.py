from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from scenario.group import Group
from scenario.representative import Representative
from scenario.venue import Venue

if TYPE_CHECKING:
    from scenario.scenario import Scenario


class Event:
    time: datetime
    scenario: Scenario
    id: int | None
    scope: set[str]
    __content: str

    def __init__(self, time: datetime, content: str, scope: set[str], scenario: Scenario):
        # self.from_rep = None
        # self.to = None
        self.time = time
        self.__content = ""
        self.scenario = scenario
        self.id = None
        self.scope = scope

class SystemEvent(Event):
    type: str
    __action: list[str]

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
    type: str
    __action: list[str]
    __from: set[str]

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

# 会议期间的传纸条私聊
class NoteEvent(Event):
    type: str
    __from: str
    __to: set[str]

    def __init__(
        self,
        time: datetime,
        content: str,
        fr: str,
        to: set[str],
        scenario: Scenario,
    ):
        super().__init__(time, content, {fr} | to, scenario)
        self.type = "note"
        self.__from = fr
        self.__to = to

# 会议期间的消息
class MessageEvent(Event):
    type: str
    __from: str

    def __init__(
        self,
        time: datetime,
        content: str,
        CoT: str,
        fr: str,
        venue: Venue,
        scenario: Scenario,
    ):
        super().__init__(time, content, set(venue.seats), scenario)
        self.type = "message"
        self.__from = fr
        self.__CoT = CoT
    
    def get_CoT(self, rep: str) -> str:
        if rep != self.__from:
            raise ValueError("Not the sender of this message")
        return self.__CoT

# free discussion环节的消息
class ChatEvent(Event):
    type: str
    __from: str

    def __init__(
        self,
        time: datetime,
        content: str,
        fr: str,
        CoT: str,
        group: Group,
        scenario: Scenario,
    ):
        super().__init__(time, content, group.members, scenario)
        self.type = "chat"
        self.__from = fr
        self.__CoT = CoT

    def get_CoT(self, rep: str) -> str:
        if rep != self.__from:
            raise ValueError("Not the sender of this message")
        return self.__CoT