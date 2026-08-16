from __future__ import annotations

from concurrent.futures import (
    Future,
    InvalidStateError,
    TimeoutError as FutureTimeoutError,
)
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from queue import Queue
import threading
from typing import TYPE_CHECKING, TypeVar, cast

if TYPE_CHECKING:
    from agenda.agenda import Agenda, AgendaManager
    from event.event import Event, EventStatus, PhaseSwitchEvent
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
    actor_id: str | None = None


@dataclass(frozen=True)
class EventStatusUpdate:
    event: Event
    status: EventStatus
    result: Future[EventStatus]


@dataclass(frozen=True)
class EventEdit:
    event: Event
    field: str
    attribute: str
    value: object
    result: Future[None]


@dataclass(frozen=True)
class AgendaSwitch:
    rep_id: str
    agenda: Agenda
    finished: bool
    time: datetime
    result: Future[None]


@dataclass(frozen=True)
class AgendaAddition:
    rep_id: str
    agenda: Agenda
    time: datetime
    result: Future[None]


VenueCommand = (
    EventSubmission
    | EventStatusUpdate
    | EventEdit
    | AgendaSwitch
    | AgendaAddition
)


class VenueEngineReentryError(RuntimeError):
    """VenueEngine listener 不能同步等待自己的命令队列."""


class VenueCommandTimeoutError(TimeoutError):
    """Venue 命令超过等待期限，所属引擎已被封闭."""

    venue_id: str
    command_name: str
    timeout_s: float

    def __init__(self, venue_id: str, command_name: str, timeout_s: float) -> None:
        self.venue_id = venue_id
        self.command_name = command_name
        self.timeout_s = timeout_s
        super().__init__(
            f"会场 {venue_id!r} 的 {command_name} 命令在 {timeout_s:g} 秒内未完成，"
            "VenueEngine 已停止接受新命令"
        )


class VenueEngineStoppedError(RuntimeError):
    """VenueEngine 已停止，提交线程不能再等待对应命令."""

    venue_id: str
    engine_failure: BaseException | None

    def __init__(
        self,
        venue_id: str,
        engine_failure: BaseException | None = None,
    ) -> None:
        self.venue_id = venue_id
        self.engine_failure = engine_failure
        if engine_failure is None:
            detail = "VenueEngine 已停止"
        else:
            detail = (
                "VenueEngine 异常退出: "
                f"{type(engine_failure).__name__}: {engine_failure}"
            )
        super().__init__(f"会场 {venue_id!r} 的 {detail}，命令未能完成")
        if engine_failure is not None:
            self.__cause__ = engine_failure


class _StopEventProcessing:
    pass


_STOP_EVENT_PROCESSING = _StopEventProcessing()

