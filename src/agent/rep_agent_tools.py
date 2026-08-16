"""RepresentativeAgent 可调用的工具:ToolSpec 定义 + 对 Representative 的分发执行."""

from __future__ import annotations

import json
from typing import Any, Callable

from agent.memory import AgentMemory, MemoryCategory, MemoryStatus
from agenda.agenda import Agenda
from llm.types import ToolCall, ToolSpec
from scenario.representative import Representative
from scenario.venue import SessionPhase, VenueEngineStoppedError

_PHASE_VALUES = [p.value for p in SessionPhase]
_MEMORY_CATEGORY_VALUES = [category.value for category in MemoryCategory]
_MEMORY_STATUS_VALUES = [status.value for status in MemoryStatus]
_EVENT_ACTION_TOOL_NAMES = {
    "send_message",
    "pass_note",
    "submit_motion_switch",
    "submit_phase_switch",
    "submit_instruction",
    "submit_resolution",
    "set_current_agenda",
    "add_agenda",
}
_CHAIR_ONLY_TOOL_NAMES = {
    "submit_phase_switch",
    "set_current_agenda",
    "add_agenda",
}

Handler = Callable[[Representative, dict[str, Any]], Any]


def _file_ref(file, *, actor: str | None = None) -> dict[str, Any]:
    """文件摘要.owners/scope/primary_owner 仅在 ``actor`` 为 owner 时附带."""
    fs = file._filesystem
    rel = fs._relkey(file.path) if fs is not None else str(file.path)
    ref: dict[str, Any] = {
        "path": rel,
        "name": file.path.name,
        "description": file.description,
        "is_submission": file.is_submission,
    }
    if actor is not None and actor in file.owners:
        ref["owners"] = sorted(file.owners)
        ref["scope"] = sorted(file.scope)
        ref["primary_owner"] = file.primary_owner
    return ref


def _agenda_ref(agenda: Agenda) -> dict[str, Any]:
    return {
        "id": agenda.id,
        "title": agenda.title,
        "questions": list(agenda.questions),
    }


def _event_ref(event) -> dict[str, Any]:
    return {
        "id": event.id,
        "type": event.type.value if event.type is not None else None,
        "content": event.content,
        "status": event.status.value,
        "venue": event.venue,
        "scope": sorted(event.scope),
    }


def _as_str_list(value: Any, *, field: str) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    raise ValueError(f"{field} 须为字符串或字符串列表")


def _as_int_list(value: Any, *, field: str) -> list[int]:
    if not isinstance(value, list) or not all(
        isinstance(item, int) and not isinstance(item, bool) for item in value
    ):
        raise ValueError(f"{field} 须为整数列表")
    return list(value)


def _resolve_file(rep: Representative, path: str):
    """按相对路径或本代表目录下文件名解析 File.

    ``reps/`` 文件须对本代表可见;``submissions/`` 副本允许按路径引用
    (例如复用已有提交副本,不经由 list_visible 发现).
    """
    raw = path.strip()
    if not raw:
        raise ValueError("path 不能为空")
    fs = rep._require_filesystem()
    candidates = [raw]
    if "/" not in raw:
        candidates.append(f"reps/{rep.id}/{raw}")
    wanted: set[str] = set()
    for key in candidates:
        try:
            wanted.add(fs._relkey(fs._resolve(key)))
        except ValueError:
            wanted.add(key.replace("\\", "/"))
    for file in fs.list_all():
        rel = fs._relkey(file.path)
        if rel not in wanted and file.path.name != raw:
            continue
        if file.is_submission or file.visible_to(rep.id):
            return file
    raise ValueError(f"找不到可访问的文件: {path!r}")


