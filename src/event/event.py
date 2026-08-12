from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from scenario.group import Group
from scenario.venue import SessionPhase, Venue

if TYPE_CHECKING:
    from agenda.agenda import Agenda
    from filesystem.filesystem import File
    from scenario.scenario import Scenario


class EventType(StrEnum):
    SYSTEM = "system"
    MOTION_SWITCH = "motion_switch"
    PHASE_SWITCH = "phase_switch"
    ADD_AGENDA = "add_agenda"
    SET_AGENDA = "set_agenda"
    INSTRUCTION = "instruction"
    RESOLUTION = "resolution"
    VOTE = "vote"
    NOTE = "note"
    MESSAGE = "message"
    CHAT = "chat"


class EventStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    ACCEPTED = "accepted"


class VotePassMode(StrEnum):
    """投票通过门槛."""

    SIMPLE_MAJORITY = "simple_majority"  # 1/2 多数
    TWO_THIRDS = "two_thirds"  # 2/3 多数
    UNANIMOUS = "unanimous"  # 全体一致


class Event:
    """事件基类.

    - ``time`` / ``id``:构造时为 ``None``;``time`` 由 Scenario 统一时钟盖戳,
      ``id`` 由所属会场的 ``EventList.submit_event`` 赋值,两者均不可再改;
      ``id`` 仅在事件所属会场的容器内唯一.
    - ``type`` / ``venue``:一旦设定不可再改.
    - 其余属性:仅当 ``status == PENDING`` 时可改.
    - 通过 ``status`` setter 离开 ``PENDING`` 时,若事件已入表,会通知
      所属会场的 ``EventList`` 将其从 pending 队列移除.
    - 子类 ``__init__`` 应直接写入私有字段,并用 ``_set_type`` / ``_init_status``.
    - 每个事件只属于一个会场(``venue`` 为会场 ID 字符串).
    """

    def __init__(
        self,
        content: str,
        venue: str,
        scope: set[str],
        scenario: Scenario,
    ):
        self.__time: datetime | None = None
        self.__content = content
        self.__venue = _normalize_venue_id(venue, scenario)
        self.__scenario = scenario
        self.__id: int | None = None
        self.__scope = set(scope)
        self.__status = EventStatus.PENDING
        self.__type: EventType | None = None

    def _require_editable(self, field: str) -> None:
        if self.__status != EventStatus.PENDING:
            raise PermissionError(
                f"事件(id={self.__id!r}, type={self.__type}, venue={self.__venue!r}) 状态为 "
                f"{self.__status.value},不能修改 {field}"
            )

    def _set_type(self, event_type: EventType) -> None:
        if self.__type is not None:
            raise PermissionError("事件 type 不可修改")
        self.__type = event_type

    def _init_status(self, status: EventStatus) -> None:
        """仅供子类构造时设定初始状态(可直接进入终态).

        不走 ``status`` setter,也不通知 EventList(构造时尚未入表).
        """
        self.__status = EventStatus(status)

    @property
    def time(self) -> datetime | None:
        return self.__time

    @time.setter
    def time(self, value: datetime) -> None:
        if self.__time is not None:
            raise PermissionError("事件 time 不可修改")
        self.__time = value

    @property
    def id(self) -> int | None:
        return self.__id

    @id.setter
    def id(self, value: int) -> None:
        if self.__id is not None:
            raise PermissionError("事件 id 不可修改")
        if value < 0:
            raise ValueError(f"id 须为非负整数,实际为: {value!r}")
        self.__id = value

    @property
    def type(self) -> EventType:
        if self.__type is None:
            raise RuntimeError("事件 type 尚未初始化")
        return self.__type

    @property
    def venue(self) -> str:
        return self.__venue

    @property
    def scenario(self) -> Scenario:
        return self.__scenario

    @property
    def status(self) -> EventStatus:
        return self.__status

    @status.setter
    def status(self, value: EventStatus | str) -> None:
        self._require_editable("status")
        new_status = EventStatus(value)
        self.__status = new_status
        if new_status == EventStatus.PENDING or self.__id is None:
            return
        self.__scenario._event_updated(self)

    @property
    def content(self) -> str:
        return self.__content

    @content.setter
    def content(self, value: str) -> None:
        self._require_editable("content")
        self.__content = value

    @property
    def scope(self) -> set[str]:
        return set(self.__scope)

    @scope.setter
    def scope(self, value: set[str]) -> None:
        self._require_editable("scope")
        self.__scope = set(value)


