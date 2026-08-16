"""ChairAgent 的程序性工具与硬权限校验。"""

from __future__ import annotations

import json
from typing import Any, Callable

from agenda.agenda import Agenda
from event.event import (
    ChairAction,
    ChairEvent,
    Event,
    EventStatus,
    MotionSwitchEvent,
    PhaseSwitchEvent,
    ResolutionEvent,
    EventType,
    VoteEvent,
    VotePassMode,
)
from llm import ToolCall, ToolSpec
from filesystem.filesystem import SYSTEM_ACTOR
from scenario.venue import (
    CHAIR_POWER,
    SYSTEM_CHAIR_ACTOR,
    SessionPhase,
    Venue,
    VenueEngineStoppedError,
)


def _tool(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        parameters={
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        },
    )


_REP_LIST = {
    "type": "array",
    "items": {"type": "string"},
    "description": "会场代表 ID 列表",
}

CHAIR_TOOL_SPECS = [
    _tool("get_meeting_state", "查看当前阶段、议程、未决事项和主席权力", {}),
    _tool(
        "list_recent_events",
        "列出主席可见的最近会场事件，供恢复程序上下文",
        {
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 50,
            }
        },
    ),
    _tool(
        "read_submission",
        "分段读取主席可见的正式决议正文",
        {
            "event_id": {"type": "integer", "minimum": 0},
            "offset": {"type": "integer", "minimum": 0},
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 8000,
            },
        },
        ["event_id"],
    ),
    _tool(
        "publish_notice",
        "发布全场可见但不要求代表立即回应的程序通知",
        {"content": {"type": "string", "description": "通知正文"}},
        ["content"],
    ),
    _tool(
        "call_speaker",
        "点名一名代表发言；只有被点名者会立即激活",
        {
            "rep_id": {"type": "string", "description": "被点名代表 ID"},
            "content": {"type": "string", "description": "发言主题或要求"},
        },
        ["rep_id", "content"],
    ),
    _tool(
        "request_vote",
        "宣布对一个未决决议或阶段动议开始表决",
        {
            "event_id": {"type": "integer", "minimum": 0},
            "content": {"type": "string", "description": "表决事项与程序说明"},
        },
        ["event_id", "content"],
    ),
    _tool(
        "record_vote",
        "记录记名表决并按门槛裁定目标决议或阶段动议",
        {
            "event_id": {"type": "integer", "minimum": 0},
            "supporters": _REP_LIST,
            "against": _REP_LIST,
            "abstentions": _REP_LIST,
            "pass_mode": {
                "type": "string",
                "enum": [mode.value for mode in VotePassMode],
            },
            "remark": {"type": "string", "description": "特殊规则或说明"},
        },
        ["event_id", "supporters", "against", "abstentions", "pass_mode"],
    ),
    _tool(
        "decide_resolution",
        "直接裁定未决决议；仅在主席拥有 decide_resolution 权力时可用",
        {
            "event_id": {"type": "integer", "minimum": 0},
            "decision": {
                "type": "string",
                "enum": [EventStatus.ACCEPTED.value, EventStatus.REJECTED.value],
            },
            "reason": {"type": "string", "description": "可审计的裁定理由"},
        },
        ["event_id", "decision", "reason"],
    ),
    _tool(
        "switch_phase",
        "落实会议阶段切换；须有直接裁定权或对应的已通过动议",
        {
            "target_phase": {
                "type": "string",
                "enum": [phase.value for phase in SessionPhase],
            },
            "content": {"type": "string", "description": "切换说明"},
            "motion_event_id": {
                "type": "integer",
                "minimum": 0,
                "description": "无直接裁定权时必填：已通过的阶段动议 ID",
            },
        },
        ["target_phase", "content"],
    ),
    _tool(
        "set_current_agenda",
        "切换到会场中已有的待审议议题",
        {
            "agenda_id": {"type": "string"},
            "finished": {
                "type": "boolean",
                "description": "是否将原议题记入 finished",
            },
        },
        ["agenda_id"],
    ),
    _tool(
        "add_agenda",
        "向会场追加新议题",
        {
            "agenda_id": {"type": "string"},
            "title": {"type": "string"},
            "questions": {"type": "array", "items": {"type": "string"}},
        },
        ["agenda_id", "title", "questions"],
    ),
]


