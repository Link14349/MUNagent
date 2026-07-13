"""设计器 Agent 任务调度与 SSE 事件总线."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from munagent.config import load_config
from munagent.designer.agent import Agent, LoopResult
from munagent.designer.scenario import chats as chat_svc
from munagent.designer.scenario import files as file_svc
from munagent.designer.scenario import history as history_svc
from munagent.designer.scenario.files import list_content_paths
from munagent.designer.scenario.package import _find_scenario
from munagent.security.sanitize import sanitize_text
from munagent.server.design_schemas import ActiveTask

_REPLAY_LIMIT = 500
_HEARTBEAT_S = 15.0


def _content_digest(scenario_id: str) -> str:
    root, _ = _find_scenario(scenario_id)
    parts: list[str] = []
    for rel in sorted(list_content_paths(root)):
        text = (root / rel).read_text(encoding="utf-8")
        parts.append(f"{rel}\0{text}")
    payload = "\n".join(parts)
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class _ScenarioRuntime:
    scenario_id: str
    seq: int = 0
    buffer: deque[dict[str, Any]] = field(default_factory=deque)
    subscribers: list[asyncio.Queue[dict[str, Any] | None]] = field(default_factory=list)
    active: ActiveTask | None = None
    abort_flag: bool = False
    task: asyncio.Task[None] | None = None
    last_content_digest: str | None = None


class DesignTaskService:
    """单进程内按场景管理 Agent 任务与 SSE."""

    def __init__(self) -> None:
        self._runtimes: dict[str, _ScenarioRuntime] = {}

    def _rt(self, scenario_id: str) -> _ScenarioRuntime:
        rt = self._runtimes.get(scenario_id)
        if rt is None:
            rt = _ScenarioRuntime(scenario_id=scenario_id)
            self._runtimes[scenario_id] = rt
        return rt

    def get_active_task(self, scenario_id: str) -> ActiveTask | None:
        return self._rt(scenario_id).active

    def has_active_task(self, scenario_id: str) -> bool:
        rt = self._rt(scenario_id)
        return rt.active is not None and rt.task is not None and not rt.task.done()

    def emit(self, scenario_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        rt = self._rt(scenario_id)
        rt.seq += 1
        event = {"seq": rt.seq, **payload}
        rt.buffer.append(event)
        while len(rt.buffer) > _REPLAY_LIMIT:
            rt.buffer.popleft()
        for sub in rt.subscribers:
            sub.put_nowait(event)
        return event

    async def subscribe(self, scenario_id: str, after: int | None) -> AsyncIterator[dict[str, Any]]:
        rt = self._rt(scenario_id)
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        rt.subscribers.append(queue)
        try:
            for event in rt.buffer:
                if after is None or int(event["seq"]) > after:
                    yield event
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_S)
                except TimeoutError:
                    yield {"seq": rt.seq, "type": "heartbeat"}
                    continue
                if item is None:
                    break
                yield item
        finally:
            if queue in rt.subscribers:
                rt.subscribers.remove(queue)

    def prepare_message_task(
        self,
        scenario_id: str,
        chat_id: str,
        text: str,
        *,
        context_file: str | None = None,
    ) -> tuple[str, int, str | None]:
        """校验并准备任务元数据; 返回 (task_id, turn, context_file)."""
        if self.has_active_task(scenario_id):
            raise RuntimeError("另一对话正在生成")
        _root, source = _find_scenario(scenario_id)
        if source == "builtin":
            raise PermissionError("只读场景不可对话, 请先另存为副本")
        chat_svc.get_chat_records(scenario_id, chat_id)

        turn = sum(1 for r in chat_svc.get_chat_records(scenario_id, chat_id) if r.get("type") == "user_message") + 1
        task_id = uuid4().hex[:12]
        rt = self._rt(scenario_id)
        rt.active = ActiveTask(task_id=task_id, chat_id=chat_id, turn=turn)
        rt.abort_flag = False

        digest = _content_digest(scenario_id)
        if rt.last_content_digest is None or digest != rt.last_content_digest:
            chat_title = _chat_title(scenario_id, chat_id)
            history_svc.create_snapshot(
                scenario_id,
                kind="auto",
                reason=f"对话「{chat_title}」第 {turn} 轮之前",
                chat_id=chat_id,
                turn=turn,
            )
        return task_id, turn, context_file

    async def launch_message_task(
        self,
        scenario_id: str,
        chat_id: str,
        text: str,
        *,
        context_file: str | None = None,
    ) -> str:
        task_id, turn, ctx = self.prepare_message_task(
            scenario_id, chat_id, text, context_file=context_file
        )
        rt = self._rt(scenario_id)
        rt.task = asyncio.create_task(
            self._run_task(scenario_id, chat_id, task_id, turn, text, ctx)
        )
        return task_id

    def abort(self, scenario_id: str) -> None:
        rt = self._rt(scenario_id)
        rt.abort_flag = True

    async def _run_task(
        self,
        scenario_id: str,
        chat_id: str,
        task_id: str,
        turn: int,
        text: str,
        context_file: str | None,
    ) -> None:
        rt = self._rt(scenario_id)
        sink = _TaskEventSink(self, scenario_id, chat_id)
        config = load_config()
        agent = Agent(
            scenario_id=scenario_id,
            chat_id=chat_id,
            config=config,
            context_file=context_file,
            event_sink=sink,
            abort_check=lambda: rt.abort_flag,
        )
        self.emit(
            scenario_id,
            {
                "type": "task_started",
                "chat_id": chat_id,
                "task_id": task_id,
                "turn": turn,
            },
        )
        error: str | None = None
        outcome = LoopResult.FAILED.value
        try:
            result = await agent.loop(text)
            outcome = result.value
            if result == LoopResult.FAILED:
                error = "任务失败"
        except Exception as exc:
            outcome = LoopResult.FAILED.value
            error = sanitize_text(str(exc))
            chat_svc.append_chat_record(
                scenario_id,
                chat_id,
                {"type": "system", "kind": "error", "text": error},
                turn=turn,
            )
        finally:
            rt.last_content_digest = _content_digest(scenario_id)
            rt.active = None
            rt.abort_flag = False
            self.emit(
                scenario_id,
                {
                    "type": "task_finished",
                    "chat_id": chat_id,
                    "result": outcome,
                    "error": error,
                },
            )
            self.emit(scenario_id, {"type": "files_changed", "paths": []})


class _TaskEventSink:
    def __init__(self, service: DesignTaskService, scenario_id: str, chat_id: str) -> None:
        self._service = service
        self._scenario_id = scenario_id
        self._chat_id = chat_id

    def on_think_delta(self, text: str) -> None:
        self._service.emit(
            self._scenario_id,
            {"type": "think_delta", "chat_id": self._chat_id, "delta": text},
        )

    def on_text_delta(self, text: str) -> None:
        self._service.emit(
            self._scenario_id,
            {"type": "text_delta", "chat_id": self._chat_id, "delta": text},
        )

    def on_record_appended(self, record: dict[str, Any]) -> None:
        self._service.emit(
            self._scenario_id,
            {"type": "record_appended", "chat_id": self._chat_id, "record": record},
        )
        if record.get("type") == "file_edit" and isinstance(record.get("path"), str):
            self._service.emit(
                self._scenario_id,
                {"type": "files_changed", "paths": [record["path"]]},
            )


def _chat_title(scenario_id: str, chat_id: str) -> str:
    for chat in chat_svc.list_chats(scenario_id):
        if chat.id == chat_id:
            return chat.title
    return chat_id


design_tasks = DesignTaskService()
