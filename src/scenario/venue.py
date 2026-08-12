from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agenda.agenda import Agenda, AgendaManager
    from event.event import Event, PhaseSwitchEvent
    from event.eventlist import EventList
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

class CHAIR_POWER(StrEnum):
    DECIDE_RESOLUTION = "decide_resolution"
    DECIDE_SWITCH_PHASE = "decide_switch_phase"


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
    chair_power: dict[CHAIR_POWER, bool]
    event_list: EventList | None

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
        self.chair_power = {power: False for power in CHAIR_POWER}
        self.event_list = None

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

    def _require_chair_actor(
        self, rep_id: str, *, action: str = "发起议题操作"
    ) -> None:
        if self.__chair is None:
            raise PermissionError(
                f"会场 {self.id or '<unset>'} 当前为系统主席，代表不能{action}"
            )
        if rep_id != self.__chair:
            raise PermissionError(
                f"代表 {rep_id} 不是会场 {self.id or '<unset>'} 的主席"
                f"(chair={self.__chair!r})，不能{action}"
            )

    def _require_chair_power(
        self, rep_id: str, power: CHAIR_POWER, *, action: str
    ) -> None:
        """校验 ``rep_id`` 为主席且 ``chair_power[power]`` 为真."""
        self._require_chair_actor(rep_id, action=action)
        if not self.chair_power[power]:
            raise PermissionError(
                f"会场 {self.id or '<unset>'} 的主席权力 {power.value}=False，"
                f"代表 {rep_id} 不能{action}"
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
        event_list = self.event_list
        if event_list is None:
            raise RuntimeError(
                f"会场 {self.id or '<unset>'} 尚未 initialize EventList,"
                "无法访问事件"
            )
        return event_list

    def submit_event(self, event: Event) -> None:
        """接收会场事件并转交本会场事件表.

        当前只建立代表与本会场 ``EventList`` 之间的边界；事件排队、排序、
        校验和裁定留给后续的会场主循环实现。事件时间由 Scenario 统一盖戳。
        """
        if event.venue != self.id:
            raise ValueError(
                f"事件 venue={event.venue!r} 不能提交给会场 {self.id!r}"
            )
        event_list = self._require_event_list()
        self.scenario._stamp_event(event)
        event_list.submit_event(event)

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
        self.submit_event(
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
        self.submit_event(
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

    def decide_switch_phase(
        self,
        rep_id: str,
        content: str,
        target_phase: SessionPhase | str,
    ) -> PhaseSwitchEvent:
        """由具备 ``decide_switch_phase`` 的主席直接切换阶段并提交 PhaseSwitchEvent."""
        from event.event import PhaseSwitchEvent

        self._require_chair_power(
            rep_id,
            CHAIR_POWER.DECIDE_SWITCH_PHASE,
            action="直接切换会议阶段",
        )
        event = PhaseSwitchEvent(
            content,
            target_phase,
            self.id,
            set(self.seats),
            self.scenario,
        )
        self.submit_event(event)
        return event

    def initialize(self) -> None:
        """创建本会场 EventList 并注册 PHASE_SWITCH listener."""
        from event.event import EventType
        from event.eventlist import EventList

        if self.event_list is not None:
            raise RuntimeError(
                f"会场 {self.id or '<unset>'} 已 initialize EventList,不能重复初始化"
            )
        self.event_list = EventList(self)
        self.event_list.add_listener(
            EventType.PHASE_SWITCH,
            self._on_phase_switch,
        )

    def _on_phase_switch(self, event: PhaseSwitchEvent) -> None:
        self.switch_phase(event.target_phase)