class SystemEvent(Event):
    def __init__(
        self,
        content: str,
        action: list[str],
        venue: str,
        scope: set[str],
        scenario: Scenario,
    ):
        super().__init__(content, venue, scope, scenario)
        self._set_type(EventType.SYSTEM)
        self.__action = list(action)
        self._init_status(EventStatus.COMPLETED)

    @property
    def action(self) -> list[str]:
        return list(self.__action)

    @action.setter
    def action(self, value: list[str]) -> None:
        self._require_editable("action")
        self.__action = list(value)


class MotionSwitchEvent(Event):
    """阶段切换动议:仅提案,不改变会场阶段.

    初始为 ``PENDING``;是否通过取决于后续投票或主席裁定.
    真正落地切换请使用 :class:`PhaseSwitchEvent`.
    """

    def __init__(
        self,
        content: str,
        target_phase: SessionPhase,
        venue: str,
        scope: set[str],
        scenario: Scenario,
    ):
        super().__init__(content, venue, scope, scenario)
        self._set_type(EventType.MOTION_SWITCH)
        self.__target_phase = SessionPhase(target_phase)

    @property
    def target_phase(self) -> SessionPhase:
        return self.__target_phase

    @target_phase.setter
    def target_phase(self, value: SessionPhase | str) -> None:
        self._require_editable("target_phase")
        self.__target_phase = SessionPhase(value)


class PhaseSwitchEvent(Event):
    """会场阶段切换事件:记录目标阶段,入表后由 Venue listener 落地 ``session_phase``.

    与 :class:`MotionSwitchEvent` 不同——后者只是动议;本事件表示阶段变更已裁定.
    构造时只读取并保存切换前阶段,不改会场状态;``EventList.submit_event`` 通知
    对应会场 listener 后才调用 ``Venue.switch_phase``.状态直接为 ``COMPLETED``.
    """

    def __init__(
        self,
        content: str,
        target_phase: SessionPhase,
        venue: str,
        scope: set[str],
        scenario: Scenario,
    ):
        super().__init__(content, venue, scope, scenario)
        self._set_type(EventType.PHASE_SWITCH)
        venue_obj = _find_venue(scenario, self.venue)
        self.__previous_phase = venue_obj.session_phase
        self.__target_phase = SessionPhase(target_phase)
        self._init_status(EventStatus.COMPLETED)

    @property
    def previous_phase(self) -> SessionPhase | None:
        return self.__previous_phase

    @property
    def target_phase(self) -> SessionPhase:
        return self.__target_phase


class AddAgendaEvent(Event):
    """主席向会场 todo 追加议题的记录事件(状态直接 COMPLETED)."""

    def __init__(
        self,
        content: str,
        agenda: Agenda,
        fr: str,
        venue: str,
        scope: set[str],
        scenario: Scenario,
    ):
        super().__init__(content, venue, scope, scenario)
        self._set_type(EventType.ADD_AGENDA)
        self.__agenda = agenda
        self.__from = fr
        self._init_status(EventStatus.COMPLETED)

    @property
    def agenda(self) -> Agenda:
        return self.__agenda

    @property
    def from_rep(self) -> str:
        return self.__from


