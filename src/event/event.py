from __future__ import annotations

from datetime import datetime
from enum import StrEnum
import threading
from typing import TYPE_CHECKING, cast

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
    - 已入表事件通过 ``status`` setter 离开 ``PENDING`` 时,状态命令由所属
      ``VenueEngine`` 顺序执行,并与 ``EventList`` 的 pending 队列一起更新.
    - 子类 ``__init__`` 应直接写入私有字段,并用 ``_set_type`` / ``_init_status``.
    - 每个事件只属于一个会场(``venue`` 为会场 ID 字符串).
    """

    _EDITABLE_FIELDS = {
        "content": "_Event__content",
        "scope": "_Event__scope",
    }

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
        self.__submission_claimed = False
        self.__submission_actor_id: str | None = None
        self.__lock = threading.RLock()

    def _require_editable(self, field: str) -> None:
        if self.__status != EventStatus.PENDING:
            raise PermissionError(
                f"事件(id={self.__id!r}, type={self.__type}, venue={self.__venue!r}) 状态为 "
                f"{self.__status.value},不能修改 {field}"
            )

    def _editable_attribute(self, field: str) -> str:
        for event_class in type(self).__mro__:
            fields = event_class.__dict__.get("_EDITABLE_FIELDS")
            if fields is not None and field in fields:
                return fields[field]
        raise AttributeError(f"事件类型 {type(self).__name__} 不支持编辑字段 {field!r}")

    def _validate_edit(self, field: str, value: object) -> None:
        """在 VenueEngine 实际执行字段修改时复核跨字段约束."""

    def _edit(self, field: str, value: object) -> None:
        attribute = self._editable_attribute(field)
        with self.__lock:
            if not self.__submission_claimed:
                self._apply_edit(field, attribute, value)
                return
        self.__scenario._edit_event(self, field, attribute, value)

    def _apply_edit(self, field: str, attribute: str, value: object) -> None:
        """仅供构造线程或所属 VenueEngine 原子落实字段修改."""
        with self.__lock:
            expected = self._editable_attribute(field)
            if attribute != expected:
                raise ValueError(
                    f"事件字段 {field!r} 的内部属性应为 {expected!r},"
                    f"实际为 {attribute!r}"
                )
            self._require_editable(field)
            self._validate_edit(field, value)
            object.__setattr__(self, attribute, value)

    def _claim_submission(self) -> None:
        """由 Venue 在入队临界区声明该事件已进入串行写入生命周期."""
        with self.__lock:
            if self.__submission_claimed:
                raise PermissionError("同一事件不能重复提交")
            self.__submission_claimed = True

    def _set_submission_actor(self, actor_id: str) -> None:
        """记录代表行动来源；仅供提交前的 Representative/Venue 调度使用。"""
        normalized = actor_id.strip()
        if not normalized:
            raise ValueError("事件提交 actor_id 须为非空代表 ID")
        with self.__lock:
            if self.__submission_claimed:
                raise PermissionError("事件进入提交队列后不能修改 actor_id")
            if (
                self.__submission_actor_id is not None
                and self.__submission_actor_id != normalized
            ):
                raise PermissionError(
                    f"事件 actor_id 已设为 {self.__submission_actor_id!r},"
                    f"不能改为 {normalized!r}"
                )
            self.__submission_actor_id = normalized

    @property
    def _submission_actor(self) -> str | None:
        with self.__lock:
            return self.__submission_actor_id

    def _release_submission_claim(self) -> None:
        """仅在命令尚未入队时回滚提交声明."""
        with self.__lock:
            self.__submission_claimed = False

    def _set_type(self, event_type: EventType) -> None:
        if self.__type is not None:
            raise PermissionError("事件 type 不可修改")
        self.__type = event_type

    def _init_status(self, status: EventStatus) -> None:
        """仅供子类构造时设定初始状态(可直接进入终态).

        不走 ``status`` setter,也不通知 EventList(构造时尚未入表).
        """
        self.__status = EventStatus(status)

    def _apply_status(self, status: EventStatus) -> None:
        """仅供所属 EventList 在 VenueEngine 线程中落实状态命令."""
        with self.__lock:
            self._require_editable("status")
            self.__status = status

    @property
    def time(self) -> datetime | None:
        with self.__lock:
            return self.__time

    @time.setter
    def time(self, value: datetime) -> None:
        with self.__lock:
            if self.__time is not None:
                raise PermissionError("事件 time 不可修改")
            self.__time = value

    @property
    def id(self) -> int | None:
        with self.__lock:
            return self.__id

    @id.setter
    def id(self, value: int) -> None:
        with self.__lock:
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
        with self.__lock:
            return self.__status

    @status.setter
    def status(self, value: EventStatus | str) -> None:
        new_status = EventStatus(value)
        with self.__lock:
            if not self.__submission_claimed:
                self._apply_status(new_status)
                return
        self.__scenario._update_event_status(self, new_status)

    @property
    def content(self) -> str:
        with self.__lock:
            return self.__content

    @content.setter
    def content(self, value: str) -> None:
        self._edit("content", value)

    @property
    def scope(self) -> set[str]:
        with self.__lock:
            return set(self.__scope)

    @scope.setter
    def scope(self, value: set[str]) -> None:
        self._edit("scope", set(value))


class SystemEvent(Event):
    _EDITABLE_FIELDS = {"action": "_SystemEvent__action"}

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
        self._edit("action", list(value))


class MotionSwitchEvent(Event):
    """阶段切换动议:仅提案,不改变会场阶段.

    初始为 ``PENDING``;是否通过取决于后续投票或主席裁定.
    真正落地切换请使用 :class:`PhaseSwitchEvent`.
    """

    _EDITABLE_FIELDS = {"target_phase": "_MotionSwitchEvent__target_phase"}

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
        self._edit("target_phase", SessionPhase(value))


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

    _EDITABLE_FIELDS = {
        "instruction": "_InstructionEvent__instruction",
        "from_reps": "_InstructionEvent__from",
    }

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
        self._edit("instruction", value)

    @property
    def from_reps(self) -> set[str]:
        return set(self.__from)

    @from_reps.setter
    def from_reps(self, value: set[str]) -> None:
        self._edit("from_reps", set(value))


class ResolutionEvent(Event):
    """决议类事件:``resolution`` 绑定一份 File(通常为 submission 副本).

    可见性语义同 :class:`InstructionEvent`:经 EventList 可见事件索引,而非文件系统枚举.
    """

    _EDITABLE_FIELDS = {
        "resolution": "_ResolutionEvent__resolution",
        "from_reps": "_ResolutionEvent__from",
    }

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
        self._edit("resolution", value)

    @property
    def from_reps(self) -> set[str]:
        return set(self.__from)

    @from_reps.setter
    def from_reps(self, value: set[str]) -> None:
        self._edit("from_reps", set(value))


class VoteEvent(Event):
    """投票事件:对某次 Resolution 或 MotionSwitch 进行表决记录.

    ``remark`` 用于记录特殊规则,例如有权代表强制通过,安理会常任理事国一票否决等.
    ``named`` 为记名表决:仅记名时可经属性读取具体支持/反对/弃权名单(返回副本);
    不记名时名单属性不可访问,但仍可通过人数属性得知票数.
    """

    _EDITABLE_FIELDS = {
        "target": "_VoteEvent__target",
        "valid_votes": "_VoteEvent__valid_votes",
        "named": "_VoteEvent__named",
        "supporters": "_VoteEvent__supporters",
        "against": "_VoteEvent__against",
        "abstentions": "_VoteEvent__abstentions",
        "pass_mode": "_VoteEvent__pass_mode",
        "passed": "_VoteEvent__passed",
        "remark": "_VoteEvent__remark",
    }

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

    def _validate_edit(self, field: str, value: object) -> None:
        if field == "target":
            target = cast("ResolutionEvent | MotionSwitchEvent", value)
            if target.venue != self.venue:
                raise ValueError(
                    f"VoteEvent.venue={self.venue!r} 与 target.venue="
                    f"{target.venue!r} 不一致"
                )
        elif field == "valid_votes":
            _validate_vote_ballots(
                self.__supporters,
                self.__against,
                self.__abstentions,
                cast(int, value),
            )
        elif field == "supporters":
            _validate_vote_ballots(
                cast(list[str], value),
                self.__against,
                self.__abstentions,
                self.__valid_votes,
            )
        elif field == "against":
            _validate_vote_ballots(
                self.__supporters,
                cast(list[str], value),
                self.__abstentions,
                self.__valid_votes,
            )
        elif field == "abstentions":
            _validate_vote_ballots(
                self.__supporters,
                self.__against,
                cast(list[str], value),
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
        self._edit("target", value)

    @property
    def valid_votes(self) -> int:
        return self.__valid_votes

    @valid_votes.setter
    def valid_votes(self, value: int) -> None:
        if value < 0:
            raise ValueError(f"valid_votes 须为非负整数,实际为: {value!r}")
        self._edit("valid_votes", value)

    @property
    def named(self) -> bool:
        return self.__named

    @named.setter
    def named(self, value: bool) -> None:
        self._edit("named", bool(value))

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
        self._edit(
            "supporters",
            _normalize_rep_list(value, field="supporters"),
        )

    @property
    def against(self) -> list[str]:
        self._require_named_ballots("against")
        return list(self.__against)

    @against.setter
    def against(self, value: list[str]) -> None:
        self._edit("against", _normalize_rep_list(value, field="against"))

    @property
    def abstentions(self) -> list[str]:
        self._require_named_ballots("abstentions")
        return list(self.__abstentions)

    @abstentions.setter
    def abstentions(self, value: list[str]) -> None:
        self._edit(
            "abstentions",
            _normalize_rep_list(value, field="abstentions"),
        )

    @property
    def pass_mode(self) -> VotePassMode:
        return self.__pass_mode

    @pass_mode.setter
    def pass_mode(self, value: VotePassMode | str) -> None:
        self._edit("pass_mode", VotePassMode(value))

    @property
    def passed(self) -> bool | None:
        return self.__passed

    @passed.setter
    def passed(self, value: bool | None) -> None:
        self._edit("passed", value)

    @property
    def remark(self) -> str:
        return self.__remark

    @remark.setter
    def remark(self, value: str) -> None:
        self._edit("remark", value.strip())


class NoteEvent(Event):
    """会议期间的传纸条私聊."""

    _EDITABLE_FIELDS = {
        "from_rep": "_NoteEvent__from",
        "to_reps": "_NoteEvent__to",
    }

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
        if not value.strip():
            raise ValueError("from_rep 须为非空字符串")
        self._edit("from_rep", value.strip())

    @property
    def to_reps(self) -> set[str]:
        return set(self.__to)

    @to_reps.setter
    def to_reps(self, value: set[str]) -> None:
        self._edit("to_reps", set(value))


class MessageEvent(Event):
    """会议期间的消息."""

    _EDITABLE_FIELDS = {"from_rep": "_MessageEvent__from"}

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
        if not value.strip():
            raise ValueError("from_rep 须为非空字符串")
        self._edit("from_rep", value.strip())


class ChatEvent(Event):
    """free discussion 环节的消息."""

    _EDITABLE_FIELDS = {"from_rep": "_ChatEvent__from"}

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
        if not value.strip():
            raise ValueError("from_rep 须为非空字符串")
        self._edit("from_rep", value.strip())


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
