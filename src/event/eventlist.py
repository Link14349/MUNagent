from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Callable

from condition.condition import Condition
from event.event import Event, EventStatus, EventType, SystemEvent

if TYPE_CHECKING:
    from scenario.scenario import Scenario


class EventList:
    """推演事件表.

    事件对象构造时 ``time`` / ``id`` 为 ``None``;``submit_event`` 用当前表时钟盖戳并分配
    ``id``.仍为 ``PENDING`` 的事件会进入 pending 队列;``Event.status`` 离开
    ``PENDING`` 时经 ``_event_updated`` 出队.剧情时钟由 ``update_time`` /
    ``time_pass`` 推进;到期的 ``PullUpEvent`` 会落成 ``SystemEvent`` 再入表.
    """

    scenario: Scenario
    pullup_events: list[PullUpEvent]
    __events: list[Event]
    __pending_events: list[int]
    __time: datetime
    __listeners: dict[EventType, list[tuple[str | None, Callable[[Event], None]]]]

    def __init__(self, scenario: Scenario):
        self.scenario = scenario
        self.__events = []
        self.pullup_events = []
        self.__pending_events: list[int] = []
        self.__listeners = {}
        if scenario.start_time is None:
            raise ValueError("场景尚未初始化开场时间")
        self.__time = scenario.start_time

    def add_listener(
        self,
        event_type: EventType,
        listener: Callable[[Event], None],
        venue: str | None = None,
    ) -> None:
        """按 ``EventType`` 注册入表回调.

        ``venue`` 为 ``None`` 时匹配任意会场;否则仅当入表事件的 ``event.venue``
        与之相同才调用.``submit_event`` 成功后按注册顺序通知匹配的 listener.
        """
        self.__listeners.setdefault(event_type, []).append((venue, listener))

    @property
    def time(self) -> datetime:
        return self.__time

    @property
    def pending_event_ids(self) -> list[int]:
        """当前仍为 PENDING 的已入表事件 id(按入队顺序的副本)."""
        return list(self.__pending_events)

    @property
    def pending_events(self) -> list[Event]:
        """当前仍为 PENDING 的已入表事件(按入队顺序的浅拷贝列表,不影响内部队列)."""
        return [self.__events[event_id] for event_id in self.__pending_events]

    def pull_up_event(self, pullup: PullUpEvent):
        if pullup.condition.type != "time":
            raise ValueError("Pull up event must be a time condition")
        if pullup.condition.time < self.time:
            return
        self.pullup_events.append(pullup)

    def update_time(self, time: datetime):
        """将剧情时钟推进到绝对时刻 ``time``(不可倒退)."""
        if time < self.__time:
            raise ValueError("Wrong time order error")
        self.__time = time
        due = [
            pullup
            for pullup in self.pullup_events
            if pullup.condition.time is not None and pullup.condition.time <= self.time
        ]
        for pullup in due:
            venue_id = self.scenario.venues[0].id
            self.submit_event(
                SystemEvent(
                    pullup.content,
                    [],
                    venue_id,
                    {rep.id for rep in self.scenario.representatives},
                    self.scenario,
                )
            )
        due_set = set(due)
        self.pullup_events = [pullup for pullup in self.pullup_events if pullup not in due_set]

    def time_pass(self, delta_time: timedelta) -> None:
        """相对当前时钟推进 ``delta_time``,内部委托 ``update_time``."""
        if delta_time < timedelta(0):
            raise ValueError(f"delta_time 不可为负,实际为 {delta_time!r}")
        self.update_time(self.__time + delta_time)

    def submit_event(self, event: Event):
        """将事件登记入表:盖上当前剧情时间并分配 ``id``,再通知匹配的 listener."""
        if event.time is not None:
            raise ValueError(
                f"事件 time 应由 EventList.submit_event 设定,当前已为 {event.time!r}"
            )
        if event.id is not None:
            raise ValueError(
                f"事件 id 应由 EventList.submit_event 设定,当前已为 {event.id!r}"
            )
        event.time = self.__time
        event.id = len(self.__events)
        self.__events.append(event)
        if event.status == EventStatus.PENDING:
            self.__pending_events.append(event.id)
        for listener_venue, listener in self.__listeners.get(event.type, ()):
            if listener_venue is None or listener_venue == event.venue:
                listener(event)

    def _event_updated(self, event: Event) -> None:
        """由 ``Event.status`` setter 在离开 PENDING 时回调;校验归属后移出 pending.

        约定仅供 Event 调用,不作为对外 API.
        """
        if event.id is None:
            raise ValueError("事件尚未入表,不能更新 pending")
        if (
            event.id < 0
            or event.id >= len(self.__events)
            or self.__events[event.id] is not event
        ):
            raise ValueError(
                f"事件(id={event.id!r}) 不属于本 EventList,不能更新 pending"
            )
        if event.status == EventStatus.PENDING:
            raise ValueError(
                f"事件(id={event.id}) 仍为 PENDING,不应移出 pending 队列"
            )
        try:
            self.__pending_events.remove(event.id)
        except ValueError as exc:
            raise ValueError(
                f"事件(id={event.id}) 不在 pending 队列中"
            ) from exc

    def get_events(self, rep: str) -> list[Event]:
        """返回对 ``rep`` 可见的事件.

        代表获知 submission 文件的唯一正规途径:可见事件(如 Instruction / Resolution)
        上绑定的 ``File`` 引用;不得依赖 FileSystem 对 submissions/ 的直接枚举.
        """
        if rep == "__GOD__":
            return [event for event in self.__events]
        return [event for event in self.__events if rep in event.scope]


class PullUpEvent:
    condition: Condition
    content: str
    scenario: Scenario

    def __init__(self, condition: Condition, content: str, scenario: Scenario):
        self.condition = condition
        self.content = content
        self.scenario = scenario
