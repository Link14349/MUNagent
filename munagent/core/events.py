"""事件模型、可见性与事件总线. 见 docs/design/03-event-model.md."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Scope = Literal["global", "venue", "group", "private", "dm-only", "self"]

# 主席团角色标识, 可见除 self 外的一切
PRESIDIUM_VIEWERS = frozenset({"chair", "dm", "recorder"})
GOD_VIEWER = "god"


class Event(BaseModel):
    """系统中一切行为的统一记录单位. 见 03§2."""

    id: int | None = None  # 全局自增(SQLite rowid), 内存中为 None
    session_id: str
    seq: int | None = None  # 会话内严格递增序号; stage 时补全
    story_time: str | None = None  # 故事内时间(ISO UTC)
    real_time: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    type: str
    actor: str  # seat:<id> | chair | dm | recorder | system | human
    venue_id: str | None = None
    group_id: str | None = None
    scope: Scope
    visible_to: list[str] | None = None  # scope∈{venue,group,private,self}时物化
    payload: dict[str, Any] = Field(default_factory=dict)
    rng: dict[str, Any] | None = None  # 判定类事件: {seed, rolls}

    def is_visible_to(self, viewer: str) -> bool:
        """单事件可见性判定(纯函数, 与 EventBus.query 共用). 见 03§4."""
        if viewer == GOD_VIEWER:
            return True
        if viewer in PRESIDIUM_VIEWERS:
            # 主席团可见除 self 外的一切
            return self.scope != "self"
        if self.scope == "global":
            return True
        if self.scope == "dm-only":
            return False  # 仅主席团/上帝, 上面已处理
        # venue / group / private / self: 看 viewer 是否在物化名单
        if self.visible_to is None:
            return False
        return viewer in self.visible_to


def canonical_viewer(v: str) -> str:
    """归一化为 canonical viewer 形式: 裸席位 id -> `seat:<id>`.

    visible_to 与 query 的 viewer 必须同形, 否则可见性判定静默失败(全盲或泄漏).
    主席团角色(chair/dm/recorder)、god、已带前缀的名字原样保留.
    """
    if v in PRESIDIUM_VIEWERS or v == GOD_VIEWER or ":" in v:
        return v
    return f"seat:{v}"


def materialize_visible_to(
    scope: Scope,
    *,
    actor: str,
    venue_seats: list[str] | None = None,
    group_members: list[str] | None = None,
    private_recipients: list[str] | None = None,
) -> list[str] | None:
    """根据 scope 与上下文计算 visible_to. 见 03§4.

    - global / dm-only: 返回 None(无需物化)
    - venue: 发出时刻该会场在场席位
    - group: 发出时刻组内成员
    - private: 显式指定(如危机笔记收件人 + 主席团)
    - self: 仅行为者本席位

    一切名单成员经 canonical_viewer 归一化(裸席位 id 自动加 `seat:` 前缀).
    """
    if scope in ("global", "dm-only"):
        return None
    if scope == "self":
        return [canonical_viewer(actor)]
    if scope == "venue":
        return [canonical_viewer(s) for s in (venue_seats or [])]
    if scope == "group":
        return [canonical_viewer(s) for s in (group_members or [])]
    if scope == "private":
        recipients = [canonical_viewer(s) for s in (private_recipients or [])]
        # 主席团始终可见 private
        for p in PRESIDIUM_VIEWERS:
            if p not in recipients:
                recipients.append(p)
        return recipients
    return None


def event_to_row(e: Event) -> tuple:
    """Event -> SQLite events 表行元组."""
    return (
        e.id,
        e.session_id,
        e.seq,
        e.story_time,
        e.real_time,
        e.type,
        e.actor,
        e.venue_id,
        e.group_id,
        e.scope,
        json.dumps(e.visible_to, ensure_ascii=False) if e.visible_to is not None else None,
        json.dumps(e.payload, ensure_ascii=False),
        json.dumps(e.rng, ensure_ascii=False) if e.rng is not None else None,
    )


def row_to_event(row: tuple) -> Event:
    """SQLite events 表行元组 -> Event."""
    (
        eid,
        session_id,
        seq,
        story_time,
        real_time,
        etype,
        actor,
        venue_id,
        group_id,
        scope,
        visible_to_json,
        payload_json,
        rng_json,
    ) = row
    return Event(
        id=eid,
        session_id=session_id,
        seq=seq,
        story_time=story_time,
        real_time=real_time,
        type=etype,
        actor=actor,
        venue_id=venue_id,
        group_id=group_id,
        scope=scope,
        visible_to=json.loads(visible_to_json) if visible_to_json else None,
        payload=json.loads(payload_json),
        rng=json.loads(rng_json) if rng_json else None,
    )


Subscriber = Callable[[Event], Awaitable[None] | None]
