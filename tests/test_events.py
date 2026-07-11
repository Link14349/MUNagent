"""事件模型与总线单元测试."""

from __future__ import annotations

import pytest

from munagent.core.events import (
    Event,
    GOD_VIEWER,
    PRESIDIUM_VIEWERS,
    materialize_visible_to,
)


def _mk(scope: str, visible_to=None, actor="seat:a") -> Event:
    return Event(
        session_id="s1",
        seq=1,
        type="speech",
        actor=actor,
        scope=scope,
        visible_to=visible_to,
        payload={"text": "hi"},
    )


class TestScopeVisibility:
    """6 scope × {代表本人/其他代表/主席团/god} 矩阵. 见 03§4."""

    def test_global_visible_to_all(self) -> None:
        e = _mk("global")
        assert e.is_visible_to("seat:a")
        assert e.is_visible_to("seat:b")
        assert e.is_visible_to("chair")
        assert e.is_visible_to(GOD_VIEWER)

    def test_venue_only_in_venue(self) -> None:
        e = _mk("venue", visible_to=["seat:a", "seat:b"])
        assert e.is_visible_to("seat:a")
        assert e.is_visible_to("seat:b")
        assert not e.is_visible_to("seat:c")
        assert e.is_visible_to("chair")
        assert e.is_visible_to(GOD_VIEWER)

    def test_group_only_in_group(self) -> None:
        e = _mk("group", visible_to=["seat:a", "seat:b"])
        assert e.is_visible_to("seat:a")
        assert not e.is_visible_to("seat:c")

    def test_private_recipients_and_presidium(self) -> None:
        e = _mk("private", visible_to=["seat:a", "chair", "dm"])
        assert e.is_visible_to("seat:a")
        assert not e.is_visible_to("seat:b")
        assert e.is_visible_to("chair")
        assert e.is_visible_to("dm")

    def test_dm_only_presidium_only(self) -> None:
        e = _mk("dm-only")
        assert not e.is_visible_to("seat:a")
        assert e.is_visible_to("chair")
        assert e.is_visible_to("dm")
        assert e.is_visible_to(GOD_VIEWER)

    def test_self_only_actor(self) -> None:
        e = _mk("self", visible_to=["seat:a"], actor="seat:a")
        assert e.is_visible_to("seat:a")
        assert not e.is_visible_to("seat:b")
        # 主席团不可见 self (不读心)
        assert not e.is_visible_to("chair")
        assert not e.is_visible_to("dm")
        # 上帝视角可见
        assert e.is_visible_to(GOD_VIEWER)


class TestMaterializeVisibleTo:
    def test_global_returns_none(self) -> None:
        assert materialize_visible_to("global", actor="seat:a") is None

    def test_dm_only_returns_none(self) -> None:
        assert materialize_visible_to("dm-only", actor="chair") is None

    def test_self_returns_actor(self) -> None:
        assert materialize_visible_to("self", actor="seat:a") == ["seat:a"]

    def test_venue_returns_venue_seats(self) -> None:
        result = materialize_visible_to(
            "venue", actor="seat:a", venue_seats=["seat:a", "seat:b", "seat:c"]
        )
        assert result == ["seat:a", "seat:b", "seat:c"]

    def test_private_includes_presidium(self) -> None:
        result = materialize_visible_to(
            "private", actor="seat:a", private_recipients=["seat:b"]
        )
        assert "seat:b" in result
        assert "chair" in result
        assert "dm" in result
        assert "recorder" in result