def _ok(result: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": True}
    if result is not None:
        payload["result"] = result
    return payload


def _err(exc: BaseException) -> dict[str, Any]:
    return {"ok": False, "error": str(exc), "error_type": type(exc).__name__}


# ---- handlers ----


def _list_visible_files(rep: Representative, args: dict[str, Any]) -> dict[str, Any]:
    return _ok([_file_ref(f, actor=rep.id) for f in rep.list_visible()])


def _list_writable_files(rep: Representative, args: dict[str, Any]) -> dict[str, Any]:
    return _ok([_file_ref(f, actor=rep.id) for f in rep.list_writable()])


def _read_file(rep: Representative, args: dict[str, Any]) -> dict[str, Any]:
    path = str(args["path"])
    file = _resolve_file(rep, path)
    return _ok(
        {"path": _file_ref(file, actor=rep.id)["path"], "content": rep.read_file(file)}
    )


def _write_file(rep: Representative, args: dict[str, Any]) -> dict[str, Any]:
    path = str(args["path"])
    content = str(args["content"])
    file = _resolve_file(rep, path)
    rep.write_file(file, content)
    return _ok({"path": _file_ref(file, actor=rep.id)["path"], "written": True})


def _create_file(rep: Representative, args: dict[str, Any]) -> dict[str, Any]:
    file = rep.create_file(
        str(args["name"]),
        str(args["content"]),
        str(args["description"]),
    )
    return _ok(_file_ref(file, actor=rep.id))


def _get_file_access(rep: Representative, args: dict[str, Any]) -> dict[str, Any]:
    file = _resolve_file(rep, str(args["path"]))
    access = rep.get_file_access(file)
    return _ok(
        {
            "path": _file_ref(file, actor=rep.id)["path"],
            "owners": sorted(access["owners"]),
            "scope": sorted(access["scope"]),
            "primary_owner": access["primary_owner"],
        }
    )


def _add_scope(rep: Representative, args: dict[str, Any]) -> dict[str, Any]:
    file = _resolve_file(rep, str(args["path"]))
    others = _as_str_list(args["others"], field="others")
    rep.add_scope(file, set(others))
    return _ok(_file_ref(file, actor=rep.id))


def _add_owner(rep: Representative, args: dict[str, Any]) -> dict[str, Any]:
    file = _resolve_file(rep, str(args["path"]))
    others = _as_str_list(args["others"], field="others")
    rep.add_owner(file, set(others))
    return _ok(_file_ref(file, actor=rep.id))


def _can_submit(rep: Representative, args: dict[str, Any]) -> dict[str, Any]:
    file = _resolve_file(rep, str(args["path"]))
    return _ok(
        {
            "path": _file_ref(file, actor=rep.id)["path"],
            "can_submit": rep.can_submit(file),
        }
    )


def _set_description(rep: Representative, args: dict[str, Any]) -> dict[str, Any]:
    file = _resolve_file(rep, str(args["path"]))
    rep.set_description(file, str(args["description"]))
    return _ok(_file_ref(file, actor=rep.id))


def _send_message(rep: Representative, args: dict[str, Any]) -> dict[str, Any]:
    event = rep.send_message(str(args["content"]))
    return _ok(_event_ref(event))


def _pass_note(rep: Representative, args: dict[str, Any]) -> dict[str, Any]:
    to = _as_str_list(args["to"], field="to")
    event = rep.pass_note(str(args["content"]), set(to))
    return _ok(_event_ref(event))


def _submit_motion_switch(rep: Representative, args: dict[str, Any]) -> dict[str, Any]:
    event = rep.submit_motion_switch(
        str(args["content"]),
        str(args["target_phase"]),
    )
    return _ok(_event_ref(event))


def _submit_phase_switch(rep: Representative, args: dict[str, Any]) -> dict[str, Any]:
    event = rep.submit_phase_switch(
        str(args["content"]),
        str(args["target_phase"]),
    )
    return _ok(_event_ref(event))


def _submit_instruction(rep: Representative, args: dict[str, Any]) -> dict[str, Any]:
    fr = set(_as_str_list(args["fr"], field="fr"))
    file = _resolve_file(rep, str(args["path"]))
    event = rep.submit_instruction(str(args["content"]), fr, file)
    payload = _event_ref(event)
    payload["file"] = _file_ref(event.instruction, actor=rep.id)
    return _ok(payload)


def _submit_resolution(rep: Representative, args: dict[str, Any]) -> dict[str, Any]:
    fr = set(_as_str_list(args["fr"], field="fr"))
    file = _resolve_file(rep, str(args["path"]))
    event = rep.submit_resolution(str(args["content"]), fr, file)
    payload = _event_ref(event)
    payload["file"] = _file_ref(event.resolution, actor=rep.id)
    return _ok(payload)


def _list_agendas(rep: Representative, args: dict[str, Any]) -> dict[str, Any]:
    current = rep.current_agenda
    return _ok(
        {
            "current": _agenda_ref(current) if current is not None else None,
            "todo": [_agenda_ref(a) for a in rep.todo_agenda],
            "finished": [_agenda_ref(a) for a in rep.finished_agenda],
        }
    )


def _get_agenda(rep: Representative, args: dict[str, Any]) -> dict[str, Any]:
    return _ok(_agenda_ref(rep.get_agenda(str(args["agenda_id"]))))


def _set_current_agenda(rep: Representative, args: dict[str, Any]) -> dict[str, Any]:
    agenda = rep.get_agenda(str(args["agenda_id"]))
    finished = bool(args.get("finished", False))
    rep.set_current_agenda(agenda, finished=finished)
    current = rep.current_agenda
    return _ok(
        {
            "current": _agenda_ref(current) if current is not None else None,
            "finished_flag": finished,
        }
    )


def _add_agenda(rep: Representative, args: dict[str, Any]) -> dict[str, Any]:
    questions = args.get("questions", [])
    if not isinstance(questions, list) or not all(isinstance(q, str) for q in questions):
        raise ValueError("questions 须为字符串列表")
    agenda = Agenda(str(args["agenda_id"]), str(args["title"]), list(questions))
    rep.add_agenda(agenda)
    return _ok(_agenda_ref(agenda))


def _get_session_info(rep: Representative, args: dict[str, Any]) -> dict[str, Any]:
    venue = rep._require_venue()
    return _ok(
        {
            "rep_id": rep.id,
            "is_chair": rep.is_chair,
            "venue_id": venue.id,
            "session_phase": (
                venue.session_phase.value if venue.session_phase is not None else None
            ),
            "chair": venue.chair,
            "seats": list(venue.seats),
            "chair_power": {
                power.value: bool(enabled)
                for power, enabled in venue.chair_power.items()
            },
        }
    )


def _list_visible_events(rep: Representative, args: dict[str, Any]) -> dict[str, Any]:
    events = rep._require_event_list().get_events(rep.id)
    return _ok([_event_ref(e) for e in events])


_HANDLERS: dict[str, Handler] = {
    "list_visible_files": _list_visible_files,
    "list_writable_files": _list_writable_files,
    "read_file": _read_file,
    "write_file": _write_file,
    "create_file": _create_file,
    "get_file_access": _get_file_access,
    "add_scope": _add_scope,
    "add_owner": _add_owner,
    "can_submit": _can_submit,
    "set_description": _set_description,
    "send_message": _send_message,
    "pass_note": _pass_note,
    "submit_motion_switch": _submit_motion_switch,
    "submit_phase_switch": _submit_phase_switch,
    "submit_instruction": _submit_instruction,
    "submit_resolution": _submit_resolution,
    "list_agendas": _list_agendas,
    "get_agenda": _get_agenda,
    "set_current_agenda": _set_current_agenda,
    "add_agenda": _add_agenda,
    "get_session_info": _get_session_info,
    "list_visible_events": _list_visible_events,
}


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


_PATH_PROP = {
    "type": "string",
    "description": (
        "文件路径:可用 FileSystem 相对路径"
        "(如 reps/<rep_id>/draft.md 或 submissions/<venue_id>/...),"
        "或本代表目录下的文件名"
    ),
}

_PHASE_PROP = {
    "type": "string",
    "enum": _PHASE_VALUES,
    "description": "目标会议阶段",
}

_OTHERS_PROP = {
    "oneOf": [
        {"type": "string"},
        {"type": "array", "items": {"type": "string"}, "minItems": 1},
    ],
    "description": "一个或多个代表 ID",
}

REP_TOOL_SPECS: list[ToolSpec] = [
    _tool(
        "get_session_info",
        "查看本代表身份、会场阶段、主席与席位等信息",
        {},
    ),
    _tool(
        "list_visible_events",
        "列出对本代表可见的已入表事件",
        {},
    ),
    _tool(
        "list_agendas",
        "列出当前/待审议/已结束议题",
        {},
    ),
    _tool(
        "get_agenda",
        "按 ID 获取本会场议题详情",
        {
            "agenda_id": {"type": "string", "description": "议题 ID"},
        },
        ["agenda_id"],
    ),
    _tool(
        "set_current_agenda",
        "切换当前议题(须为主席)",
        {
            "agenda_id": {"type": "string", "description": "要设为当前的议题 ID"},
            "finished": {
                "type": "boolean",
                "description": "是否将原当前议题记入 finished,默认 false",
            },
        },
        ["agenda_id"],
    ),
    _tool(
        "add_agenda",
        "向 todo 追加新议题(须为主席)",
        {
            "agenda_id": {"type": "string", "description": "新议题 ID"},
            "title": {"type": "string", "description": "议题标题"},
            "questions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "议题问题列表",
            },
        },
        ["agenda_id", "title", "questions"],
    ),
    _tool("list_visible_files", "列出本代表可见的 reps/ 文件", {}),
    _tool("list_writable_files", "列出本代表可写的 reps/ 文件", {}),
    _tool(
        "read_file",
        "读取可见文件内容",
        {"path": _PATH_PROP},
        ["path"],
    ),
    _tool(
        "write_file",
        "覆盖写入已有文件(须为 owner)",
        {
            "path": _PATH_PROP,
            "content": {"type": "string", "description": "新文件全文"},
        },
        ["path", "content"],
    ),
    _tool(
        "create_file",
        "在本代表目录下创建新文件",
        {
            "name": {
                "type": "string",
                "description": "文件名,如 draft.md(不要含目录)",
            },
            "content": {"type": "string", "description": "初始内容"},
            "description": {
                "type": "string",
                "description": "不超过 20 字的简述",
            },
        },
        ["name", "content", "description"],
    ),
    _tool(
        "get_file_access",
        "查看文件的 owners/scope(须为 owner;非 owner 会被拒绝)",
        {"path": _PATH_PROP},
        ["path"],
    ),
    _tool(
        "add_scope",
        "扩大文件可见范围(须为 owner)",
        {"path": _PATH_PROP, "others": _OTHERS_PROP},
        ["path", "others"],
    ),
    _tool(
        "add_owner",
        "将已在 scope 中的代表提升为 owner(须为 owner)",
        {"path": _PATH_PROP, "others": _OTHERS_PROP},
        ["path", "others"],
    ),
    _tool(
        "can_submit",
        "判断当前是否可将该工作文件提交到 submissions/(内容相对最新版须有变化)",
        {"path": _PATH_PROP},
        ["path"],
    ),
    _tool(
        "set_description",
        "修改文件简述(须为 owner)",
        {
            "path": _PATH_PROP,
            "description": {"type": "string", "description": "不超过 20 字"},
        },
        ["path", "description"],
    ),
    _tool(
        "send_message",
        "会场公开发言(全会场可见)",
        {"content": {"type": "string", "description": "发言正文"}},
        ["content"],
    ),
    _tool(
        "pass_note",
        "传纸条(仅自己与收件人可见)",
        {
            "content": {"type": "string", "description": "纸条正文"},
            "to": _OTHERS_PROP,
        },
        ["content", "to"],
    ),
    _tool(
        "submit_motion_switch",
        "提出阶段切换动议(不立即改阶段,PENDING)",
        {
            "content": {"type": "string", "description": "动议说明"},
            "target_phase": _PHASE_PROP,
        },
        ["content", "target_phase"],
    ),
    _tool(
        "submit_phase_switch",
        "主席直接切换会议阶段(须具备 decide_switch_phase)",
        {
            "content": {"type": "string", "description": "裁定说明"},
            "target_phase": _PHASE_PROP,
        },
        ["content", "target_phase"],
    ),
    _tool(
        "submit_instruction",
        "将 reps/ 工作文件提交到 submissions/ 并创建指示事件;fr 为可见代表集合",
        {
            "content": {"type": "string", "description": "指示说明"},
            "fr": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": "可见/关联代表 ID 列表(含自己)",
            },
            "path": {
                **_PATH_PROP,
                "description": "reps/ 下工作文件路径(须为 owner;会自动生成提交副本)",
            },
        },
        ["content", "fr", "path"],
    ),
    _tool(
        "submit_resolution",
        "将 reps/ 工作文件提交到 submissions/ 并创建决议事件;fr 为可见代表集合",
        {
            "content": {"type": "string", "description": "决议说明"},
            "fr": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": "可见/关联代表 ID 列表",
            },
            "path": {
                **_PATH_PROP,
                "description": "reps/ 下工作文件路径(须为 owner;会自动生成提交副本)",
            },
        },
        ["content", "fr", "path"],
    ),
]


