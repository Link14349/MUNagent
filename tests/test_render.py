"""事件渲染器 golden 测试(字节级确定). 见 11§4."""

from __future__ import annotations

from munagent.core.events import Event
from munagent.core.render import render


def _speech_event() -> Event:
    return Event(
        id=1,
        session_id="s1",
        seq=5,
        story_time="1962-10-16T13:00:00Z",
        real_time="2026-07-12T00:00:00Z",
        type="speech",
        actor="seat:gromyko",
        venue_id="politburo",
        scope="venue",
        visible_to=["seat:khrushchev", "seat:gromyko", "seat:malinovsky"],
        payload={"text": "建议通过外交渠道接触美方."},
    )


SPEECH_GOLDEN = (
    "[1962-10-16T13:00:00Z] "
    "seat:gromyko发言: 建议通过外交渠道接触美方."
)


def test_speech_render_matches_golden() -> None:
    assert render(_speech_event()) == SPEECH_GOLDEN


def test_render_is_deterministic() -> None:
    """同一事件渲染两次, 字节级相同."""
    e = _speech_event()
    assert render(e) == render(e)


def test_phase_change_render() -> None:
    e = Event(
        session_id="s1",
        seq=1,
        story_time="1962-10-16T09:00:00Z",
        type="phase_change",
        actor="chair",
        venue_id="politburo",
        scope="venue",
        visible_to=["seat:a"],
        payload={"from": "Opening", "to": "ModeratedCaucus", "reason": "会议开始"},
    )
    assert "Opening → ModeratedCaucus" in render(e)
    assert "会议开始" in render(e)


def test_adjudication_render() -> None:
    e = Event(
        session_id="s1",
        seq=10,
        story_time="1962-10-16T14:00:00Z",
        type="adjudication",
        actor="dm",
        scope="dm-only",
        payload={
            "directive_id": "d1",
            "probability_tier": 70,
            "roll": 45,
            "outcome": "成功",
        },
    )
    r = render(e)
    assert "70%" in r
    assert "45" in r
    assert "成功" in r


def test_presiding_change_render() -> None:
    e = Event(
        session_id="s1",
        seq=20,
        story_time="1962-10-16T15:00:00Z",
        type="presiding_change",
        actor="chair",
        venue_id="politburo",
        scope="venue",
        visible_to=["seat:a"],
        payload={"from_seat": "seat:khrushchev", "to_seat": "seat:mikoyan", "cause": "投票罢免"},
    )
    r = render(e)
    assert "seat:khrushchev" in r
    assert "seat:mikoyan" in r
    assert "投票罢免" in r


def test_motion_ruling_render() -> None:
    e = Event(
        session_id="s1",
        seq=8,
        story_time="1962-10-16T10:00:00Z",
        type="motion_ruling",
        actor="seat:khrushchev",
        venue_id="politburo",
        scope="venue",
        visible_to=["seat:a"],
        payload={"motion_seq": 7, "ruling": "reject", "reason": "时机不成熟"},
    )
    r = render(e)
    assert "reject" in r
    assert "7" in r
    assert "时机不成熟" in r
