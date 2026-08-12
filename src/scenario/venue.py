from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from queue import Queue
import threading
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


@dataclass(frozen=True)
class EventSubmission:
    event: Event
    time: datetime
    result: Future[Event]


class _StopEventProcessing:
    pass


_STOP_EVENT_PROCESSING = _StopEventProcessing()


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
    __event_queue: Queue[EventSubmission | _StopEventProcessing] | None
    __event_processing: threading.Event
    __event_submission_lock: threading.Lock

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
        self.__event_queue = None
        self.__event_processing = threading.Event()
        self.__event_submission_lock = threading.Lock()

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

    def _require_event_queue(
        self,
    ) -> Queue[EventSubmission | _StopEventProcessing]:
        event_queue = self.__event_queue
        if event_queue is None:
            raise RuntimeError(
                f"会场 {self.id or '<unset>'} 尚未 initialize 事件队列"
            )
        return event_queue

    def submit_event(self, event: Event) -> Event:
        """提交事件并等待所属 VenueEngine 返回处理结果.

        事件先进入本会场的线程安全队列；调用线程不会直接写入 ``EventList``。
        """
        event_time = self.scenario._event_submission_time(event)
        return self._submit_event(event, event_time)

    def _submit_event(self, event: Event, event_time: datetime) -> Event:
        """按指定剧情时间入队；仅供 Scenario 广播定时事件时使用."""
        if event.venue != self.id:
            raise ValueError(
                f"事件 venue={event.venue!r} 不能提交给会场 {self.id!r}"
            )
        self._require_event_list()
        event_queue = self._require_event_queue()
        result: Future[Event] = Future()
        submission = EventSubmission(event, event_time, result)
        with self.__event_submission_lock:
            if not self.__event_processing.is_set():
                raise RuntimeError(
                    f"会场 {self.id!r} 的 VenueEngine 尚未运行或已经停止,"
                    "不能提交事件"
                )
            event_queue.put(submission)
        return result.result()

    def _start_event_processing(self) -> None:
        """标记 VenueEngine 已成为本会场事件队列的唯一消费者."""
        self._require_event_list()
        self._require_event_queue()
        with self.__event_submission_lock:
            if self.__event_processing.is_set():
                raise RuntimeError(f"会场 {self.id!r} 的事件处理循环已运行")
            self.__event_processing.set()

    def _stop_event_processing(self) -> None:
        """停止接受新事件，并让 VenueEngine 处理完已入队事件后退出."""
        event_queue = self._require_event_queue()
        with self.__event_submission_lock:
            if not self.__event_processing.is_set():
                return
            self.__event_processing.clear()
            event_queue.put(_STOP_EVENT_PROCESSING)

    def _take_event_submission(
        self,
    ) -> EventSubmission | _StopEventProcessing:
        return self._require_event_queue().get()

    def _event_submission_done(self) -> None:
        self._require_event_queue().task_done()

    def _commit_event(self, submission: EventSubmission) -> None:
        """由 VenueEngine 为事件盖戳并写入本会场 EventList."""
        self.scenario._stamp_event(submission.event, submission.time)
        self._require_event_list()._commit_event(submission.event)

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
        """创建本会场 EventList、提交队列并注册 PHASE_SWITCH listener."""
        from event.event import EventType
        from event.eventlist import EventList

        if self.event_list is not None:
            raise RuntimeError(
                f"会场 {self.id or '<unset>'} 已 initialize EventList,不能重复初始化"
            )
        self.event_list = EventList(self)
        self.__event_queue = Queue()
        self.__event_processing.clear()
        self.event_list.add_listener(
            EventType.PHASE_SWITCH,
            self._on_phase_switch,
        )

    def _on_phase_switch(self, event: PhaseSwitchEvent) -> None:
        self.switch_phase(event.target_phase)