class ChairToolExecutor:
    """只暴露主席职责动作；不提供代表发言、文件或秘密通信工具。"""

    def __init__(self, venue: Venue) -> None:
        self.venue = venue
        self.__successful_tools: list[str] = []
        self.__action_count = 0
        self.action_limit = 6
        self.__handlers: dict[str, Callable[[dict[str, Any]], object]] = {
            "get_meeting_state": self._get_meeting_state,
            "list_recent_events": self._list_recent_events,
            "read_submission": self._read_submission,
            "publish_notice": self._publish_notice,
            "call_speaker": self._call_speaker,
            "request_vote": self._request_vote,
            "record_vote": self._record_vote,
            "decide_resolution": self._decide_resolution,
            "switch_phase": self._switch_phase,
            "set_current_agenda": self._set_current_agenda,
            "add_agenda": self._add_agenda,
        }

    @property
    def tool_specs(self) -> list[ToolSpec]:
        return list(CHAIR_TOOL_SPECS)

    @property
    def successful_tools(self) -> list[str]:
        return list(self.__successful_tools)

    def begin_turn(self) -> None:
        self.__successful_tools = []
        self.__action_count = 0

    def execute(self, call: ToolCall) -> str:
        read_only = False
        try:
            args = json.loads(call.arguments or "{}")
            if not isinstance(args, dict):
                raise ValueError("工具参数必须是 JSON 对象")
            handler = self.__handlers.get(call.name)
            if handler is None:
                raise ValueError(f"未知主席工具: {call.name!r}")
            read_only = call.name in {
                "get_meeting_state",
                "list_recent_events",
                "read_submission",
            }
            if not read_only and self.__action_count >= self.action_limit:
                raise PermissionError("本轮主席行动额度已用尽，请等待新事件")
            result = handler(args)
            payload: dict[str, object] = {"ok": True}
            if result is not None:
                payload["result"] = result
        except VenueEngineStoppedError:
            raise
        except Exception as exc:
            payload = {
                "ok": False,
                "error": str(exc),
                "error_type": type(exc).__name__,
            }
        if payload["ok"] is True:
            self.__successful_tools.append(call.name)
            if not read_only:
                self.__action_count += 1
        return json.dumps(payload, ensure_ascii=False)

    def _event(self, event_id: int) -> Event:
        events = self.venue._require_event_list().events
        if event_id < 0 or event_id >= len(events):
            raise ValueError(
                f"会场 {self.venue.id!r} 不存在或主席不可见事件 #{event_id}"
            )
        event = events[event_id]
        if not self.can_read_event(event):
            raise ValueError(
                f"会场 {self.venue.id!r} 不存在或主席不可见事件 #{event_id}"
            )
        return event

    def can_read_event(self, event: Event) -> bool:
        if event.type in {EventType.NOTE, EventType.CHAT}:
            return False
        if self.venue.chair is not None:
            return self.venue.chair in event.scope
        if isinstance(event, ResolutionEvent):
            return True
        if event.type == EventType.SYSTEM:
            return event.scope == set(self.venue.seats)
        return True

    def visible_pending(self) -> list[Event]:
        return [
            event
            for event in self.venue._require_event_list().pending_events
            if self.can_read_event(event)
        ]

    def visible_events(self) -> list[Event]:
        return [
            event
            for event in self.venue._require_event_list().events
            if self.can_read_event(event)
        ]

    def _seat_set(self, values: object, *, field: str) -> set[str]:
        if not isinstance(values, list) or not all(
            isinstance(item, str) for item in values
        ):
            raise ValueError(f"{field} 须为代表 ID 列表")
        normalized = {item.strip() for item in values}
        if "" in normalized:
            raise ValueError(f"{field} 不能包含空代表 ID")
        if len(normalized) != len(values):
            raise ValueError(f"{field} 不能包含重复代表 ID")
        unknown = normalized - set(self.venue.seats)
        if unknown:
            raise ValueError(f"{field} 包含不属于本会场的代表: {sorted(unknown)}")
        return normalized

    def _submit_chair_event(
        self,
        content: str,
        action: ChairAction,
        *,
        targets: set[str] | None = None,
        scope: set[str] | None = None,
    ) -> ChairEvent:
        event = ChairEvent(
            content,
            action,
            targets or set(),
            self.venue.id,
            self.venue.scenario,
            scope=scope,
        )
        event._set_submission_actor(self.venue.chair_actor_id())
        self.venue.submit_event(event)
        return event

    def _get_meeting_state(self, args: dict[str, Any]) -> object:
        current = self.venue.current_agenda
        pending = self.visible_pending()
        return {
            "venue_id": self.venue.id,
            "chair": self.venue.chair,
            "chair_mode": "representative" if self.venue.chair else "neutral",
            "session_phase": (
                self.venue.session_phase.value
                if self.venue.session_phase is not None
                else None
            ),
            "current_agenda": _agenda_ref(current) if current is not None else None,
            "pending_events": [_event_ref(item) for item in pending],
            "chair_power": {
                power.value: enabled
                for power, enabled in self.venue.chair_power.items()
            },
        }

    def _list_recent_events(self, args: dict[str, Any]) -> object:
        limit = int(args.get("limit", 20))
        if limit < 1 or limit > 50:
            raise ValueError("limit 须在 1 到 50 之间")
        return [_event_ref(item) for item in self.visible_events()[-limit:]]

    def _read_submission(self, args: dict[str, Any]) -> object:
        event = self._event(int(args["event_id"]))
        if not isinstance(event, ResolutionEvent):
            raise ValueError("read_submission 只能读取主席可见的正式决议")
        file = event.resolution
        content = file.get_content(SYSTEM_ACTOR)
        offset = int(args.get("offset", 0))
        limit = int(args.get("limit", 4000))
        if offset < 0:
            raise ValueError("offset 不能为负数")
        if limit < 1 or limit > 8000:
            raise ValueError("limit 须在 1 到 8000 之间")
        filesystem = file._filesystem
        path = (
            filesystem._relkey(file.path)
            if filesystem is not None
            else file.path.name
        )
        chunk = content[offset : offset + limit]
        return {
            "event_id": event.id,
            "path": path,
            "offset": offset,
            "total_chars": len(content),
            "content": chunk,
            "has_more": offset + len(chunk) < len(content),
        }

    def _publish_notice(self, args: dict[str, Any]) -> object:
        event = self._submit_chair_event(
            str(args["content"]),
            ChairAction.PROCEDURAL_NOTICE,
        )
        return _event_ref(event)

    def _call_speaker(self, args: dict[str, Any]) -> object:
        rep_id = str(args["rep_id"]).strip()
        if rep_id not in self.venue.seats:
            raise ValueError(f"代表 {rep_id!r} 不属于会场 {self.venue.id!r}")
        event = self._submit_chair_event(
            str(args["content"]),
            ChairAction.CALL_SPEAKER,
            targets={rep_id},
        )
        return _event_ref(event)

    def _request_vote(self, args: dict[str, Any]) -> object:
        target = self._event(int(args["event_id"]))
        if not isinstance(target, (ResolutionEvent, MotionSwitchEvent)):
            raise ValueError("只能对未决决议或阶段切换动议发起表决")
        if target.status != EventStatus.PENDING:
            raise ValueError(f"目标事件 #{target.id} 已是 {target.status.value}")
        event = self._submit_chair_event(
            str(args["content"]),
            ChairAction.REQUEST_VOTE,
            targets=set(target.scope),
            scope=set(target.scope),
        )
        return _event_ref(event)

    def _record_vote(self, args: dict[str, Any]) -> object:
        target = self._event(int(args["event_id"]))
        if not isinstance(target, (ResolutionEvent, MotionSwitchEvent)):
            raise ValueError("VoteEvent 目标只能是决议或阶段切换动议")
        if target.status != EventStatus.PENDING:
            raise ValueError(f"目标事件 #{target.id} 已是 {target.status.value}")

        supporters = self._seat_set(args["supporters"], field="supporters")
        against = self._seat_set(args["against"], field="against")
        abstentions = self._seat_set(args["abstentions"], field="abstentions")
        overlap = (
            (supporters & against)
            | (supporters & abstentions)
            | (against & abstentions)
        )
        if overlap:
            raise ValueError(f"同一代表不能出现在多个票箱: {sorted(overlap)}")
        ballots = supporters | against | abstentions
        outside_scope = ballots - set(target.scope)
        if outside_scope:
            raise PermissionError(
                f"下列代表不在目标事件 #{target.id} 的可见 scope 内，不能参与表决: "
                f"{sorted(outside_scope)}"
            )
        valid_votes = len(ballots)
        if valid_votes == 0:
            raise ValueError("表决至少须记录一票")
        mode = VotePassMode(str(args["pass_mode"]))
        voting = len(supporters) + len(against)
        passed = _vote_passed(len(supporters), voting, mode)
        vote = VoteEvent(
            f"主席记录对事件 #{target.id} 的表决结果",
            self.venue.id,
            set(target.scope),
            target,
            valid_votes,
            mode,
            self.venue.scenario,
            supporters=sorted(supporters),
            against=sorted(against),
            abstentions=sorted(abstentions),
            passed=passed,
            remark=str(args.get("remark", "")),
            named=True,
        )
        vote._set_submission_actor(self.venue.chair_actor_id())
        self.venue.submit_event(vote)
        self.venue._update_event_status(
            target,
            EventStatus.ACCEPTED if passed else EventStatus.REJECTED,
            actor_id=self.venue.chair_actor_id(),
        )
        return {"vote": _event_ref(vote), "target": _event_ref(target)}

    def _decide_resolution(self, args: dict[str, Any]) -> object:
        event = self._event(int(args["event_id"]))
        if not isinstance(event, ResolutionEvent):
            raise ValueError("decide_resolution 只能裁定 ResolutionEvent")
        self.venue._require_chair_power(
            SYSTEM_CHAIR_ACTOR,
            CHAIR_POWER.DECIDE_RESOLUTION,
            action="直接裁定决议",
        )
        return self._decide(event, args)

    def _decide(
        self,
        event: ResolutionEvent,
        args: dict[str, Any],
    ) -> object:
        if event.status != EventStatus.PENDING:
            raise ValueError(f"目标事件 #{event.id} 已是 {event.status.value}")
        decision = EventStatus(str(args["decision"]))
        reason = str(args["reason"]).strip()
        if not reason:
            raise ValueError("裁定理由不能为空")
        self.venue._update_event_status(
            event,
            decision,
            actor_id=self.venue.chair_actor_id(),
        )
        audit = self._submit_chair_event(
            f"主席裁定事件 #{event.id} 为 {decision.value}：{reason}",
            ChairAction.DECIDE_RESOLUTION,
            targets=set(event.scope),
            scope=set(event.scope),
        )
        return {"audit_event": _event_ref(audit), "target": _event_ref(event)}

    def _switch_phase(self, args: dict[str, Any]) -> object:
        target_phase = SessionPhase(str(args["target_phase"]))
        content = str(args["content"])
        if self.venue.chair_power[CHAIR_POWER.DECIDE_SWITCH_PHASE]:
            event = self.venue.decide_switch_phase(
                SYSTEM_CHAIR_ACTOR,
                content,
                target_phase,
            )
            return _event_ref(event)

        if "motion_event_id" not in args:
            raise PermissionError(
                "主席没有直接切换阶段的权力，须提供已通过的 motion_event_id"
            )
        motion = self._event(int(args["motion_event_id"]))
        if not isinstance(motion, MotionSwitchEvent):
            raise ValueError("motion_event_id 必须指向 MotionSwitchEvent")
        if motion.status != EventStatus.ACCEPTED:
            raise PermissionError(
                f"阶段动议 #{motion.id} 尚未通过，状态为 {motion.status.value}"
            )
        if motion.target_phase != target_phase:
            raise ValueError(
                f"阶段动议目标为 {motion.target_phase.value}，"
                f"不能据此切换为 {target_phase.value}"
            )
        event = PhaseSwitchEvent(
            content,
            target_phase,
            self.venue.id,
            set(self.venue.seats),
            self.venue.scenario,
        )
        event._set_submission_actor(self.venue.chair_actor_id())
        self.venue.submit_event(event)
        return _event_ref(event)

    def _set_current_agenda(self, args: dict[str, Any]) -> object:
        agenda = self.venue.get_agenda(str(args["agenda_id"]))
        self.venue.set_current_agenda(
            SYSTEM_CHAIR_ACTOR,
            agenda,
            finished=bool(args.get("finished", False)),
        )
        current = self.venue.current_agenda
        return _agenda_ref(current) if current is not None else None

    def _add_agenda(self, args: dict[str, Any]) -> object:
        questions = args["questions"]
        if not isinstance(questions, list) or not all(
            isinstance(item, str) for item in questions
        ):
            raise ValueError("questions 须为字符串列表")
        agenda = Agenda(str(args["agenda_id"]), str(args["title"]), questions)
        self.venue.add_agenda(SYSTEM_CHAIR_ACTOR, agenda)
        return _agenda_ref(agenda)


def _vote_passed(supporters: int, voting: int, mode: VotePassMode) -> bool:
    """弃权不计入 present and voting；零张赞成/反对票时不通过。"""
    if voting == 0:
        return False
    if mode == VotePassMode.SIMPLE_MAJORITY:
        return supporters * 2 > voting
    if mode == VotePassMode.TWO_THIRDS:
        return supporters * 3 >= voting * 2
    return supporters == voting


def _event_ref(event: Event) -> dict[str, object]:
    return {
        "id": event.id,
        "type": event.type.value,
        "status": event.status.value,
        "content": event.content,
        "scope": sorted(event.scope),
    }


def _agenda_ref(agenda: Agenda) -> dict[str, object]:
    return {
        "id": agenda.id,
        "title": agenda.title,
        "questions": list(agenda.questions),
    }