class SetAgendaEvent(Event):
    """主席切换当前议题的记录事件(状态直接 COMPLETED).

    ``finished`` 表示切换时是否将原当前议题记入 finished;
    ``previous`` 为切换前的当前议题(若有).
    """

    def __init__(
        self,
        content: str,
        agenda: Agenda,
        fr: str,
        venue: str,
        scope: set[str],
        scenario: Scenario,
        *,
        finished: bool = False,
        previous: Agenda | None = None,
    ):
        super().__init__(content, venue, scope, scenario)
        self._set_type(EventType.SET_AGENDA)
        self.__agenda = agenda
        self.__from = fr
        self.__finished = bool(finished)
        self.__previous = previous
        self._init_status(EventStatus.COMPLETED)

    @property
    def agenda(self) -> Agenda:
        return self.__agenda

    @property
    def from_rep(self) -> str:
        return self.__from

    @property
    def finished(self) -> bool:
        return self.__finished

    @property
    def previous(self) -> Agenda | None:
        return self.__previous


class InstructionEvent(Event):
    """指示类事件:``instruction`` 绑定一份 File(通常为 submission 副本).

    事件落在代表 scope 内时,该代表可通过本事件索引得知并访问该文件;
    不能通过 FileSystem.list_visible 直接发现 submissions/.
    """

    def __init__(
        self,
        content: str,
        fr: set[str],
        instruction: File,
        venue: str,
        scenario: Scenario,
    ):
        super().__init__(content, venue, fr, scenario)
        self._set_type(EventType.INSTRUCTION)
        self.__instruction = instruction
        self.__from = set(fr)

    @property
    def instruction(self) -> File:
        return self.__instruction

    @instruction.setter
    def instruction(self, value: File) -> None:
        self._require_editable("instruction")
        self.__instruction = value

    @property
    def from_reps(self) -> set[str]:
        return set(self.__from)

    @from_reps.setter
    def from_reps(self, value: set[str]) -> None:
        self._require_editable("from_reps")
        self.__from = set(value)


class ResolutionEvent(Event):
    """决议类事件:``resolution`` 绑定一份 File(通常为 submission 副本).

    可见性语义同 :class:`InstructionEvent`:经 EventList 可见事件索引,而非文件系统枚举.
    """

    def __init__(
        self,
        content: str,
        fr: set[str],
        resolution: File,
        venue: str,
        scenario: Scenario,
    ):
        super().__init__(content, venue, fr, scenario)
        self._set_type(EventType.RESOLUTION)
        self.__resolution = resolution
        self.__from = set(fr)

    @property
    def resolution(self) -> File:
        return self.__resolution

    @resolution.setter
    def resolution(self, value: File) -> None:
        self._require_editable("resolution")
        self.__resolution = value

    @property
    def from_reps(self) -> set[str]:
        return set(self.__from)

    @from_reps.setter
    def from_reps(self, value: set[str]) -> None:
        self._require_editable("from_reps")
        self.__from = set(value)


