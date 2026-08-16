"""DMAgent 的指令概率裁定、时间推进与危机更新工具。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
import hashlib
import json
from typing import Any

from event.event import Event, EventStatus, InstructionEvent, ResolutionEvent, SystemEvent
from llm import ToolCall, ToolSpec
from filesystem.filesystem import SYSTEM_ACTOR
from scenario.venue import Venue, VenueEngineStoppedError

DM_ACTOR = "__dm__"


class InstructionOutcomeTier(StrEnum):
    """DM 对一份待执行指令作出的六档可行性判断。"""

    VERY_LIKELY_SUCCESS = "very_likely_success"
    SUCCESS = "success"
    POSSIBLE_SUCCESS = "possible_success"
    POSSIBLE_FAILURE = "possible_failure"
    FAILURE = "failure"
    VERY_LIKELY_FAILURE = "very_likely_failure"


INSTRUCTION_TIER_PROBABILITIES: dict[InstructionOutcomeTier, float] = {
    InstructionOutcomeTier.VERY_LIKELY_SUCCESS: 0.95,
    InstructionOutcomeTier.SUCCESS: 0.80,
    InstructionOutcomeTier.POSSIBLE_SUCCESS: 0.60,
    InstructionOutcomeTier.POSSIBLE_FAILURE: 0.40,
    InstructionOutcomeTier.FAILURE: 0.20,
    InstructionOutcomeTier.VERY_LIKELY_FAILURE: 0.05,
}

_INSTRUCTION_TIER_LABELS: dict[InstructionOutcomeTier, str] = {
    InstructionOutcomeTier.VERY_LIKELY_SUCCESS: "极有可能成功",
    InstructionOutcomeTier.SUCCESS: "成功",
    InstructionOutcomeTier.POSSIBLE_SUCCESS: "可能成功",
    InstructionOutcomeTier.POSSIBLE_FAILURE: "可能失败",
    InstructionOutcomeTier.FAILURE: "失败",
    InstructionOutcomeTier.VERY_LIKELY_FAILURE: "极大概率失败",
}


@dataclass(frozen=True)
class InstructionAdjudication:
    tier: InstructionOutcomeTier
    probability: float
    roll: float
    succeeded: bool
    rationale: str
    audit_event_id: int

    def to_dict(self) -> dict[str, object]:
        return {
            "tier": self.tier.value,
            "tier_label": _INSTRUCTION_TIER_LABELS[self.tier],
            "probability": self.probability,
            "roll": self.roll,
            "succeeded": self.succeeded,
            "rationale": self.rationale,
            "audit_event_id": self.audit_event_id,
        }


@dataclass(frozen=True)
class DMTaskResult:
    published_event_ids: tuple[int, ...]
    advanced_minutes: int
    instruction_adjudication: InstructionAdjudication | None


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


DM_TOOL_SPECS = [
    _tool("get_current_tasks", "查看本轮指令/决议任务及处理轨迹", {}),
    _tool(
        "read_submission",
        "分段读取当前或近期正式指令/决议的 submission 正文",
        {
            "source_event_id": {"type": "integer", "minimum": 0},
            "offset": {"type": "integer", "minimum": 0},
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 8000,
            },
        },
        ["source_event_id"],
    ),
    _tool(
        "adjudicate_instruction",
        "为待执行指令选择六档可行性并进行一次可审计概率判定",
        {
            "source_event_id": {"type": "integer", "minimum": 0},
            "tier": {
                "type": "string",
                "enum": [tier.value for tier in InstructionOutcomeTier],
                "description": (
                    "极有可能成功=95%，成功=80%，可能成功=60%，"
                    "可能失败=40%，失败=20%，极大概率失败=5%"
                ),
            },
            "rationale": {
                "type": "string",
                "description": "根据权限、资源、时距、阻力和情报作出的分档理由",
            },
        },
        ["source_event_id", "tier", "rationale"],
    ),
    _tool(
        "publish_crisis_update",
        "发布由指定指令/决议引起的危机更新；scope 决定程序级可见范围",
        {
            "source_event_id": {"type": "integer", "minimum": 0},
            "content": {"type": "string", "description": "客观、可观察的事件更新"},
            "action": {
                "type": "array",
                "items": {"type": "string"},
                "description": "已发生的状态变化或可跟进事项",
            },
            "scope": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": "能看到本更新的会场代表 ID",
            },
        },
        ["source_event_id", "content", "action", "scope"],
    ),
    _tool(
        "advance_time",
        "因指定提交的执行过程推进剧情时钟，并触发到期外部事件",
        {
            "source_event_id": {"type": "integer", "minimum": 0},
            "minutes": {
                "type": "integer",
                "minimum": 1,
                "maximum": 1440,
            },
            "reason": {"type": "string", "description": "推进时间的执行依据"},
        },
        ["source_event_id", "minutes", "reason"],
    ),
]


class DMToolExecutor:
    """工具只能作用于 DMAgent 当前批次中的指令/决议任务。"""

    def __init__(
        self,
        venue: Venue,
        *,
        random_seed: str | int = "0",
    ) -> None:
        self.venue = venue
        self.__random_seed = str(random_seed)
        self.__tasks: dict[int, Event] = {}
        self.__published: dict[int, list[int]] = defaultdict(list)
        self.__advanced_minutes: dict[int, int] = defaultdict(int)
        self.__adjudications: dict[int, InstructionAdjudication] = {}
        self.__successful_tools: list[str] = []
        self.max_updates_per_task = 4

    @property
    def tool_specs(self) -> list[ToolSpec]:
        return list(DM_TOOL_SPECS)

    @property
    def successful_tools(self) -> list[str]:
        return list(self.__successful_tools)

    def begin_tasks(self, events: list[Event]) -> None:
        tasks: dict[int, Event] = {}
        for event in events:
            if event.id is None:
                raise ValueError("DM 任务事件必须已经入表")
            if not isinstance(event, (InstructionEvent, ResolutionEvent)):
                raise TypeError("DM 只处理 InstructionEvent 或 ResolutionEvent")
            if (
                isinstance(event, InstructionEvent)
                and event.status != EventStatus.PENDING
            ):
                raise ValueError(
                    f"DM 收到的指令 #{event.id} 状态须为 pending，"
                    f"实际为 {event.status.value}"
                )
            if (
                isinstance(event, ResolutionEvent)
                and event.status not in {EventStatus.ACCEPTED, EventStatus.REJECTED}
            ):
                raise ValueError(
                    f"DM 收到的决议 #{event.id} 状态须为 accepted/rejected，"
                    f"实际为 {event.status.value}"
                )
            tasks[event.id] = event
        self.__tasks = tasks
        self.__published = defaultdict(list)
        self.__advanced_minutes = defaultdict(int)
        self.__adjudications = {}
        self.__successful_tools = []

    def execute(self, call: ToolCall) -> str:
        try:
            args = json.loads(call.arguments or "{}")
            if not isinstance(args, dict):
                raise ValueError("工具参数必须是 JSON 对象")
            if call.name == "get_current_tasks":
                result = self._get_current_tasks()
            elif call.name == "read_submission":
                result = self._read_submission(args)
            elif call.name == "adjudicate_instruction":
                result = self._adjudicate_instruction(args)
            elif call.name == "publish_crisis_update":
                result = self._publish_crisis_update(args)
            elif call.name == "advance_time":
                result = self._advance_time(args)
            else:
                raise ValueError(f"未知 DM 工具: {call.name!r}")
            payload: dict[str, object] = {"ok": True, "result": result}
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
        return json.dumps(payload, ensure_ascii=False)

    def task_results(self) -> dict[int, DMTaskResult]:
        return {
            event_id: DMTaskResult(
                published_event_ids=tuple(self.__published[event_id]),
                advanced_minutes=self.__advanced_minutes[event_id],
                instruction_adjudication=self.__adjudications.get(event_id),
            )
            for event_id in self.__tasks
        }

    def _require_task(self, event_id: int) -> Event:
        try:
            return self.__tasks[event_id]
        except KeyError as exc:
            raise PermissionError(
                f"事件 #{event_id} 不在 DMAgent 当前任务批次中"
            ) from exc

    def _submission_event(
        self,
        event_id: int,
    ) -> InstructionEvent | ResolutionEvent:
        events = self.venue._require_event_list().events
        if event_id < 0 or event_id >= len(events):
            raise ValueError(f"会场 {self.venue.id!r} 不存在事件 #{event_id}")
        event = events[event_id]
        if not isinstance(event, (InstructionEvent, ResolutionEvent)):
            raise ValueError(f"事件 #{event_id} 不是正式指令或决议")
        return event

    def _get_current_tasks(self) -> object:
        return [
            {
                "event_id": event_id,
                "type": event.type.value,
                "status": event.status.value,
                "published_event_ids": list(self.__published[event_id]),
                "advanced_minutes": self.__advanced_minutes[event_id],
                "instruction_adjudication": (
                    self.__adjudications[event_id].to_dict()
                    if event_id in self.__adjudications
                    else None
                ),
            }
            for event_id, event in self.__tasks.items()
        ]

    def _read_submission(self, args: dict[str, Any]) -> object:
        source_id = int(args["source_event_id"])
        event = self._submission_event(source_id)
        file = (
            event.instruction
            if isinstance(event, InstructionEvent)
            else event.resolution
        )
        content = file.get_content(SYSTEM_ACTOR)
        offset = int(args.get("offset", 0))
        limit = int(args.get("limit", 4000))
        if offset < 0:
            raise ValueError("offset 不能为负数")
        if limit < 1 or limit > 8000:
            raise ValueError("limit 须在 1 到 8000 之间")
        chunk = content[offset : offset + limit]
        return {
            "source_event_id": source_id,
            "offset": offset,
            "total_chars": len(content),
            "content": chunk,
            "has_more": offset + len(chunk) < len(content),
        }

    def _adjudicate_instruction(self, args: dict[str, Any]) -> object:
        source_id = int(args["source_event_id"])
        source = self._require_task(source_id)
        if not isinstance(source, InstructionEvent):
            raise ValueError("adjudicate_instruction 只能裁定 InstructionEvent")
        if source.status != EventStatus.PENDING:
            raise PermissionError(
                f"指令 #{source_id} 已完成概率判定，状态为 {source.status.value}"
            )
        if source_id in self.__adjudications:
            raise PermissionError(f"指令 #{source_id} 不能重复抽取随机数")
        tier = InstructionOutcomeTier(str(args["tier"]))
        rationale = str(args["rationale"]).strip()
        if not rationale:
            raise ValueError("指令分档 rationale 不能为空")
        probability = INSTRUCTION_TIER_PROBABILITIES[tier]
        roll = deterministic_instruction_roll(
            self.__random_seed,
            self.venue.id,
            source_id,
            source.instruction.get_content(SYSTEM_ACTOR),
        )
        succeeded = roll < probability
        status = EventStatus.COMPLETED if succeeded else EventStatus.FAILED
        self.venue._update_event_status(
            source,
            status,
            actor_id=DM_ACTOR,
        )
        audit = SystemEvent(
            (
                f"DM 完成指令 #{source_id} 的概率判定："
                f"{_INSTRUCTION_TIER_LABELS[tier]}，"
                f"最终{'成功' if succeeded else '失败'}。依据：{rationale}"
            ),
            [
                "instruction_adjudication",
                f"source_event:{source_id}",
                f"tier:{tier.value}",
                f"probability:{probability:.4f}",
                f"roll:{roll:.12f}",
                f"result:{'success' if succeeded else 'failure'}",
            ],
            self.venue.id,
            set(source.scope),
            self.venue.scenario,
        )
        audit._set_submission_actor(DM_ACTOR)
        self.venue.submit_event(audit)
        if audit.id is None:
            raise RuntimeError("指令概率判定审计事件入表后没有事件 ID")
        adjudication = InstructionAdjudication(
            tier=tier,
            probability=probability,
            roll=roll,
            succeeded=succeeded,
            rationale=rationale,
            audit_event_id=audit.id,
        )
        self.__adjudications[source_id] = adjudication
        return adjudication.to_dict()

    def _publish_crisis_update(self, args: dict[str, Any]) -> object:
        source_id = int(args["source_event_id"])
        source = self._require_task(source_id)
        self._require_source_ready(source)
        if len(self.__published[source_id]) >= self.max_updates_per_task:
            raise PermissionError(
                f"事件 #{source_id} 本轮最多发布 {self.max_updates_per_task} 条危机更新"
            )
        content = str(args["content"]).strip()
        if not content:
            raise ValueError("危机更新 content 不能为空")
        action = args["action"]
        if not isinstance(action, list) or not all(
            isinstance(item, str) and item.strip() for item in action
        ):
            raise ValueError("action 须为非空字符串列表")
        scope_raw = args["scope"]
        if not isinstance(scope_raw, list) or not all(
            isinstance(item, str) for item in scope_raw
        ):
            raise ValueError("scope 须为代表 ID 列表")
        scope = {item.strip() for item in scope_raw}
        if not scope or "" in scope:
            raise ValueError("scope 不能为空或包含空代表 ID")
        if len(scope) != len(scope_raw):
            raise ValueError("scope 不能包含重复代表 ID")
        unknown = scope - set(self.venue.seats)
        if unknown:
            raise ValueError(f"scope 包含不属于本会场的代表: {sorted(unknown)}")

        metadata = [
            f"source_event:{source_id}",
            f"source_status:{source.status.value}",
            *(item.strip() for item in action),
        ]
        adjudication = self.__adjudications.get(source_id)
        if adjudication is not None:
            metadata.extend(
                [
                    f"tier:{adjudication.tier.value}",
                    f"roll:{adjudication.roll:.12f}",
                    f"result:{'success' if adjudication.succeeded else 'failure'}",
                ]
            )
        event = SystemEvent(
            content,
            metadata,
            self.venue.id,
            scope,
            self.venue.scenario,
        )
        event._set_submission_actor(DM_ACTOR)
        self.venue.submit_event(event)
        if event.id is None:
            raise RuntimeError("危机更新入表后没有事件 ID")
        self.__published[source_id].append(event.id)
        return {
            "event_id": event.id,
            "source_event_id": source_id,
            "scope": sorted(scope),
        }

    def _advance_time(self, args: dict[str, Any]) -> object:
        source_id = int(args["source_event_id"])
        source = self._require_task(source_id)
        self._require_source_ready(source)
        if isinstance(source, ResolutionEvent) and source.status != EventStatus.ACCEPTED:
            raise PermissionError("被拒绝的决议不能推进剧情时间")
        if self.__advanced_minutes[source_id] > 0:
            raise PermissionError(f"事件 #{source_id} 本轮已经推进过剧情时间")
        minutes = int(args["minutes"])
        if minutes < 1 or minutes > 1440:
            raise ValueError("minutes 须在 1 到 1440 之间")
        reason = str(args["reason"]).strip()
        if not reason:
            raise ValueError("推进时间的 reason 不能为空")
        before = self.venue.scenario.time
        self.venue.scenario.time_pass(timedelta(minutes=minutes))
        self.__advanced_minutes[source_id] = minutes
        return {
            "source_event_id": source_id,
            "before": before.isoformat(),
            "after": self.venue.scenario.time.isoformat(),
            "minutes": minutes,
            "reason": reason,
        }

    def _require_source_ready(self, source: Event) -> None:
        if (
            isinstance(source, InstructionEvent)
            and source.id not in self.__adjudications
        ):
            raise PermissionError(
                f"指令 #{source.id} 必须先调用 adjudicate_instruction 完成六档判定"
            )


def deterministic_instruction_roll(
    random_seed: str | int,
    venue_id: str,
    event_id: int,
    instruction_content: str = "",
) -> float:
    """由显式运行种子和事件身份生成 [0, 1) 的稳定伪随机数。"""
    content_hash = hashlib.sha256(instruction_content.encode()).hexdigest()
    material = (
        f"{random_seed}|{venue_id}|instruction|{event_id}|{content_hash}"
    ).encode()
    digest = hashlib.sha256(material).digest()
    return int.from_bytes(digest[:8], "big") / 2**64
