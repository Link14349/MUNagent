"""EventBus stage/commit/rollback 单元测试."""

from __future__ import annotations

import pytest

from munagent.core.bus import EventBus
from munagent.core.events import Event


@pytest.fixture
async def bus(tmp_path):
    db = tmp_path / "test.db"
    b = EventBus(str(db), "s1")
    await b.init_db()
    await b.create_session("scenario-x", master_seed=42)
    yield b
    await b.close()


@pytest.mark.asyncio
async def test_stage_and_commit(bus: EventBus) -> None:
    e1 = bus.stage(
        Event(
            session_id="s1",
            type="phase_change",
            actor="chair",
            venue_id="v1",
            scope="venue",
            payload={"from": "Opening", "to": "ModeratedCaucus", "reason": "开始"},
        ),
        venue_seats=["seat:a", "seat:b"],
    )
    assert e1.seq == 1
    assert e1.visible_to == ["seat:a", "seat:b"]

    committed = await bus.commit_step()
    assert len(committed) == 1
    assert bus.next_seq == 2


@pytest.mark.asyncio
async def test_rollback_discards_buffer(bus: EventBus) -> None:
    bus.stage(
        Event(
            session_id="s1",
            type="speech",
            actor="seat:a",
            venue_id="v1",
            scope="venue",
            payload={"text": "test"},
        ),
        venue_seats=["seat:a"],
    )
    bus.rollback_step()
    assert bus.next_seq == 1  # seq 回到 1


@pytest.mark.asyncio
async def test_query_filters_by_viewer(bus: EventBus) -> None:
    # venue 事件
    bus.stage(
        Event(
            session_id="s1",
            type="speech",
            actor="seat:a",
            venue_id="v1",
            scope="venue",
            payload={"text": "hello"},
        ),
        venue_seats=["seat:a", "seat:b"],
    )
    # self 事件(内心动机)
    bus.stage(
        Event(
            session_id="s1",
            type="speech_thought",
            actor="seat:a",
            venue_id="v1",
            scope="self",
            payload={"thought": "我在盘算..."},
        ),
    )
    await bus.commit_step()

    # seat:a 看得到两条
    a_events = await bus.query("seat:a")
    assert len(a_events) == 2

    # seat:b 看不到 self
    b_events = await bus.query("seat:b")
    assert len(b_events) == 1
    assert b_events[0].type == "speech"

    # 主席团看不到 self
    chair_events = await bus.query("chair")
    assert len(chair_events) == 1

    # god 看全部
    god_events = await bus.query("god")
    assert len(god_events) == 2


@pytest.mark.asyncio
async def test_query_includes_buffer(bus: EventBus) -> None:
    """query 应同时查询已 commit 和当前缓冲."""
    bus.stage(
        Event(
            session_id="s1",
            type="speech",
            actor="seat:a",
            venue_id="v1",
            scope="venue",
            payload={"text": "first"},
        ),
        venue_seats=["seat:a"],
    )
    await bus.commit_step()

    # 第二个还在缓冲里
    bus.stage(
        Event(
            session_id="s1",
            type="speech",
            actor="seat:a",
            venue_id="v1",
            scope="venue",
            payload={"text": "second"},
        ),
        venue_seats=["seat:a"],
    )

    events = await bus.query("seat:a")
    assert len(events) == 2
    assert events[0].payload["text"] == "first"
    assert events[1].payload["text"] == "second"


@pytest.mark.asyncio
async def test_group_query_keeps_venue_events(tmp_path) -> None:
    """group 过滤只排除其他组的事件, venue/global 事件仍可见(Unmod 中要能看到 Crisis Update)."""
    bus = EventBus(str(tmp_path / "t.db"), "s1")
    await bus.init_db()
    bus.stage(
        Event(
            session_id="s1", type="crisis_update", actor="chair",
            venue_id="v1", scope="venue", payload={"text": "危机!"},
        ),
        venue_seats=["seat:a", "seat:b"],
    )
    bus.stage(
        Event(
            session_id="s1", type="speech", actor="seat:a",
            venue_id="v1", group_id="g1", scope="group", payload={"text": "组内话"},
        ),
        group_members=["seat:a"],
    )
    bus.stage(
        Event(
            session_id="s1", type="speech", actor="seat:b",
            venue_id="v1", group_id="g2", scope="group", payload={"text": "别组的话"},
        ),
        group_members=["seat:b"],
    )
    await bus.commit_step()

    events = await bus.query("seat:a", venue="v1", group="g1")
    types = [e.type for e in events]
    assert "crisis_update" in types  # venue 事件保留
    assert any(e.group_id == "g1" for e in events)  # 本组事件保留
    assert not any(e.group_id == "g2" for e in events)  # 他组事件排除
    await bus.close()