class VoteEvent(Event):
    """投票事件:对某次 Resolution 或 MotionSwitch 进行表决记录.

    ``remark`` 用于记录特殊规则,例如有权代表强制通过,安理会常任理事国一票否决等.
    ``named`` 为记名表决:仅记名时可经属性读取具体支持/反对/弃权名单(返回副本);
    不记名时名单属性不可访问,但仍可通过人数属性得知票数.
    """

    def __init__(
        self,
        content: str,
        venue: str,
        scope: set[str],
        target: ResolutionEvent | MotionSwitchEvent,
        valid_votes: int,
        pass_mode: VotePassMode | str,
        scenario: Scenario,
        *,
        supporters: list[str] | None = None,
        against: list[str] | None = None,
        abstentions: list[str] | None = None,
        passed: bool | None = None,
        remark: str = "",
        named: bool = True,
    ):
        if valid_votes < 0:
            raise ValueError(f"valid_votes 须为非负整数,实际为: {valid_votes!r}")

        mode = VotePassMode(pass_mode)
        support_list = _normalize_rep_list(supporters or [], field="supporters")
        against_list = _normalize_rep_list(against or [], field="against")
        abstain_list = _normalize_rep_list(abstentions or [], field="abstentions")
        _validate_vote_ballots(support_list, against_list, abstain_list, valid_votes)

        super().__init__(content, venue, scope, scenario)
        if target.venue != self.venue:
            raise ValueError(
                f"VoteEvent.venue={self.venue!r} 与 target.venue={target.venue!r} 不一致"
            )
        self._set_type(EventType.VOTE)
        self.__target = target
        self.__valid_votes = valid_votes
        self.__supporters = support_list
        self.__against = against_list
        self.__abstentions = abstain_list
        self.__pass_mode = mode
        self.__passed = passed
        self.__remark = remark.strip()
        self.__named = bool(named)
        if passed is True:
            self._init_status(EventStatus.COMPLETED)
        elif passed is False:
            self._init_status(EventStatus.REJECTED)

    def _revalidate_ballots(self) -> None:
        _validate_vote_ballots(
            self.__supporters,
            self.__against,
            self.__abstentions,
            self.__valid_votes,
        )

    def _require_named_ballots(self, field: str) -> None:
        if not self.__named:
            raise PermissionError(
                f"事件(id={self.id!r}, type={self.type}, venue={self.venue!r}) "
                f"为不记名投票,不能访问 {field}"
            )

    @property
    def target(self) -> ResolutionEvent | MotionSwitchEvent:
        return self.__target

    @target.setter
    def target(self, value: ResolutionEvent | MotionSwitchEvent) -> None:
        self._require_editable("target")
        if value.venue != self.venue:
            raise ValueError(
                f"VoteEvent.venue={self.venue!r} 与 target.venue={value.venue!r} 不一致"
            )
        self.__target = value

    @property
    def valid_votes(self) -> int:
        return self.__valid_votes

    @valid_votes.setter
    def valid_votes(self, value: int) -> None:
        self._require_editable("valid_votes")
        if value < 0:
            raise ValueError(f"valid_votes 须为非负整数,实际为: {value!r}")
        self.__valid_votes = value
        self._revalidate_ballots()

    @property
    def named(self) -> bool:
        return self.__named

    @named.setter
    def named(self, value: bool) -> None:
        self._require_editable("named")
        self.__named = bool(value)

    @property
    def support_count(self) -> int:
        return len(self.__supporters)

    @property
    def against_count(self) -> int:
        return len(self.__against)

    @property
    def abstention_count(self) -> int:
        return len(self.__abstentions)

    @property
    def supporters(self) -> list[str]:
        self._require_named_ballots("supporters")
        return list(self.__supporters)

    @supporters.setter
    def supporters(self, value: list[str]) -> None:
        self._require_editable("supporters")
        self.__supporters = _normalize_rep_list(value, field="supporters")
        self._revalidate_ballots()

    @property
    def against(self) -> list[str]:
        self._require_named_ballots("against")
        return list(self.__against)

    @against.setter
    def against(self, value: list[str]) -> None:
        self._require_editable("against")
        self.__against = _normalize_rep_list(value, field="against")
        self._revalidate_ballots()

    @property
    def abstentions(self) -> list[str]:
        self._require_named_ballots("abstentions")
        return list(self.__abstentions)

    @abstentions.setter
    def abstentions(self, value: list[str]) -> None:
        self._require_editable("abstentions")
        self.__abstentions = _normalize_rep_list(value, field="abstentions")
        self._revalidate_ballots()

    @property
    def pass_mode(self) -> VotePassMode:
        return self.__pass_mode

    @pass_mode.setter
    def pass_mode(self, value: VotePassMode | str) -> None:
        self._require_editable("pass_mode")
        self.__pass_mode = VotePassMode(value)

    @property
    def passed(self) -> bool | None:
        return self.__passed

    @passed.setter
    def passed(self, value: bool | None) -> None:
        self._require_editable("passed")
        self.__passed = value

    @property
    def remark(self) -> str:
        return self.__remark

    @remark.setter
    def remark(self, value: str) -> None:
        self._require_editable("remark")
        self.__remark = value.strip()


