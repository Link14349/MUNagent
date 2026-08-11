from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scenario.group import Group
    from scenario.scenario import Scenario


class SessionPhase(StrEnum):
    """会议阶段."""

    CHAIRED_CORE = "chaired_core"  # 有主持核心磋商
    UNCHAIRED_CORE = "unchaired_core"  # 无主持核心磋商
    FREE_DISCUSSION = "free_discussion"  # 自由讨论
    RECESS = "recess"  # 休会
    MEETING_ENDED = "meeting_ended"  # 会议结束


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
    groups: list[Group]

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
        self.groups = []
        self.__session_phase: SessionPhase | None = None

    @property
    def session_phase(self) -> SessionPhase | None:
        """当前会议阶段(只读)."""
        return self.__session_phase

    def switch_phase(self, phase: SessionPhase) -> None:
        """切换会议阶段.

        阶段变更通过显式方法而非 @property setter 完成,以便将来作为
        Agent 可调用的会场动作暴露;读取仍使用 session_phase 属性.
        """
        self.__session_phase = phase
