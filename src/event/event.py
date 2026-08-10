from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from scenario.group import Group
from scenario.venue import SessionPhase, Venue

if TYPE_CHECKING:
    from scenario.scenario import Scenario

class EventType(StrEnum):
    SYSTEM = "system"
    MOTION_SWITCH = "motion_switch"
    INSTRUCTION = "instruction"
    NOTE = "note"
    MESSAGE = "message"
    CHAT = "chat"

class EventStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"

class Event:
    time: datetime
    scenario: Scenario
    id: int | None
    scope: set[str]
    status: EventStatus
    __content: str

    def __init__(self, time: datetime, content: str, scope: set[str], scenario: Scenario):
        # self.from_rep = None
        # self.to = None
        self.time = time
        self.__content = ""
        self.scenario = scenario
        self.id = None
        self.scope = scope
        self.status = EventStatus.PENDING

class SystemEvent(Event):
    type: EventType
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
        self.type = EventType.SYSTEM
        self.__action = action
        self.status = EventStatus.COMPLETED

class MotionSwitchEvent(Event):
    type: EventType
    target_phase: SessionPhase

    def __init__(
        self,
        time: datetime,
        content: str,
        target_phase: SessionPhase,
        scope: set[str],
        scenario: Scenario,
    ):
        super().__init__(time, content, scope, scenario)
        self.type = EventType.MOTION_SWITCH
        self.target_phase = target_phase

class InstructionEvent(Event):
    type: EventType
    instruction: str
    __from: set[str]

    def __init__(
        self,
        time: datetime,
        content: str,
        fr: set[str],
        instruction: str,
        scenario: Scenario,
    ):
        super().__init__(time, content, fr, scenario)
        self.type = EventType.INSTRUCTION
        self.instruction = instruction
        self.__from = fr

class ResolutionEvent(Event):
    type: EventType
    resolution: str
    __from: set[str]

    def __init__(
        self,
        time: datetime,
        content: str,
        fr: set[str],
        resolution: str,
        scenario: Scenario,
    ):
        super().__init__(time, content, fr, scenario)
        self.type = EventType.RESOLUTION
        self.resolution = resolution
        self.__from = fr

# 会议期间的传纸条私聊
class NoteEvent(Event):
    type: EventType
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
        self.type = EventType.NOTE
        self.__from = fr
        self.__to = to
        self.status = EventStatus.COMPLETED

# 会议期间的消息
class MessageEvent(Event):
    type: EventType
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
        self.type = EventType.MESSAGE
        self.__from = fr
        self.__CoT = CoT
        self.status = EventStatus.COMPLETED
    
    def get_CoT(self, rep: str) -> str:
        if rep != self.__from:
            raise ValueError("Not the sender of this message")
        return self.__CoT

# free discussion环节的消息
class ChatEvent(Event):
    type: EventType
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
        self.type = EventType.CHAT
        self.__from = fr
        self.__CoT = CoT
        self.status = EventStatus.COMPLETED

    def get_CoT(self, rep: str) -> str:
        if rep != self.__from:
            raise ValueError("Not the sender of this message")
        return self.__CoT