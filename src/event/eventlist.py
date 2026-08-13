from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Callable

from event.event import Event, EventStatus, EventType

if TYPE_CHECKING:
    from condition.condition import Condition
    from scenario.scenario import Scenario
    from scenario.venue import Venue


class EventList:
    """单个会场的事件表.

    ``EventList`` 只负责编号、保存、pending 队列和 listener 通知，不持有或
    推进剧情时钟。事件时间须已由所属 ``Scenario`` 在 ``Venue.submit_event``
    路径上盖戳；``time is None`` 的事件会被拒绝入表。
    """

    venue: Venue
    __events: list[Event]
    __pending_events: list[int]
    __listeners: dict[EventType, list[Callable[[Event], None]]]
    __lock: threading.RLock

    def __init__(self, venue: Venue) -> None:
        if not venue.id:
            raise ValueError("EventList 所属 Venue.id 不能为空")
        self.venue = venue
        self.__events = []
        self.__pending_events = []
        self.__listeners = {}
        self.__lock = threading.RLock()

    @property
    def venue_id(self) -> str:
        return self.venue.id

    @property
    def events(self) -> list[Event]:
        """已入表事件的浅拷贝列表."""
        with self.__lock:
            return list(self.__events)

    @property
    def pending_event_ids(self) -> list[int]:
        """仍为 ``PENDING`` 的事件 id，按入队顺序返回."""
        with self.__lock:
            return list(self.__pending_events)

    @property
    def pending_events(self) -> list[Event]:
        """仍为 ``PENDING`` 的事件，按入队顺序返回."""
        with self.__lock:
            return [self.__events[event_id] for event_id in self.__pending_events]

    def add_listener(
        self,
        event_type: EventType,
        listener: Callable[[Event], None],
    ) -> None:
        """按事件类型注册本会场入表回调."""
        with self.__lock:
            self.__listeners.setdefault(event_type, []).append(listener)

    def submit_event(self, event: Event) -> Event:
        """经所属 Venue 的队列提交事件并等待处理结果."""
        return self.venue.submit_event(event)

    def _commit_event(self, event: Event) -> None:
        """为已由 Scenario 盖戳的会场事件编号、入表并通知 listener."""
        with self.__lock:
            if event.venue != self.venue.id:
                raise ValueError(
                    f"事件 venue={event.venue!r} 与 EventList 所属会场 "
                    f"{self.venue.id!r} 不一致"
                )
            if event.time is None:
                raise ValueError(
                    "事件 time 应由 Scenario 盖戳后再入表,当前为 None"
                )
            if event.id is not None:
                raise ValueError(
                    f"事件 id 应由 EventList._commit_event 设定,当前已为 {event.id!r}"
                )

            event.id = len(self.__events)
            self.__events.append(event)
            if event.status == EventStatus.PENDING:
                self.__pending_events.append(event.id)
            listeners = list(self.__listeners.get(event.type, ()))

        for listener in listeners:
            listener(event)

    def _update_event_status(
        self,
        event: Event,
        status: EventStatus,
    ) -> EventStatus:
        """在同一临界区更新事件状态及 pending 队列."""
        with self.__lock:
            if event.id is None:
                raise ValueError("事件尚未入表,不能更新 pending")
            if (
                event.id < 0
                or event.id >= len(self.__events)
                or self.__events[event.id] is not event
            ):
                raise ValueError(
                    f"事件(id={event.id!r}, venue={event.venue!r}) 不属于会场 "
                    f"{self.venue.id!r} 的 EventList,不能更新 pending"
                )
            event._apply_status(status)
            if status == EventStatus.PENDING:
                return status
            try:
                self.__pending_events.remove(event.id)
            except ValueError as exc:
                raise ValueError(
                    f"事件(id={event.id}, venue={event.venue!r}) 不在 pending 队列中"
                ) from exc
            return status

    def _edit_event(
        self,
        event: Event,
        field: str,
        attribute: str,
        value: object,
    ) -> None:
        """在 EventList 临界区内校验归属并编辑 PENDING 事件字段."""
        with self.__lock:
            if event.id is None:
                raise ValueError("事件尚未入表,不能通过 VenueEngine 编辑")
            if (
                event.id < 0
                or event.id >= len(self.__events)
                or self.__events[event.id] is not event
            ):
                raise ValueError(
                    f"事件(id={event.id!r}, venue={event.venue!r}) 不属于会场 "
                    f"{self.venue.id!r} 的 EventList,不能编辑 {field}"
                )
            event._apply_edit(field, attribute, value)

    def get_events(self, rep: str) -> list[Event]:
        """返回本会场内对 ``rep`` 可见的事件."""
        with self.__lock:
            if rep == "__GOD__":
                return list(self.__events)
            return [event for event in self.__events if rep in event.scope]


class PullUpEvent:
    condition: Condition
    content: str
    scenario: Scenario

    def __init__(self, condition: Condition, content: str, scenario: Scenario):
        self.condition = condition
        self.content = content
        self.scenario = scenario
