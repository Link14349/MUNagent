from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scenario.venue import Venue


class Agenda:
    id: str
    title: str
    questions: list[str]

    def __init__(self, id: str, title: str, questions: list[str]):
        self.id = id
        self.title = title
        self.questions = list(questions)


class AgendaManager:
    """会场议题管理:维护 current / todo / finished 三个集合.

    Venue 不直接改动议题列表,一律通过本类操作.
    构造时用 ``initial_agenda_id`` 指定开场 ``current_agenda``,其余进入 ``todo_agenda``.
    ``current_agenda`` / ``todo_agenda`` / ``finished_agenda`` 仅能通过 property 读取(列表为副本).
    """

    venue: Venue
    __lock: threading.RLock

    def __init__(
        self,
        agenda_list: list[Agenda],
        venue: Venue,
        *,
        initial_agenda_id: str,
    ):
        if not agenda_list:
            raise ValueError(
                f"会场 {venue.id or '<unset>'} 的 agenda_list 不能为空"
            )

        seen: set[str] = set()
        ordered: list[Agenda] = []
        for agenda in agenda_list:
            if not agenda.id.strip():
                raise ValueError(
                    f"会场 {venue.id or '<unset>'} 存在空议题 ID"
                )
            if agenda.id in seen:
                raise ValueError(
                    f"会场 {venue.id or '<unset>'} 存在重复议题 ID: {agenda.id}"
                )
            seen.add(agenda.id)
            ordered.append(agenda)

        if initial_agenda_id not in seen:
            raise ValueError(
                f"会场 {venue.id or '<unset>'}.initial_agenda "
                f"引用未知议题 ID: {initial_agenda_id}"
            )

        self.venue = venue
        self.__by_id: dict[str, Agenda] = {item.id: item for item in ordered}
        self.__current_agenda: Agenda | None = self.__by_id[initial_agenda_id]
        self.__todo_agenda: list[Agenda] = [
            item for item in ordered if item.id != initial_agenda_id
        ]
        self.__finished_agenda: list[Agenda] = []
        self.__lock = threading.RLock()

    @property
    def current_agenda(self) -> Agenda | None:
        with self.__lock:
            return self.__current_agenda

    @property
    def todo_agenda(self) -> list[Agenda]:
        with self.__lock:
            return list(self.__todo_agenda)

    @property
    def finished_agenda(self) -> list[Agenda]:
        with self.__lock:
            return list(self.__finished_agenda)

    def get(self, agenda_id: str) -> Agenda:
        """按 ID 取得议题对象."""
        with self.__lock:
            try:
                return self.__by_id[agenda_id]
            except KeyError as exc:
                raise ValueError(
                    f"会场 {self.venue.id or '<unset>'} 未知议题 ID: {agenda_id}"
                ) from exc

    def set_current_agenda(self, agenda: Agenda, finished: bool = False) -> None:
        """将 ``agenda`` 设为当前议题.

        ``agenda`` 必须位于 ``todo_agenda`` 中(已是当前议题则无操作).
        原 ``current_agenda``:``finished=True`` 时进入 ``finished_agenda``,
        否则退回 ``todo_agenda`` 末尾.
        """
        with self.__lock:
            if agenda is self.__current_agenda:
                return

            if agenda not in self.__todo_agenda:
                raise ValueError(
                    f"议题 {agenda.id} 不在会场 {self.venue.id or '<unset>'} 的 todo_agenda 中"
                )

            if self.__current_agenda is not None:
                if finished:
                    self.__finished_agenda.append(self.__current_agenda)
                else:
                    self.__todo_agenda.append(self.__current_agenda)

            self.__todo_agenda.remove(agenda)
            self.__current_agenda = agenda

    def add_todo(self, agenda: Agenda) -> None:
        """向 ``todo_agenda`` 追加新议题(ID 全局唯一)."""
        with self.__lock:
            if agenda.id in self.__by_id:
                raise ValueError(
                    f"会场 {self.venue.id or '<unset>'} 已存在议题 ID: {agenda.id}"
                )
            self.__by_id[agenda.id] = agenda
            self.__todo_agenda.append(agenda)
