from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import threading
from typing import TYPE_CHECKING

from condition.condition import Condition
from scenario.representative import Representative
from scenario.venue import Venue

if TYPE_CHECKING:
    from event.event import Event, EventStatus
    from event.eventlist import PullUpEvent
    from filesystem.filesystem import FileSystem


class Scenario:
    title: str
    background: str
    targets: list[str]
    description: str
    timezone: str
    start_time: datetime | None
    event_pool: list[PullUpEvent]
    end_conditions: list[Condition]
    venues: list[Venue]
    representatives: list[Representative]
    reps: dict[str, Representative]
    root_path: Path | None
    filesystem: FileSystem | None
    __time: datetime | None
    __pullup_events: list[PullUpEvent]
    __time_lock: threading.RLock
    __time_update_lock: threading.RLock

    def __init__(self) -> None:
        self.title = ""
        self.background = ""
        self.targets = []
        self.description = ""
        self.timezone = ""
        self.start_time = None
        self.event_pool = []
        self.end_conditions = []
        self.venues = []
        self.representatives = []
        self.reps = {}
        self.root_path = None
        self.filesystem = None
        self.__time = None
        self.__pullup_events = []
        self.__time_lock = threading.RLock()
        self.__time_update_lock = threading.RLock()

    def load(self, scenario_path: str) -> None:
        from scenario.load import populate_scenario

        populate_scenario(self, scenario_path)

    @property
    def time(self) -> datetime:
        """全场景统一的当前剧情时间."""
        with self.__time_lock:
            if self.__time is None:
                raise RuntimeError("Scenario 尚未 initialize，剧情时间不可用")
            return self.__time

    @property
    def pullup_events(self) -> list[PullUpEvent]:
        """尚未到期的时间条件外部事件副本."""
        with self.__time_lock:
            return list(self.__pullup_events)

    def pull_up_event(self, pullup: PullUpEvent) -> None:
        """将时间条件外部事件挂入场景级待触发队列."""
        with self.__time_lock:
            if pullup.scenario is not self:
                raise ValueError("PullUpEvent 不属于当前 Scenario")
            if pullup.condition.type != "time" or pullup.condition.time is None:
                raise ValueError("Pull up event must be a time condition")
            if pullup.condition.time < self.time:
                return
            self.__pullup_events.append(pullup)

    def _event_submission_time(self, event: Event) -> datetime:
        """校验事件归属并取得提交瞬间的统一剧情时间."""
        with self.__time_lock:
            if event.scenario is not self:
                raise ValueError("事件不属于当前 Scenario,不能使用本场景时间盖戳")
            if event.time is not None:
                raise ValueError(
                    f"事件 time 应由 Scenario 设定,当前已为 {event.time!r}"
                )
            return self.time

    def _stamp_event(self, event: Event, event_time: datetime) -> None:
        """按场景统一时钟为尚未入表的事件盖戳."""
        with self.__time_lock:
            if event.scenario is not self:
                raise ValueError("事件不属于当前 Scenario,不能使用本场景时间盖戳")
            if event.time is not None:
                raise ValueError(
                    f"事件 time 应由 Scenario 设定,当前已为 {event.time!r}"
                )
            if self.__time is None:
                raise RuntimeError("Scenario 尚未 initialize，无法为事件盖戳")
            if event_time > self.__time:
                raise ValueError(
                    f"事件提交时间 {event_time!r} 晚于当前剧情时间 {self.__time!r}"
                )
            event.time = event_time

    def _update_event_status(
        self,
        event: Event,
        status: EventStatus,
    ) -> EventStatus:
        """将已入表事件的状态命令路由到所属 VenueEngine."""
        if event.scenario is not self:
            raise ValueError("事件不属于当前 Scenario,不能更新 pending")
        venue = next((item for item in self.venues if item.id == event.venue), None)
        if venue is None:
            raise ValueError(f"事件所属会场不存在: {event.venue!r}")
        event_list = venue.event_list
        if event_list is None:
            raise RuntimeError(
                f"事件(id={event.id}, venue={event.venue!r}) 已入表,"
                "但所属 Venue.event_list 为空,无法更新 pending"
            )
        return venue._update_event_status(event, status)

    def _edit_event(
        self,
        event: Event,
        field: str,
        attribute: str,
        value: object,
    ) -> None:
        """将已提交事件的字段修改路由到所属 VenueEngine."""
        if event.scenario is not self:
            raise ValueError("事件不属于当前 Scenario,不能编辑")
        venue = next((item for item in self.venues if item.id == event.venue), None)
        if venue is None:
            raise ValueError(f"事件所属会场不存在: {event.venue!r}")
        venue._edit_event(event, field, attribute, value)

    def update_time(self, new_time: datetime) -> None:
        """将全场景剧情时钟推进到绝对时刻 ``new_time``，不可倒退."""
        with self.__time_update_lock:
            with self.__time_lock:
                if new_time < self.time:
                    raise ValueError("剧情时间不可倒退")
                self.__time = new_time

                due = [
                    pullup
                    for pullup in self.__pullup_events
                    if pullup.condition.time is not None
                    and pullup.condition.time <= new_time
                ]
                due_set = set(due)
                self.__pullup_events = [
                    pullup
                    for pullup in self.__pullup_events
                    if pullup not in due_set
                ]
            if not due:
                return

            from event.event import SystemEvent

            for pullup in due:
                for venue in self.venues:
                    venue._submit_event(
                        SystemEvent(
                            pullup.content,
                            [],
                            venue.id,
                            set(venue.seats),
                            self,
                        ),
                        new_time,
                    )

    def time_pass(self, delta_time: timedelta) -> None:
        """让全场景剧情时钟相对推进 ``delta_time``."""
        if delta_time < timedelta(0):
            raise ValueError(f"delta_time 不可为负,实际为 {delta_time!r}")
        with self.__time_update_lock:
            self.update_time(self.time + delta_time)

    def initialize(self) -> None:
        """准备一次推演运行:统一时钟、定时事件、各会场事件表和文件系统."""
        from filesystem.filesystem import FileSystem

        if self.filesystem is not None:
            raise RuntimeError("Scenario 已绑定 FileSystem,不能重复 initialize")

        if self.start_time is None:
            raise RuntimeError("Scenario 尚未加载 start_time,不能 initialize")

        with self.__time_lock:
            self.__time = self.start_time
            self.__pullup_events = []
        for pullup in self.event_pool:
            if pullup.condition.type == "time":
                self.pull_up_event(pullup)

        self.filesystem = FileSystem.create_for_scenario(self)

        for venue in self.venues:
            venue.initialize()