class NoteEvent(Event):
    """会议期间的传纸条私聊."""

    def __init__(
        self,
        content: str,
        fr: str,
        to: set[str],
        venue: str,
        scenario: Scenario,
    ):
        super().__init__(content, venue, {fr} | to, scenario)
        self._set_type(EventType.NOTE)
        self.__from = fr
        self.__to = set(to)
        self._init_status(EventStatus.COMPLETED)

    @property
    def from_rep(self) -> str:
        return self.__from

    @from_rep.setter
    def from_rep(self, value: str) -> None:
        self._require_editable("from_rep")
        if not value.strip():
            raise ValueError("from_rep 须为非空字符串")
        self.__from = value.strip()

    @property
    def to_reps(self) -> set[str]:
        return set(self.__to)

    @to_reps.setter
    def to_reps(self, value: set[str]) -> None:
        self._require_editable("to_reps")
        self.__to = set(value)


class MessageEvent(Event):
    """会议期间的消息."""

    def __init__(
        self,
        content: str,
        fr: str,
        venue: str,
        scenario: Scenario,
    ):
        seats = _venue_seats(scenario, venue)
        super().__init__(content, venue, set(seats), scenario)
        self._set_type(EventType.MESSAGE)
        self.__from = fr
        self._init_status(EventStatus.COMPLETED)

    @property
    def from_rep(self) -> str:
        return self.__from

    @from_rep.setter
    def from_rep(self, value: str) -> None:
        self._require_editable("from_rep")
        if not value.strip():
            raise ValueError("from_rep 须为非空字符串")
        self.__from = value.strip()


class ChatEvent(Event):
    """free discussion 环节的消息."""

    def __init__(
        self,
        content: str,
        fr: str,
        group: Group,
        venue: str,
        scenario: Scenario,
    ):
        super().__init__(content, venue, group.members, scenario)
        self._set_type(EventType.CHAT)
        self.__from = fr
        self._init_status(EventStatus.COMPLETED)

    @property
    def from_rep(self) -> str:
        return self.__from

    @from_rep.setter
    def from_rep(self, value: str) -> None:
        self._require_editable("from_rep")
        if not value.strip():
            raise ValueError("from_rep 须为非空字符串")
        self.__from = value.strip()


def _normalize_venue_id(venue: str, scenario: Scenario) -> str:
    if not venue.strip():
        raise ValueError("venue 须为非空会场 ID 字符串")
    venue_id = venue.strip()
    known = {item.id for item in scenario.venues}
    if known and venue_id not in known:
        raise ValueError(f"未知会场 ID: {venue_id}")
    return venue_id


def _find_venue(scenario: Scenario, venue: str) -> Venue:
    venue_id = _normalize_venue_id(venue, scenario)
    for item in scenario.venues:
        if item.id == venue_id:
            return item
    raise ValueError(f"未知会场 ID: {venue_id}")


def _venue_seats(scenario: Scenario, venue: str) -> list[str]:
    return list(_find_venue(scenario, venue).seats)


def _normalize_rep_list(values: list[str], *, field: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(values):
        if not item.strip():
            raise ValueError(f"{field}[{index}] 须为非空代表 ID 字符串")
        rep_id = item.strip()
        if rep_id in seen:
            raise ValueError(f"{field} 存在重复代表 ID: {rep_id}")
        seen.add(rep_id)
        result.append(rep_id)
    return result


def _validate_vote_ballots(
    supporters: list[str],
    against: list[str],
    abstentions: list[str],
    valid_votes: int,
) -> None:
    buckets = (
        ("supporters", supporters),
        ("against", against),
        ("abstentions", abstentions),
    )
    seen: dict[str, str] = {}
    for field, reps in buckets:
        for rep_id in reps:
            if rep_id in seen:
                raise ValueError(
                    f"代表 {rep_id} 同时出现在 {seen[rep_id]} 与 {field} 中"
                )
            seen[rep_id] = field

    cast = len(supporters) + len(against) + len(abstentions)
    if cast > valid_votes:
        raise ValueError(
            f"支持/反对/弃权合计 {cast} 超过总有效票数 valid_votes={valid_votes}"
        )
