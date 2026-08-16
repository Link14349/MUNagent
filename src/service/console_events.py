"""将各会场 EventList 的新增和变化直接输出到服务终端。"""

from __future__ import annotations

from collections.abc import Callable
import json
import threading
from typing import TYPE_CHECKING

from service.meeting_service import serialize_event

if TYPE_CHECKING:
    from scenario.scenario import Scenario


class VenueEventConsoleReporter:
    """轮询权威 EventList；只输出事件，不输出任何 Agent 内部思考。"""

    def __init__(
        self,
        scenario: Scenario,
        *,
        output: Callable[[str], None] | None = None,
        interval_s: float = 0.1,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("interval_s 必须大于 0")
        self.scenario = scenario
        self.output = output or _print_flush
        self.interval_s = interval_s
        self.__fingerprints: dict[tuple[str, int], str] = {}
        self.__stop_event = threading.Event()
        self.__thread: threading.Thread | None = None

    def start(self) -> None:
        if self.__thread is not None:
            raise RuntimeError("VenueEventConsoleReporter 不能重复启动")
        self.__thread = threading.Thread(
            target=self._run,
            name="console-events",
            daemon=True,
        )
        self.__thread.start()

    def stop(self) -> None:
        self.__stop_event.set()

    def join(self, timeout: float | None = None) -> None:
        thread = self.__thread
        if thread is not None:
            thread.join(timeout=timeout)

    def emit_changes(self) -> int:
        """立即扫描一次；返回本次输出的新增或变化事件数。"""
        emitted = 0
        for venue in self.scenario.venues:
            event_list = venue.event_list
            if event_list is None:
                continue
            for event in event_list.events:
                if event.id is None:
                    continue
                payload = serialize_event(event, include_scope=True)
                fingerprint = json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                key = (venue.id, event.id)
                previous = self.__fingerprints.get(key)
                if previous == fingerprint:
                    continue
                self.__fingerprints[key] = fingerprint
                label = "事件" if previous is None else "更新"
                self.output(_format_event_line(label, payload))
                emitted += 1
        return emitted

    def _run(self) -> None:
        while not self.__stop_event.wait(self.interval_s):
            self.emit_changes()
        # 关闭前最后扫一次，避免遗漏刚刚完成入表的事件。
        self.emit_changes()


def _format_event_line(label: str, event: dict[str, object]) -> str:
    content = " ".join(str(event.get("content") or "").splitlines())
    scope = event.get("scope") or []
    return (
        f"[{label}] {event.get('venue')}#{event.get('id')} "
        f"{event.get('time')} [{event.get('type')}/{event.get('status')}] "
        f"scope={scope} {content}"
    )


def _print_flush(line: str) -> None:
    print(line, flush=True)
