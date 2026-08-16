"""代表 Agent 的线程安全观察收件箱。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import StrEnum
import threading
import time


class ObservationKind(StrEnum):
    """会场权威状态发生变化的方式。"""

    EVENT_CREATED = "event_created"
    EVENT_EDITED = "event_edited"
    EVENT_STATUS_CHANGED = "event_status_changed"


class ObservationPriority(StrEnum):
    """观察对正在进行的 Agent 轮次的影响。"""

    NORMAL = "normal"
    URGENT = "urgent"


@dataclass(frozen=True)
class EventSnapshot:
    """事件在投递时刻的不可变、已完成可见性过滤的快照。"""

    id: int
    venue_id: str
    event_type: str
    content: str
    status: str
    time: str
    scope: tuple[str, ...]
    attached_file: str | None = None
    target_reps: tuple[str, ...] = ()


@dataclass(frozen=True)
class Observation:
    """投递给一名代表的一次会场变化通知。"""

    sequence: int
    kind: ObservationKind
    priority: ObservationPriority
    activates_agent: bool
    event: EventSnapshot
    actor_id: str | None = None
    changed_field: str | None = None


class AgentInbox:
    """先等待首条观察，再以固定窗口合并同一时段的普通观察。"""

    def __init__(self) -> None:
        self.__items: deque[Observation] = deque()
        self.__closed = False
        self.__condition = threading.Condition()

    def put(self, observation: Observation) -> bool:
        """写入观察并唤醒等待线程；收件箱关闭后返回 ``False``。"""
        with self.__condition:
            if self.__closed:
                return False
            self.__items.append(observation)
            self.__condition.notify()
            return True

    def close(self) -> None:
        """关闭收件箱并唤醒所有等待线程。未处理观察随之丢弃。"""
        with self.__condition:
            self.__closed = True
            self.__items.clear()
            self.__condition.notify_all()

    def take_batch(self, *, coalesce_s: float = 0.3) -> list[Observation] | None:
        """阻塞等待首条观察，并在固定窗口内合并随后到达的观察。

        紧急观察会立即结束合并窗口。返回 ``None`` 表示收件箱已关闭。
        """
        if coalesce_s < 0:
            raise ValueError(f"coalesce_s 须为非负数，实际为 {coalesce_s!r}")

        with self.__condition:
            self.__condition.wait_for(lambda: self.__items or self.__closed)
            if self.__closed:
                return None

            deadline = time.monotonic() + coalesce_s
            while not self.__contains_urgent_locked():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.__condition.wait(timeout=remaining)
                if self.__closed:
                    return None

            return self.__drain_locked()

    def take_ready(self) -> list[Observation]:
        """不等待，取走当前已积累的全部观察。"""
        with self.__condition:
            return self.__drain_locked()

    def merge_during(
        self,
        initial: list[Observation],
        *,
        wait_s: float,
    ) -> list[Observation] | None:
        """在行动冷却期间保留原 batch，并合并新观察。

        新到达的紧急观察会提前结束等待；返回 ``None`` 表示收件箱关闭。
        """
        if wait_s < 0:
            raise ValueError(f"wait_s 须为非负数，实际为 {wait_s!r}")
        if wait_s == 0:
            return [*initial, *self.take_ready()]

        with self.__condition:
            deadline = time.monotonic() + wait_s
            while not self.__contains_urgent_locked():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.__condition.wait(timeout=remaining)
                if self.__closed:
                    return None
            return [*initial, *self.__drain_locked()]

    def __contains_urgent_locked(self) -> bool:
        return any(
            item.priority == ObservationPriority.URGENT
            and item.activates_agent
            for item in self.__items
        )

    def __drain_locked(self) -> list[Observation]:
        items = list(self.__items)
        self.__items.clear()
        return items