MEMORY_TOOL_SPECS: list[ToolSpec] = [
    _tool(
        "remember",
        "保存一条私有长期记忆；只记录策略、承诺、判断、问题、关系或重要事实",
        {
            "category": {
                "type": "string",
                "enum": _MEMORY_CATEGORY_VALUES,
                "description": "记忆类别",
            },
            "content": {
                "type": "string",
                "maxLength": 500,
                "description": "独立、明确、可在后续决策中复用的内容",
            },
            "importance": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5,
                "description": "重要度，5 最高",
            },
            "source_event_ids": {
                "type": "array",
                "items": {"type": "integer", "minimum": 0},
                "description": "支持该记忆且对本代表可见的事件 ID",
            },
        },
        ["category", "content", "importance", "source_event_ids"],
    ),
    _tool(
        "revise_memory",
        "修订、解决或标记已被取代的私有长期记忆",
        {
            "memory_id": {"type": "string", "description": "例如 m1"},
            "content": {"type": "string", "maxLength": 500},
            "importance": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5,
            },
            "source_event_ids": {
                "type": "array",
                "items": {"type": "integer", "minimum": 0},
            },
            "status": {
                "type": "string",
                "enum": _MEMORY_STATUS_VALUES,
            },
        },
        ["memory_id"],
    ),
    _tool(
        "list_memories",
        "列出本代表的私有长期记忆；默认返回全部状态",
        {
            "category": {
                "type": "string",
                "enum": _MEMORY_CATEGORY_VALUES,
            },
            "status": {
                "type": "string",
                "enum": _MEMORY_STATUS_VALUES,
            },
        },
    ),
]


