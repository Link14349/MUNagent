"""代表 Agent 的结构化长期记忆与可见事件历史索引。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
import re
import threading

from agent.inbox import (
    EventSnapshot,
    Observation,
    ObservationKind,
    ObservationPriority,
)


class MemoryCategory(StrEnum):
    """长期记忆的语义类别。"""

    STRATEGY = "strategy"
    COMMITMENT = "commitment"
    BELIEF = "belief"
    OPEN_QUESTION = "open_question"
    RELATIONSHIP = "relationship"
    FACT = "fact"


class MemoryStatus(StrEnum):
    """记忆是否仍应参与默认上下文。"""

    ACTIVE = "active"
    RESOLVED = "resolved"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class MemoryEntry:
    """一条带来源和修订序号的 Agent 私有记忆。"""

    id: str
    category: MemoryCategory
    content: str
    importance: int
    source_event_ids: tuple[int, ...]
    status: MemoryStatus
    created_sequence: int
    updated_sequence: int

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "category": self.category.value,
            "content": self.content,
            "importance": self.importance,
            "source_event_ids": list(self.source_event_ids),
            "status": self.status.value,
            "created_sequence": self.created_sequence,
            "updated_sequence": self.updated_sequence,
        }


class AgentMemory:
    """线程安全、只追加 ID 且以状态保留修订结果的私有记忆表。"""

    def __init__(self) -> None:
        self.__entries: dict[str, MemoryEntry] = {}
        self.__next_id = 1
        self.__current_sequence = 0
        self.__lock = threading.RLock()

    def note_sequence(self, sequence: int) -> None:
        """推进记忆修订使用的观察序号。"""
        if sequence < 0:
            raise ValueError(f"sequence 须为非负整数,实际为 {sequence!r}")
        with self.__lock:
            self.__current_sequence = max(self.__current_sequence, sequence)

    def remember(
        self,
        category: MemoryCategory | str,
        content: str,
        *,
        importance: int = 3,
        source_event_ids: list[int] | tuple[int, ...] = (),
    ) -> MemoryEntry:
        """新增记忆；同类别同正文的 active 项会合并来源并提高重要度。"""
        normalized = _normalize_content(content)
        level = _normalize_importance(importance)
        sources = _normalize_source_ids(source_event_ids)
        memory_category = MemoryCategory(category)

        with self.__lock:
            for memory_id, entry in self.__entries.items():
                if (
                    entry.status == MemoryStatus.ACTIVE
                    and entry.category == memory_category
                    and entry.content == normalized
                ):
                    updated = replace(
                        entry,
                        importance=max(entry.importance, level),
                        source_event_ids=tuple(
                            sorted(set(entry.source_event_ids) | set(sources))
                        ),
                        updated_sequence=self.__current_sequence,
                    )
                    self.__entries[memory_id] = updated
                    return updated

            memory_id = f"m{self.__next_id}"
            self.__next_id += 1
            entry = MemoryEntry(
                id=memory_id,
                category=memory_category,
                content=normalized,
                importance=level,
                source_event_ids=sources,
                status=MemoryStatus.ACTIVE,
                created_sequence=self.__current_sequence,
                updated_sequence=self.__current_sequence,
            )
            self.__entries[memory_id] = entry
            return entry

    def revise(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        importance: int | None = None,
        source_event_ids: list[int] | tuple[int, ...] | None = None,
        status: MemoryStatus | str | None = None,
    ) -> MemoryEntry:
        """修订或关闭已有记忆，ID 保持不变。"""
        with self.__lock:
            try:
                entry = self.__entries[memory_id]
            except KeyError as exc:
                raise ValueError(f"未知 memory_id: {memory_id!r}") from exc

            updated = replace(
                entry,
                content=(
                    _normalize_content(content) if content is not None else entry.content
                ),
                importance=(
                    _normalize_importance(importance)
                    if importance is not None
                    else entry.importance
                ),
                source_event_ids=(
                    _normalize_source_ids(source_event_ids)
                    if source_event_ids is not None
                    else entry.source_event_ids
                ),
                status=MemoryStatus(status) if status is not None else entry.status,
                updated_sequence=self.__current_sequence,
            )
            self.__entries[memory_id] = updated
            return updated

    def list_entries(
        self,
        *,
        category: MemoryCategory | str | None = None,
        status: MemoryStatus | str | None = None,
    ) -> list[MemoryEntry]:
        """按创建 ID 返回筛选后的记忆副本。"""
        wanted_category = MemoryCategory(category) if category is not None else None
        wanted_status = MemoryStatus(status) if status is not None else None
        with self.__lock:
            return [
                entry
                for entry in self.__entries.values()
                if (wanted_category is None or entry.category == wanted_category)
                and (wanted_status is None or entry.status == wanted_status)
            ]

    def relevant(self, query: str, *, limit: int = 12) -> list[MemoryEntry]:
        """以重要度、文本相关性和更新时间选出 active 记忆。"""
        if limit < 1:
            return []
        query_tokens = text_tokens(query)
        with self.__lock:
            active = [
                entry
                for entry in self.__entries.values()
                if entry.status == MemoryStatus.ACTIVE
            ]
        scored = sorted(
            active,
            key=lambda entry: (
                len(query_tokens & text_tokens(entry.content)) * 10,
                entry.importance,
                entry.updated_sequence,
                -int(entry.id[1:]),
            ),
            reverse=True,
        )
        return scored[:limit]


@dataclass(frozen=True)
class HistoricalEvent:
    """一名代表实际收到过的事件版本。"""

    event: EventSnapshot
    first_sequence: int
    last_sequence: int
    actor_id: str | None


@dataclass(frozen=True)
class HistorySummary:
    """一段连续旧事件的确定性摘要。"""

    first_event_id: int
    last_event_id: int
    event_ids: tuple[int, ...]
    text: str


class EventHistory:
    """按代表可见性建立的事件版本索引、摘要与相关性检索器。"""

    def __init__(self) -> None:
        self.__events: dict[int, HistoricalEvent] = {}
        self.__lock = threading.RLock()

    def record(self, observation: Observation) -> None:
        """记录新观察；同一事件的编辑/裁定会替换当前快照。"""
        event_id = observation.event.id
        with self.__lock:
            previous = self.__events.get(event_id)
            self.__events[event_id] = HistoricalEvent(
                event=observation.event,
                first_sequence=(
                    observation.sequence
                    if previous is None
                    else previous.first_sequence
                ),
                last_sequence=observation.sequence,
                actor_id=(
                    observation.actor_id
                    if observation.actor_id is not None
                    else previous.actor_id if previous is not None else None
                ),
            )

    def record_snapshot(
        self,
        event: EventSnapshot,
        *,
        sequence: int = 0,
        actor_id: str | None = None,
    ) -> None:
        """载入 Agent 创建前已经可见的事件。"""
        self.record(
            Observation(
                sequence=sequence,
                kind=ObservationKind.EVENT_CREATED,
                priority=ObservationPriority.NORMAL,
                activates_agent=False,
                event=event,
                actor_id=actor_id,
            )
        )

    def get(self, event_id: int) -> HistoricalEvent | None:
        with self.__lock:
            return self.__events.get(event_id)

    def retrieve(
        self,
        query: str,
        *,
        exclude_event_ids: set[int] | None = None,
        pinned_event_ids: set[int] | None = None,
        limit: int = 6,
    ) -> list[EventSnapshot]:
        """按来源固定、词项重合、事件重要度和新近度检索旧事件。"""
        if limit < 1:
            return []
        excluded = exclude_event_ids or set()
        pinned = pinned_event_ids or set()
        query_tokens = text_tokens(query)
        with self.__lock:
            candidates = [
                item for item in self.__events.values() if item.event.id not in excluded
            ]

        def score(item: HistoricalEvent) -> tuple[int, int, int, int]:
            event = item.event
            overlap = len(query_tokens & text_tokens(event.content))
            type_weight = _EVENT_TYPE_WEIGHT.get(event.event_type, 0)
            return (
                1 if event.id in pinned else 0,
                overlap,
                type_weight,
                item.last_sequence * 1000 + event.id,
            )

        ranked = sorted(candidates, key=score, reverse=True)
        return [item.event for item in ranked[:limit]]

    def summarize(
        self,
        query: str,
        *,
        exclude_event_ids: set[int] | None = None,
        segment_size: int = 6,
        limit: int = 4,
    ) -> list[HistorySummary]:
        """把未直接注入的旧事件压缩成连续分段，并检索最相关的分段。"""
        if segment_size < 1 or limit < 1:
            return []
        excluded = exclude_event_ids or set()
        with self.__lock:
            events = sorted(
                (
                    item.event
                    for item in self.__events.values()
                    if item.event.id not in excluded
                ),
                key=lambda event: event.id,
            )

        segments: list[HistorySummary] = []
        for offset in range(0, len(events), segment_size):
            group = events[offset : offset + segment_size]
            segments.append(
                HistorySummary(
                    first_event_id=group[0].id,
                    last_event_id=group[-1].id,
                    event_ids=tuple(event.id for event in group),
                    text="；".join(
                        f"#{event.id} {event.event_type}/{event.status}:"
                        f"{_truncate(event.content, 72)}"
                        for event in group
                    ),
                )
            )

        query_tokens = text_tokens(query)
        ranked = sorted(
            segments,
            key=lambda segment: (
                len(query_tokens & text_tokens(segment.text)),
                segment.last_event_id,
            ),
            reverse=True,
        )
        return ranked[:limit]


_ASCII_TOKEN = re.compile(r"[a-z0-9_]+")
_CJK_RUN = re.compile(r"[\u3400-\u9fff]+")
_EVENT_TYPE_WEIGHT = {
    "system": 5,
    "chair": 5,
    "resolution": 5,
    "instruction": 4,
    "vote": 4,
    "phase_switch": 4,
    "set_agenda": 4,
    "motion_switch": 3,
    "note": 3,
    "message": 1,
    "chat": 1,
}


def text_tokens(text: str) -> set[str]:
    """为中英文混合文本产生确定性词项；中文使用二元字组。"""
    normalized = text.lower()
    tokens = set(_ASCII_TOKEN.findall(normalized))
    for run in _CJK_RUN.findall(normalized):
        if len(run) == 1:
            tokens.add(run)
        else:
            tokens.update(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


def _normalize_content(content: str) -> str:
    normalized = " ".join(content.split())
    if not normalized:
        raise ValueError("memory content 不能为空")
    if len(normalized) > 500:
        raise ValueError("memory content 不能超过 500 字符")
    return normalized


def _normalize_importance(importance: int) -> int:
    if importance < 1 or importance > 5:
        raise ValueError(f"importance 须在 1..5,实际为 {importance!r}")
    return importance


def _normalize_source_ids(
    values: list[int] | tuple[int, ...],
) -> tuple[int, ...]:
    result = tuple(sorted(set(values)))
    if any(value < 0 for value in result):
        raise ValueError("source_event_ids 不能包含负数")
    return result


def _truncate(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1]}…"
