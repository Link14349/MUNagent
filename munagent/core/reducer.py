"""RuntimeState 与事件流折叠(reducer). 见 03§7.

纯函数: apply(state, event) -> state, reduce(events) -> state.
引擎在线维护与续推重建共用 apply.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, Field

from munagent.core.events import Event


class GroupState(BaseModel):
    id: str
    members: list[str] = Field(default_factory=list)
    closed: bool = False
    founder: str = ""


class VoteState(BaseModel):
    directive_id: str = ""
    cast: dict[str, str] = Field(default_factory=dict)


class VenueState(BaseModel):
    id: str
    kind: str = "main"
    phase: str = "Opening"
    interrupted_phase: str | None = None
    present_seats: list[str] = Field(default_factory=list)
    presiding_seat: str | None = None
    agenda: str = ""
    groups: list[GroupState] = Field(default_factory=list)
    unmod_round: int = 0
    mod_speech_count: int = 0
    story_time: str = ""
    active_vote: VoteState | None = None


class RuntimeState(BaseModel):
    session_id: str
    last_seq: int = 0
    venues: dict[str, VenueState] = Field(default_factory=dict)
    directives: dict[str, str] = Field(default_factory=dict)  # id -> status
    backroom_queue: list[str] = Field(default_factory=list)
    pending_interrupts: list[dict] = Field(default_factory=list)
    fired_arcs: list[str] = Field(default_factory=list)
    stats: dict[str, dict] = Field(default_factory=dict)
    session_status: str = "running"


def initial_state(session_id: str) -> RuntimeState:
    return RuntimeState(session_id=session_id)


def apply(state: RuntimeState, e: Event) -> RuntimeState:
    """单事件递推. 纯函数: 不读时钟/不掷随机/不做 IO. 见 03§7."""
    s = state.model_copy(deep=True)
    s.last_seq = e.seq or s.last_seq

    def _venue(venue_id: str) -> VenueState:
        if venue_id not in s.venues:
            s.venues[venue_id] = VenueState(id=venue_id)
        return s.venues[venue_id]

    t = e.type

    if t == "phase_change":
        if e.venue_id:
            v = _venue(e.venue_id)
            v.phase = e.payload.get("to", v.phase)
            if v.phase == "ModeratedCaucus":
                v.mod_speech_count = 0
            elif v.phase == "UnmoderatedCaucus":
                v.unmod_round = 0
                v.groups = []

    elif t == "speech":
        if e.venue_id:
            v = _venue(e.venue_id)
            if v.phase == "ModeratedCaucus":
                v.mod_speech_count += 1

    elif t == "vote_call":
        if e.venue_id:
            v = _venue(e.venue_id)
            v.active_vote = VoteState(directive_id=e.payload.get("directive_id", ""))
            v.interrupted_phase = v.phase

    elif t == "vote_cast":
        if e.venue_id:
            v = _venue(e.venue_id)
            if v.active_vote:
                v.active_vote.cast[e.actor.replace("seat:", "")] = e.payload.get("choice", "abstain")

    elif t == "vote_result":
        if e.venue_id:
            v = _venue(e.venue_id)
            v.active_vote = None
            d_id = e.payload.get("directive_id", "")
            result = e.payload.get("result", "")
            if d_id:
                s.directives[d_id] = result
                if result == "passed":
                    s.backroom_queue.append(d_id)

    elif t == "directive_submitted":
        d_id = e.payload.get("directive_id", "")
        kind = e.payload.get("kind", "")
        s.directives[d_id] = "submitted"
        if kind in ("personal", "crisis_note"):
            s.backroom_queue.append(d_id)

    elif t == "directive_status":
        d_id = e.payload.get("directive_id", "")
        status = e.payload.get("status", "")
        if d_id:
            s.directives[d_id] = status
            if status == "resolved" and d_id in s.backroom_queue:
                s.backroom_queue.remove(d_id)

    elif t == "adjudication":
        for change in e.payload.get("stat_changes", []):
            entity = change.get("entity", "")
            field = change.get("field", "")
            to = change.get("to", "")
            if entity:
                s.stats.setdefault(entity, {})[field] = to

    elif t == "presiding_change":
        if e.venue_id:
            v = _venue(e.venue_id)
            v.presiding_seat = e.payload.get("to_seat")

    elif t == "clock_advance":
        if e.venue_id:
            v = _venue(e.venue_id)
            v.story_time = e.payload.get("to", v.story_time)

    elif t == "session_control":
        action = e.payload.get("action", "")
        if action in ("end", "pause"):
            s.session_status = action + "ed" if action == "end" else "paused"

    # speech_thought / motion / motion_ruling / crisis_update /
    # group_* / summary_written: 无状态变更或由后续事件承载
    return s


def reduce(events: Iterable[Event], session_id: str = "") -> RuntimeState:
    """全量折叠. 见 03§7."""
    state = initial_state(session_id)
    for e in events:
        state = apply(state, e)
    return state
