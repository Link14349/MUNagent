"""单次会议运行控制、状态快照与审计存档。"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from enum import StrEnum
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
from typing import TYPE_CHECKING

from engine.simulator import LLMFactory, Simulator, VenueLLMFactory
from event.event import (
    AddAgendaEvent,
    ChatEvent,
    ChairEvent,
    Event,
    InstructionEvent,
    MessageEvent,
    MeetingStartEvent,
    MotionSwitchEvent,
    NoteEvent,
    PhaseSwitchEvent,
    ResolutionEvent,
    SetAgendaEvent,
    SystemEvent,
    VoteEvent,
)
from scenario.load import load_scenario

if TYPE_CHECKING:
    from engine.end_conditions import TextEndConditionEvaluator
    from scenario.scenario import Scenario


class RunState(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    ENDED = "ended"
    STOPPED = "stopped"
    FAILED = "failed"


_TERMINAL_STATES = {RunState.ENDED, RunState.STOPPED, RunState.FAILED}


class MeetingRun:
    """管理一场会议，并持续将可复盘状态写入本次 simulation 目录。"""

    def __init__(
        self,
        scenario: Scenario | str | Path,
        *,
        seed: str | int | None = None,
        llm_factory: LLMFactory | None = None,
        chair_llm_factory: VenueLLMFactory | None = None,
        dm_llm_factory: VenueLLMFactory | None = None,
        text_end_condition_evaluator: TextEndConditionEvaluator | None = None,
        runtime_config: dict[str, object] | None = None,
        archive_interval_s: float = 0.5,
    ) -> None:
        if archive_interval_s <= 0:
            raise ValueError("archive_interval_s 必须大于 0")
        self.scenario = (
            load_scenario(scenario)
            if isinstance(scenario, (str, Path))
            else scenario
        )
        self.seed = str(seed) if seed is not None else secrets.token_hex(16)
        self.runtime_config = dict(runtime_config or {})
        self.simulator = Simulator(
            self.scenario,
            llm_factory=llm_factory,
            chair_llm_factory=chair_llm_factory,
            dm_llm_factory=dm_llm_factory,
            dm_random_seed=self.seed,
            text_end_condition_evaluator=text_end_condition_evaluator,
        )
        self.archive_interval_s = archive_interval_s
        self.__state = RunState.STARTING
        self.__started_at: str | None = None
        self.__ended_at: str | None = None
        self.__manual_stop_reason: str | None = None
        self.__failure: str | None = None
        self.__run_dir: Path | None = None
        self.__state_lock = threading.RLock()
        self.__archive_lock = threading.Lock()
        self.__done = threading.Event()
        self.__supervisor_thread: threading.Thread | None = None
        self.__archive_thread: threading.Thread | None = None

    @property
    def state(self) -> RunState:
        with self.__state_lock:
            return self.__state

    @property
    def run_dir(self) -> Path | None:
        with self.__state_lock:
            return self.__run_dir

    @property
    def done(self) -> bool:
        return self.__done.is_set()

    def start(self) -> None:
        with self.__state_lock:
            if self.__started_at is not None:
                raise RuntimeError("MeetingRun 不能重复启动")
            self.__started_at = _utc_now()
        try:
            self.simulator.start()
        except BaseException as exc:
            with self.__state_lock:
                self.__state = RunState.FAILED
                self.__failure = _format_exception(exc)
                self.__ended_at = _utc_now()
                filesystem = self.scenario.filesystem
                self.__run_dir = filesystem.path if filesystem is not None else None
            self.__done.set()
            self.persist_archive()
            raise

        filesystem = self.scenario.filesystem
        if filesystem is None:
            raise RuntimeError("Simulator 启动后未创建运行目录")
        with self.__state_lock:
            self.__run_dir = filesystem.path
            self.__state = RunState.RUNNING

        self.persist_archive()
        self.__archive_thread = threading.Thread(
            target=self._archive_loop,
            name="run-archive",
            daemon=True,
        )
        self.__supervisor_thread = threading.Thread(
            target=self._supervise,
            name="run-supervisor",
            daemon=True,
        )
        self.__archive_thread.start()
        self.__supervisor_thread.start()

    def stop(self, reason: str = "operator_requested") -> RunState:
        normalized = reason.strip()
        if not normalized:
            raise ValueError("停止原因不能为空")
        with self.__state_lock:
            if self.__state in _TERMINAL_STATES:
                return self.__state
            self.__manual_stop_reason = normalized
        if self.simulator.started and not self.simulator.stop_requested:
            self.simulator.stop()
        return self.state

    def wait(self, timeout: float | None = None) -> bool:
        return self.__done.wait(timeout)

    def snapshot(self) -> dict[str, object]:
        with self.__state_lock:
            state = self.__state
            started_at = self.__started_at
            ended_at = self.__ended_at
            manual_stop_reason = self.__manual_stop_reason
            failure = self.__failure
            run_dir = self.__run_dir

        match = self.simulator.end_condition_match
        warning = self.simulator.end_condition_error
        end_condition_failure = self.simulator.end_condition_fatal_error
        venues: list[dict[str, object]] = []
        for venue in self.scenario.venues:
            event_list = venue.event_list
            events = event_list.events if event_list is not None else []
            pending_ids = (
                event_list.pending_event_ids if event_list is not None else []
            )
            agenda = venue.current_agenda
            venues.append(
                {
                    "id": venue.id,
                    "name": venue.name,
                    "phase": (
                        venue.session_phase.value
                        if venue.session_phase is not None
                        else None
                    ),
                    "current_agenda": (
                        {"id": agenda.id, "title": agenda.title}
                        if agenda is not None
                        else None
                    ),
                    "event_count": len(events),
                    "public_event_count": sum(
                        event.scope == set(venue.seats) for event in events
                    ),
                    "pending_event_ids": pending_ids,
                    "threads": {
                        "venue": _thread_alive(
                            self.simulator.venue_threads.get(venue.id)
                        ),
                        "chair": _thread_alive(
                            self.simulator.chair_threads.get(venue.id)
                        ),
                        "dm": _thread_alive(
                            self.simulator.dm_threads.get(venue.id)
                        ),
                    },
                    "dm_processed_event_ids": sorted(
                        self.simulator.dm_agents[venue.id].processed_event_ids
                    )
                    if venue.id in self.simulator.dm_agents
                    else [],
                }
            )

        worker_errors = {
            "venues": _serialize_errors(self.simulator.venue_errors),
            "representatives": _serialize_errors(self.simulator.agent_errors),
            "chairs": _serialize_errors(self.simulator.chair_errors),
            "dms": _serialize_errors(self.simulator.dm_errors),
        }
        return {
            "run_id": run_dir.name if run_dir is not None else None,
            "state": state.value,
            "scenario": {
                "title": self.scenario.title,
                "path": (
                    str(self.scenario.root_path)
                    if self.scenario.root_path is not None
                    else None
                ),
            },
            "seed": self.seed,
            "started_at": started_at,
            "ended_at": ended_at,
            "story_time": (
                self.scenario.time.isoformat()
                if self.scenario.filesystem is not None
                else None
            ),
            "archive_path": str(run_dir) if run_dir is not None else None,
            "runtime_config": self.runtime_config,
            "end_condition": asdict(match) if match is not None else None,
            "manual_stop_reason": manual_stop_reason,
            "failure": failure,
            "end_condition_warning": (
                _format_exception(warning) if warning is not None else None
            ),
            "end_condition_failure": (
                _format_exception(end_condition_failure)
                if end_condition_failure is not None
                else None
            ),
            "worker_errors": worker_errors,
            "representatives": [
                {
                    "id": rep.id,
                    "name": rep.name,
                    "thread_alive": _thread_alive(
                        self.simulator.agent_threads.get(rep.id)
                    ),
                }
                for rep in self.scenario.representatives
            ],
            "venues": venues,
        }

    def public_events(
        self,
        *,
        venue_id: str | None = None,
        after: int = -1,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        if after < -1:
            raise ValueError("after 不能小于 -1")
        if limit < 1 or limit > 500:
            raise ValueError("limit 必须位于 1..500")
        known = {venue.id for venue in self.scenario.venues}
        if venue_id is not None and venue_id not in known:
            raise ValueError(f"未知会场 ID: {venue_id!r}")

        result: list[dict[str, object]] = []
        for venue in self.scenario.venues:
            if venue_id is not None and venue.id != venue_id:
                continue
            event_list = venue.event_list
            if event_list is None:
                continue
            for event in event_list.events:
                if event.id is None or event.id <= after:
                    continue
                if event.scope != set(venue.seats):
                    continue
                result.append(serialize_event(event, include_scope=False))
        return result[:limit]

    def persist_archive(self) -> None:
        run_dir = self.run_dir
        if run_dir is None:
            return
        with self.__archive_lock:
            status_text = json.dumps(
                self.snapshot(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n"
            event_lines: list[str] = []
            for venue in self.scenario.venues:
                event_list = venue.event_list
                if event_list is None:
                    continue
                event_lines.extend(
                    json.dumps(
                        serialize_event(event, include_scope=True),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    for event in event_list.events
                )
            events_text = "\n".join(event_lines)
            if events_text:
                events_text += "\n"
            _atomic_write(run_dir / "run.json", status_text)
            _atomic_write(run_dir / "events.jsonl", events_text)

    def _supervise(self) -> None:
        try:
            self.simulator.join()
        except BaseException as exc:
            with self.__state_lock:
                self.__state = RunState.FAILED
                self.__failure = _format_exception(exc)
        else:
            with self.__state_lock:
                if self.simulator.end_condition_match is not None:
                    self.__state = RunState.ENDED
                elif self.__manual_stop_reason is not None:
                    self.__state = RunState.STOPPED
                else:
                    self.__state = RunState.ENDED
        finally:
            with self.__state_lock:
                self.__ended_at = _utc_now()
            try:
                self.persist_archive()
            except Exception as exc:
                with self.__state_lock:
                    self.__state = RunState.FAILED
                    self.__failure = f"运行存档失败：{_format_exception(exc)}"
            finally:
                # wait() 返回即表示最终状态和存档写入已经完成（或明确失败）。
                self.__done.set()

    def _archive_loop(self) -> None:
        while not self.__done.wait(self.archive_interval_s):
            self.persist_archive()
        self.persist_archive()


def serialize_event(event: Event, *, include_scope: bool) -> dict[str, object]:
    payload: dict[str, object] = {
        "venue": event.venue,
        "id": event.id,
        "time": event.time.isoformat() if event.time is not None else None,
        "type": event.type.value,
        "status": event.status.value,
        "content": event.content,
    }
    if include_scope:
        payload["scope"] = sorted(event.scope)

    if isinstance(event, SystemEvent):
        payload["action"] = event.action
    elif isinstance(event, MeetingStartEvent):
        payload["target_reps"] = sorted(event.target_reps)
        payload["activates_chair"] = event.activates_chair
    elif isinstance(event, ChairEvent):
        payload["action"] = event.action.value
        payload["target_reps"] = sorted(event.target_reps)
    elif isinstance(event, PhaseSwitchEvent):
        payload["previous_phase"] = (
            event.previous_phase.value if event.previous_phase is not None else None
        )
        payload["target_phase"] = event.target_phase.value
    elif isinstance(event, MotionSwitchEvent):
        payload["target_phase"] = event.target_phase.value
    elif isinstance(event, (InstructionEvent, ResolutionEvent)):
        file = (
            event.instruction
            if isinstance(event, InstructionEvent)
            else event.resolution
        )
        filesystem = file._filesystem
        payload["from_reps"] = sorted(event.from_reps)
        payload["submission"] = {
            "path": (
                filesystem._relkey(file.path)
                if filesystem is not None
                else file.path.name
            ),
            "content_hash": file.content_hash,
        }
    elif isinstance(event, VoteEvent):
        payload["target_event_id"] = event.target.id
        payload["passed"] = event.passed
        payload["support_count"] = event.support_count
        payload["against_count"] = event.against_count
        payload["abstention_count"] = event.abstention_count
        payload["pass_mode"] = event.pass_mode.value
        payload["named"] = event.named
        if event.named:
            payload["supporters"] = event.supporters
            payload["against"] = event.against
            payload["abstentions"] = event.abstentions
    elif isinstance(event, (MessageEvent, NoteEvent, ChatEvent)):
        payload["from_rep"] = event.from_rep
        if isinstance(event, NoteEvent):
            payload["to_reps"] = sorted(event.to_reps)
    elif isinstance(event, (AddAgendaEvent, SetAgendaEvent)):
        payload["from_rep"] = event.from_rep
        payload["agenda_id"] = event.agenda.id
    return payload


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _thread_alive(thread: threading.Thread | None) -> bool:
    return thread is not None and thread.is_alive()


def _serialize_errors(errors: dict[str, Exception]) -> dict[str, str]:
    return {key: _format_exception(value) for key, value in errors.items()}


def _format_exception(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