_T = TypeVar("_T")


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
    __event_queue: Queue[VenueCommand | _StopEventProcessing] | None
    __event_processing: threading.Event
    __event_submission_lock: threading.RLock
    __pending_results: set[Future[object]]
    __event_failure: BaseException | None
    __event_thread_id: int | None
    command_timeout_s: float

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
        self.__event_submission_lock = threading.RLock()
        self.__pending_results = set()
        self.__event_failure = None
        self.__event_thread_id = None
        self.command_timeout_s = 30.0

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
    ) -> Queue[VenueCommand | _StopEventProcessing]:
        event_queue = self.__event_queue
        if event_queue is None:
            raise RuntimeError(
                f"会场 {self.id or '<unset>'} 尚未 initialize 事件队列"
            )
        return event_queue

    def submit_event(self, event: Event) -> Event:
        """提交事件并等待所属 VenueEngine 返回处理结果.

        事件先进入本会场的线程安全命令队列；调用线程不会直接写入 ``EventList``。
        """
        event_time = self.scenario._event_submission_time(event)
        return self._submit_event(event, event_time)

    def _submit_event(
        self,
        event: Event,
        event_time: datetime,
        *,
        actor_id: str | None = None,
    ) -> Event:
        """按指定剧情时间入队；仅供 Scenario 广播定时事件时使用."""
        if event.venue != self.id:
            raise ValueError(
                f"事件 venue={event.venue!r} 不能提交给会场 {self.id!r}"
            )
        self._require_event_list()
        self._require_event_queue()
        result: Future[Event] = Future()
        submission = EventSubmission(
            event,
            event_time,
            result,
            actor_id if actor_id is not None else event._submission_actor,
        )
        self._submit_command(submission)
        return self._wait_command_result(result, "event_submission")

    def _submit_command(self, command: VenueCommand) -> None:
        """将状态命令放入队列；所有调用方均在各自的 Future 上等待结果."""
        with self.__event_submission_lock:
            self._require_command_submission_locked()
            if isinstance(command, EventSubmission):
                command.event._claim_submission()
                try:
                    self._queue_command_locked(command)
                except BaseException:
                    command.event._release_submission_claim()
                    raise
            else:
                self._queue_command_locked(command)

    def _require_command_submission_locked(self) -> None:
        if self.__event_thread_id == threading.get_ident():
            raise VenueEngineReentryError(
                f"会场 {self.id!r} 的 VenueEngine listener/命令处理器不能同步"
                "提交同一会场命令"
            )
        if not self.__event_processing.is_set():
            raise VenueEngineStoppedError(self.id, self.__event_failure)

    def _queue_command_locked(self, command: VenueCommand) -> None:
        result = cast(Future[object], command.result)
        self.__pending_results.add(result)
        result.add_done_callback(self._discard_pending_result)
        self._require_event_queue().put(command)

    def _wait_command_result(
        self,
        result: Future[_T],
        command_name: str,
    ) -> _T:
        """限时等待命令；超时即封闭 Venue，避免其他 Agent 永久等待."""
        try:
            return result.result(timeout=self.command_timeout_s)
        except FutureTimeoutError:
            if result.done():
                return result.result()
            failure = VenueCommandTimeoutError(
                self.id,
                command_name,
                self.command_timeout_s,
            )
            self._finish_event_processing(failure)
            raise failure

    def _discard_pending_result(self, result: Future[object]) -> None:
        with self.__event_submission_lock:
            self.__pending_results.discard(result)

    @property
    def event_failure(self) -> BaseException | None:
        """命令处理失败原因；供 Simulator 监督线程读取."""
        with self.__event_submission_lock:
            return self.__event_failure

    def _update_event_status(self, event: Event, status: EventStatus) -> EventStatus:
        """将已入表事件的状态变更交给本会场 VenueEngine 顺序执行."""
        if event.venue != self.id:
            raise ValueError(
                f"事件 venue={event.venue!r} 不能由会场 {self.id!r} 更新状态"
            )
        self._require_event_list()
        result: Future[EventStatus] = Future()
        self._submit_command(EventStatusUpdate(event, status, result))
        return self._wait_command_result(result, "event_status_update")

    def _edit_event(
        self,
        event: Event,
        field: str,
        attribute: str,
        value: object,
    ) -> None:
        """将已提交事件的字段修改交给本会场 VenueEngine 顺序执行."""
        if event.venue != self.id:
            raise ValueError(
                f"事件 venue={event.venue!r} 不能由会场 {self.id!r} 编辑"
            )
        self._require_event_list()
        result: Future[None] = Future()
        self._submit_command(EventEdit(event, field, attribute, value, result))
        self._wait_command_result(result, f"event_edit:{field}")

    def _start_event_processing(self) -> None:
        """标记 VenueEngine 已成为本会场命令队列的唯一消费者."""
        self._require_event_list()
        self._require_event_queue()
        with self.__event_submission_lock:
            if self.__event_processing.is_set():
                raise RuntimeError(f"会场 {self.id!r} 的事件处理循环已运行")
            if self.__event_failure is not None:
                raise VenueEngineStoppedError(self.id, self.__event_failure)
            self.__event_thread_id = threading.get_ident()
            self.__event_processing.set()

    def _stop_event_processing(self) -> None:
        """停止接受新命令，并让 VenueEngine 处理完已入队命令后退出."""
        event_queue = self._require_event_queue()
        with self.__event_submission_lock:
            if not self.__event_processing.is_set():
                return
            self.__event_processing.clear()
            event_queue.put(_STOP_EVENT_PROCESSING)

    def _finish_event_processing(self, failure: BaseException | None) -> None:
        """结束消费循环并让所有未完成命令立即失败."""
        with self.__event_submission_lock:
            was_processing = self.__event_processing.is_set()
            self.__event_processing.clear()
            self.__event_thread_id = None
            if failure is not None and self.__event_failure is None:
                self.__event_failure = failure
            pending = list(self.__pending_results)
            self.__pending_results.clear()
            if failure is not None and was_processing:
                self._require_event_queue().put(_STOP_EVENT_PROCESSING)

        for result in pending:
            if result.done():
                continue
            try:
                result.set_exception(
                    VenueEngineStoppedError(self.id, self.__event_failure)
                )
            except InvalidStateError:
                pass

    def _take_command(
        self,
    ) -> VenueCommand | _StopEventProcessing:
        return self._require_event_queue().get()

    def _command_done(self) -> None:
        self._require_event_queue().task_done()

    def _commit_event(self, submission: EventSubmission) -> None:
        """由 VenueEngine 为事件盖戳并写入本会场 EventList."""
        self.scenario._stamp_event(submission.event, submission.time)
        self._require_event_list()._commit_event(submission.event)

    def _commit_event_status(self, update: EventStatusUpdate) -> EventStatus:
        """由 VenueEngine 原子更新事件状态及 EventList.pending."""
        return self._require_event_list()._update_event_status(
            update.event,
            update.status,
        )

    def _commit_event_edit(self, edit: EventEdit) -> None:
        """由 VenueEngine 原子校验事件归属并修改 PENDING 字段."""
        self._require_event_list()._edit_event(
            edit.event,
            edit.field,
            edit.attribute,
            edit.value,
        )

    def _agenda_event_scope(self) -> set[str]:
        return set(self.seats)

    def set_current_agenda(
        self,
        rep_id: str,
        agenda: Agenda,
        finished: bool = False,
    ) -> None:
        """将主席的议题切换命令交给 VenueEngine 顺序执行并记录事件."""
        result: Future[None] = Future()
        self._submit_command(
            AgendaSwitch(
                rep_id,
                agenda,
                finished,
                self.scenario.time,
                result,
            )
        )
        self._wait_command_result(result, "agenda_switch")

    def _commit_agenda_switch(self, command: AgendaSwitch) -> Event | None:
        """由 VenueEngine 修改议题状态并提交对应 SetAgendaEvent."""
        from event.event import SetAgendaEvent

        self._require_chair_actor(command.rep_id)
        manager = self._require_agenda_manager()
        previous = manager.current_agenda
        if command.agenda is previous:
            return None
        manager.set_current_agenda(command.agenda, finished=command.finished)
        event = SetAgendaEvent(
            f"主席 {command.rep_id} 将当前议题切换为 {command.agenda.id}",
            command.agenda,
            command.rep_id,
            self.id,
            self._agenda_event_scope(),
            self.scenario,
            finished=command.finished,
            previous=previous,
        )
        self.scenario._stamp_event(event, command.time)
        self._require_event_list()._commit_event(event)
        return event

    def add_agenda(self, rep_id: str, agenda: Agenda) -> None:
        """将主席的议题新增命令交给 VenueEngine 顺序执行并记录事件."""
        result: Future[None] = Future()
        self._submit_command(
            AgendaAddition(
                rep_id,
                agenda,
                self.scenario.time,
                result,
            )
        )
        self._wait_command_result(result, "agenda_addition")

    def _commit_agenda_addition(self, command: AgendaAddition) -> Event:
        """由 VenueEngine 修改议题状态并提交对应 AddAgendaEvent."""
        from event.event import AddAgendaEvent

        self._require_chair_actor(command.rep_id)
        self._require_agenda_manager().add_todo(command.agenda)
        event = AddAgendaEvent(
            f"主席 {command.rep_id} 追加议题 {command.agenda.id}",
            command.agenda,
            command.rep_id,
            self.id,
            self._agenda_event_scope(),
            self.scenario,
        )
        self.scenario._stamp_event(event, command.time)
        self._require_event_list()._commit_event(event)
        return event

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
        event._set_submission_actor(rep_id)
        self.submit_event(event)
        return event

    def initialize(self) -> None:
        """创建本会场 EventList、命令队列并注册 PHASE_SWITCH listener."""
        from event.event import EventType
        from event.eventlist import EventList

        if self.event_list is not None:
            raise RuntimeError(
                f"会场 {self.id or '<unset>'} 已 initialize EventList,不能重复初始化"
            )
        self.event_list = EventList(self)
        self.__event_queue = Queue()
        self.__event_processing.clear()
        self.__pending_results = set()
        self.__event_failure = None
        self.__event_thread_id = None
        self.event_list.add_listener(
            EventType.PHASE_SWITCH,
            self._on_phase_switch,
        )

    def _on_phase_switch(self, event: PhaseSwitchEvent) -> None:
        self.switch_phase(event.target_phase)
