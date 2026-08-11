from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agenda.agenda import Agenda, AgendaManager
    from scenario.group import Group
    from scenario.representative import Representative
    from scenario.scenario import Scenario


class SessionPhase(StrEnum):
    """会议阶段."""

    CHAIRED_CORE = "chaired_core"  # 有主持核心磋商
    UNCHAIRED_CORE = "unchaired_core"  # 无主持核心磋商
    FREE_DISCUSSION = "free_discussion"  # 自由讨论
    RECESS = "recess"  # 休会
    MEETING_ENDED = "meeting_ended"  # 会议结束


class Venue:
    id: str
    name: str
    description: str
    timezone: str
    scenario: Scenario
    seats: list[str]
    reps: dict[str, Representative]
    initial_agenda: str
    groups: list[Group]

    def __init__(self, scenario: Scenario):
        self.id = ""
        self.name = ""
        self.description = ""
        self.timezone = ""
        self.scenario = scenario
        self.__chair: str | None = None
        self.seats = []
        self.reps = {}
        self.initial_agenda = ""
        self.__agenda_manager: AgendaManager | None = None
        self.groups = []
        self.__session_phase: SessionPhase | None = None

    def _find_rep(self, rep_id: str) -> Representative | None:
        return self.reps.get(rep_id) or self.scenario.reps.get(rep_id)

    def _require_agenda_manager(self) -> AgendaManager:
        if self.__agenda_manager is None:
            raise RuntimeError(
                f"会场 {self.id or '<unset>'} 尚未绑定 AgendaManager"
            )
        return self.__agenda_manager

    def _bind_agenda_manager(self, manager: AgendaManager) -> None:
        """加载期一次性绑定;外部不应调用."""
        if self.__agenda_manager is not None:
            raise RuntimeError(
                f"会场 {self.id or '<unset>'} 已绑定 AgendaManager,不能重复绑定"
            )
        self.__agenda_manager = manager

    def _require_chair_actor(self, rep_id: str) -> None:
        if self.__chair is None:
            raise PermissionError(
                f"会场 {self.id or '<unset>'} 当前为系统主席，代表不能发起议题操作"
            )
        if rep_id != self.__chair:
            raise PermissionError(
                f"代表 {rep_id} 不是会场 {self.id or '<unset>'} 的主席"
                f"(chair={self.__chair!r})，不能发起议题操作"
            )

    @property
    def chair(self) -> str | None:
        """当前主席代表 ID;``None`` 表示系统中立主席."""
        return self.__chair

    @chair.setter
    def chair(self, value: str | None) -> None:
        if value is None:
            new_chair: str | None = None
        else:
            normalized = value.strip()
            if not normalized or normalized == "none":
                new_chair = None
            else:
                new_chair = normalized
                if self.seats and new_chair not in self.seats:
                    raise ValueError(
                        f"会场 {self.id or '<unset>'}.chair={new_chair!r} 必须是 seats 中的代表 ID"
                    )

        old_chair = self.__chair
        if old_chair is not None and old_chair != new_chair:
            old_rep = self._find_rep(old_chair)
            if old_rep is not None:
                old_rep.is_chair = False

        self.__chair = new_chair

        if new_chair is not None:
            new_rep = self._find_rep(new_chair)
            if new_rep is not None:
                new_rep.is_chair = True

    @property
    def current_agenda(self) -> Agenda | None:
        return self._require_agenda_manager().current_agenda

    @property
    def todo_agenda(self) -> list[Agenda]:
        return self._require_agenda_manager().todo_agenda

    @property
    def finished_agenda(self) -> list[Agenda]:
        return self._require_agenda_manager().finished_agenda

    def get_agenda(self, agenda_id: str) -> Agenda:
        return self._require_agenda_manager().get(agenda_id)

    def _require_event_list(self):
        event_list = self.scenario.event_list
        if event_list is None:
            raise RuntimeError(
                f"会场 {self.id or '<unset>'} 所在 Scenario 尚未创建 EventList,"
                "无法提交议题事件"
            )
        return event_list

    def _agenda_event_scope(self) -> set[str]:
        return set(self.seats)

    def set_current_agenda(
        self,
        rep_id: str,
        agenda: Agenda,
        finished: bool = False,
    ) -> None:
        """由主席将 ``agenda`` 设为当前议题;非主席拒绝;成功后提交 SetAgendaEvent."""
        from event.event import SetAgendaEvent

        self._require_chair_actor(rep_id)
        manager = self._require_agenda_manager()
        previous = manager.current_agenda
        if agenda is previous:
            return
        manager.set_current_agenda(agenda, finished=finished)
        self._require_event_list().submit_event(
            SetAgendaEvent(
                f"主席 {rep_id} 将当前议题切换为 {agenda.id}",
                agenda,
                rep_id,
                self.id,
                self._agenda_event_scope(),
                self.scenario,
                finished=finished,
                previous=previous,
            )
        )

    def add_agenda(self, rep_id: str, agenda: Agenda) -> None:
        """由主席向 todo 追加议题;非主席拒绝;成功后提交 AddAgendaEvent."""
        from event.event import AddAgendaEvent

        self._require_chair_actor(rep_id)
        self._require_agenda_manager().add_todo(agenda)
        self._require_event_list().submit_event(
            AddAgendaEvent(
                f"主席 {rep_id} 追加议题 {agenda.id}",
                agenda,
                rep_id,
                self.id,
                self._agenda_event_scope(),
                self.scenario,
            )
        )

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