class RepresentativeToolExecutor:
    """分发代表工具并返回 JSON；VenueEngine 停止异常直接交给 Agent 结束线程."""

    def __init__(
        self,
        rep: Representative,
        *,
        memory: AgentMemory | None = None,
    ) -> None:
        self.rep = rep
        self.memory = memory
        self.__successful_tools: list[str] = []
        self.__public_message_limit: int | None = None
        self.__event_action_limit: int | None = None
        self.__public_message_count = 0
        self.__event_action_count = 0

    @property
    def tool_specs(self) -> list[ToolSpec]:
        chair_managed = self.rep._require_venue().chair_agent_managed
        specs = [
            spec
            for spec in REP_TOOL_SPECS
            if not chair_managed or spec.name not in _CHAIR_ONLY_TOOL_NAMES
        ]
        if self.memory is not None:
            specs.extend(MEMORY_TOOL_SPECS)
        return specs

    @property
    def successful_tools(self) -> list[str]:
        """当前 step 内成功执行的工具名，按执行顺序返回副本。"""
        return list(self.__successful_tools)

    def begin_turn(
        self,
        *,
        public_message_limit: int | None = None,
        event_action_limit: int | None = None,
    ) -> None:
        """重置本轮工具轨迹与硬行动预算。"""
        if public_message_limit is not None and public_message_limit < 0:
            raise ValueError("public_message_limit 不能为负数")
        if event_action_limit is not None and event_action_limit < 0:
            raise ValueError("event_action_limit 不能为负数")
        self.__successful_tools = []
        self.__public_message_limit = public_message_limit
        self.__event_action_limit = event_action_limit
        self.__public_message_count = 0
        self.__event_action_count = 0

    def execute(self, call: ToolCall) -> str:
        try:
            args = json.loads(call.arguments or "{}")
            if not isinstance(args, dict):
                raise ValueError("工具参数必须是 JSON 对象")
            self._require_action_budget(call.name)
            if call.name in {"remember", "revise_memory", "list_memories"}:
                payload = self._execute_memory_tool(call.name, args)
            else:
                handler = _HANDLERS.get(call.name)
                if handler is None:
                    raise ValueError(f"未知工具: {call.name!r}")
                payload = handler(self.rep, args)
        except VenueEngineStoppedError:
            raise
        except Exception as exc:
            payload = _err(exc)
        if payload.get("ok") is True:
            self.__successful_tools.append(call.name)
            if call.name == "send_message":
                self.__public_message_count += 1
            if call.name in _EVENT_ACTION_TOOL_NAMES:
                self.__event_action_count += 1
        return json.dumps(payload, ensure_ascii=False)

    def _require_action_budget(self, tool_name: str) -> None:
        if (
            tool_name == "send_message"
            and self.__public_message_limit is not None
            and self.__public_message_count >= self.__public_message_limit
        ):
            raise PermissionError(
                "本轮公开发言额度已用尽；请等待新的实质性事件后再发言"
            )
        if (
            tool_name in _EVENT_ACTION_TOOL_NAMES
            and self.__event_action_limit is not None
            and self.__event_action_count >= self.__event_action_limit
        ):
            raise PermissionError(
                "本轮会场行动额度已用尽；请结束当前轮次并等待新事件"
            )

    def _execute_memory_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        memory = self.memory
        if memory is None:
            raise RuntimeError("当前 Agent 未绑定长期记忆")
        if tool_name == "list_memories":
            entries = memory.list_entries(
                category=args.get("category"),
                status=args.get("status"),
            )
            return _ok([entry.to_dict() for entry in entries])

        source_ids = None
        if "source_event_ids" in args:
            source_ids = _as_int_list(
                args["source_event_ids"],
                field="source_event_ids",
            )
            self._require_visible_event_ids(source_ids)

        if tool_name == "remember":
            entry = memory.remember(
                str(args["category"]),
                str(args["content"]),
                importance=int(args["importance"]),
                source_event_ids=source_ids or [],
            )
            return _ok(entry.to_dict())

        if tool_name == "revise_memory":
            if not any(
                field in args
                for field in (
                    "content",
                    "importance",
                    "source_event_ids",
                    "status",
                )
            ):
                raise ValueError("revise_memory 至少须提供一个要修改的字段")
            entry = memory.revise(
                str(args["memory_id"]),
                content=str(args["content"]) if "content" in args else None,
                importance=(
                    int(args["importance"]) if "importance" in args else None
                ),
                source_event_ids=source_ids,
                status=str(args["status"]) if "status" in args else None,
            )
            return _ok(entry.to_dict())
        raise ValueError(f"未知记忆工具: {tool_name!r}")

    def _require_visible_event_ids(self, event_ids: list[int]) -> None:
        visible_ids = {
            event.id
            for event in self.rep._require_event_list().get_events(self.rep.id)
            if event.id is not None
        }
        unknown = set(event_ids) - visible_ids
        if unknown:
            raise PermissionError(
                f"source_event_ids 包含对代表 {self.rep.id} 不可见的事件: "
                f"{sorted(unknown)}"
            )
