"""Reducer 确定性测试. 见 03§7."""

from __future__ import annotations

from munagent.core.events import Event
from munagent.core.reducer import apply, initial_state, reduce


def _mk_event(seq: int, etype: str, **kwargs) -> Event:
    payload = kwargs.pop("payload", {})
    return Event(
        session_id="s1",
        seq=seq,
        type=etype,
        actor=kwargs.pop("actor", "chair"),
        venue_id=kwargs.pop("venue_id", "v1"),
        scope=kwargs.pop("scope", "venue"),
        payload=payload,
        **kwargs,
    )


def test_reduce_empty() -> None:
    state = reduce([], "s1")
    assert state.session_id == "s1"
    assert state.last_seq == 0
    assert state.venues == {}


def test_phase_change_updates_venue() -> None:
    from munagent.core.reducer import VenueState
    state = initial_state("s1")
    state.venues["v1"] = VenueState(id="v1")
    state = apply(state, _mk_event(1, "phase_change", payload={"from": "Opening", "to": "ModeratedCaucus"}))
    assert state.venues["v1"].phase == "ModeratedCaucus"


def test_speech_increments_mod_count() -> None:
    from munagent.core.reducer import VenueState
    state = initial_state("s1")
    state.venues["v1"] = VenueState(id="v1", phase="ModeratedCaucus")
    state = apply(state, _mk_event(1, "speech", actor="seat:a"))
    state = apply(state, _mk_event(2, "speech", actor="seat:b"))
    assert state.venues["v1"].mod_speech_count == 2


def test_directive_submitted_personal_enters_queue() -> None:
    state = initial_state("s1")
    state = apply(state, _mk_event(1, "directive_submitted", actor="seat:a", scope="private",
                                   payload={"directive_id": "d1", "kind": "personal"}))
    assert state.directives["d1"] == "submitted"
    assert "d1" in state.backroom_queue


def test_directive_resolved_leaves_queue() -> None:
    state = initial_state("s1")
    state = apply(state, _mk_event(1, "directive_submitted", actor="seat:a", scope="private",
                                   payload={"directive_id": "d1", "kind": "personal"}))
    state = apply(state, _mk_event(2, "directive_status", actor="system", scope="private",
                                   payload={"directive_id": "d1", "status": "resolved"}))
    assert "d1" not in state.backroom_queue
    assert state.directives["d1"] == "resolved"


def test_reduce_twice_equal() -> None:
    """同一事件流 reduce 两次, 结果结构级相等. P2 验收项."""
    events = [
        _mk_event(1, "phase_change", payload={"from": "Opening", "to": "ModeratedCaucus"}),
        _mk_event(2, "speech", actor="seat:a"),
        _mk_event(3, "speech", actor="seat:b"),
        _mk_event(4, "directive_submitted", actor="seat:a", scope="private",
                  payload={"directive_id": "d1", "kind": "personal"}),
    ]
    s1 = reduce(events, "s1")
    s2 = reduce(events, "s1")
    assert s1.model_dump() == s2.model_dump()


def test_apply_is_pure_function() -> None:
    """apply 不修改输入 state."""
    from munagent.core.reducer import VenueState
    state = initial_state("s1")
    state.venues["v1"] = VenueState(id="v1", phase="ModeratedCaucus", mod_speech_count=0)
    original = state.model_copy(deep=True)
    _ = apply(state, _mk_event(1, "speech", actor="seat:a"))
    assert state.model_dump() == original.model_dump()  # 输入未被修改


def test_presiding_change_updates_seat() -> None:
    from munagent.core.reducer import VenueState
    state = initial_state("s1")
    state.venues["v1"] = VenueState(id="v1", presiding_seat="seat:a")
    state = apply(state, _mk_event(1, "presiding_change",
                                   payload={"from_seat": "seat:a", "to_seat": "seat:b", "cause": "投票"}))
    assert state.venues["v1"].presiding_seat == "seat:b"


def test_vote_result_passed_enters_queue() -> None:
    from munagent.core.reducer import VenueState
    state = initial_state("s1")
    state.venues["v1"] = VenueState(id="v1", phase="Voting")
    state = apply(state, _mk_event(1, "vote_result", actor="system",
                                   payload={"directive_id": "d1", "result": "passed"}))
    assert state.directives["d1"] == "passed"
    assert "d1" in state.backroom_queue
