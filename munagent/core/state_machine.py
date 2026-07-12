"""单会场前场状态机(完整版). 见 04§3.

状态: Opening / ModeratedCaucus / UnmoderatedCaucus / Voting / Suspended / Adjourned
- Mod: 点名 + 保底轮询 + 预算
- Unmod: 小轮 + 屏障
- Voting: 子流程(冻结前场, 完毕返回原阶段)
- 转移经校验, 非法转移拒绝
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

Phase = Literal[
    "Opening",
    "ModeratedCaucus",
    "UnmoderatedCaucus",
    "Voting",
    "Suspended",
    "Adjourned",
]

# 合法转移表(04§3)
_TRANSITIONS: dict[Phase, set[Phase]] = {
    "Opening": {"ModeratedCaucus"},
    "ModeratedCaucus": {"UnmoderatedCaucus", "Voting", "Suspended", "Adjourned"},
    "UnmoderatedCaucus": {"ModeratedCaucus", "Voting", "Suspended", "Adjourned"},
    "Voting": {"ModeratedCaucus", "UnmoderatedCaucus"},  # 返回被打断的阶段
    "Suspended": {"ModeratedCaucus", "UnmoderatedCaucus"},  # 归还后恢复
    "Adjourned": set(),
}


def parse_clock_delta(s: str) -> timedelta:
    """解析 '5m' / '15m' / '1h' 为 timedelta."""
    s = s.strip()
    if s.endswith("m"):
        return timedelta(minutes=int(s[:-1]))
    if s.endswith("h"):
        return timedelta(hours=int(s[:-1]))
    if s.endswith("s"):
        return timedelta(seconds=int(s[:-1]))
    return timedelta(minutes=int(s))


class GroupState:
    """Unmod 分组状态."""

    def __init__(self, id: str, members: list[str], closed: bool = False, founder: str = "") -> None:
        self.id = id
        self.members = list(members)
        self.closed = closed
        self.founder = founder


class VenueStateMachine:
    """单会场前场状态机(完整版). 见 04§3."""

    def __init__(
        self,
        venue_id: str,
        seat_ids: list[str],
        initial_phase: Phase,
        start_story_time: str,
        *,
        per_mod_speech: str = "5m",
        per_unmod_round: str = "15m",
        max_speeches: int = 12,
        unmod_rounds: int = 4,
        presiding_seat: str | None = None,
    ) -> None:
        self.venue_id = venue_id
        self.seat_ids = seat_ids
        # 席位状态: active(在席) | suspended(停职) | removed(除名/死亡/被捕)
        # 非 active 席位不参与点名/轮询/分组/投票, 见 04§3
        self.seat_status: dict[str, str] = {sid: "active" for sid in seat_ids}
        self.phase: Phase = initial_phase
        self.presiding_seat = presiding_seat
        self.story_time = start_story_time
        self._story_dt = datetime.fromisoformat(start_story_time)
        self.per_mod_speech_delta = parse_clock_delta(per_mod_speech)
        self.per_unmod_round_delta = parse_clock_delta(per_unmod_round)
        self.max_speeches = max_speeches
        self.unmod_rounds = unmod_rounds

        # Mod 阶段计数
        self.mod_speech_count = 0
        self.spoken_this_phase: list[str] = []
        self.unspoken_count = 0

        # Unmod 阶段状态
        self.groups: list[GroupState] = []
        self.unmod_round_count = 0

        # Voting 子流程状态
        self.interrupted_phase: Phase | None = None  # Voting 结束后返回
        self.active_vote_directive_id: str | None = None
        self.vote_casts: dict[str, str] = {}  # seat -> aye|nay|abstain
        self.vote_order: list[str] = []  # 投票顺序
        self.vote_index = 0  # 当前等谁投

    @property
    def active_seat_ids(self) -> list[str]:
        return [s for s in self.seat_ids if self.seat_status.get(s) == "active"]

    def set_seat_status(self, seat_id: str, status: str) -> None:
        """更新席位状态; 主持席失去 active 时主持权自动回落中立主席."""
        if seat_id not in self.seat_status:
            raise ValueError(f"未知席位: {seat_id}")
        if status not in ("active", "suspended", "removed"):
            raise ValueError(f"非法席位状态: {status}")
        self.seat_status[seat_id] = status
        if status != "active" and self.presiding_seat == seat_id:
            self.presiding_seat = None

    def can_transition(self, to: Phase) -> bool:
        return to in _TRANSITIONS.get(self.phase, set())

    def transition(self, to: Phase, *, interrupted_from: Phase | None = None) -> None:
        if not self.can_transition(to):
            raise ValueError(f"非法状态转移: {self.phase} → {to}")
        if to == "Voting":
            self.interrupted_phase = interrupted_from or self.phase
        self.phase = to
        if to == "ModeratedCaucus":
            self.mod_speech_count = 0
            self.spoken_this_phase = []
            self.unspoken_count = 0
        elif to == "UnmoderatedCaucus":
            self.unmod_round_count = 0
            self.groups = []
        elif to == "Voting":
            self.vote_casts = {}
            self.vote_index = 0
        # Voting 结束后返回时, 恢复计数器不变(继续被打断的阶段)

    def advance_clock(self, *, unmod: bool = False) -> str:
        delta = self.per_unmod_round_delta if unmod else self.per_mod_speech_delta
        self._story_dt = self._story_dt + delta
        self.story_time = self._story_dt.isoformat()
        return self.story_time

    def advance_clock_to(self, target: str) -> str:
        """显式跳时(clock_advance 事件用)."""
        self._story_dt = datetime.fromisoformat(target)
        self.story_time = self._story_dt.isoformat()
        return self.story_time

    # --- Mod 阶段 ---
    def record_speech(self, seat_id: str) -> None:
        self.mod_speech_count += 1
        if seat_id not in self.spoken_this_phase:
            self.spoken_this_phase.append(seat_id)
        self.unspoken_count = 0

    def record_no_speech(self) -> None:
        self.unspoken_count += 1

    @property
    def floor_rotation_due(self) -> bool:
        return self.unspoken_count >= len(self.active_seat_ids)

    @property
    def budget_exceeded(self) -> bool:
        return self.mod_speech_count >= self.max_speeches

    def next_for_floor_rotation(self) -> str | None:
        active = self.active_seat_ids
        for sid in active:
            if sid not in self.spoken_this_phase:
                return sid
        self.spoken_this_phase = []
        return active[0] if active else None

    # --- Unmod 阶段 ---
    def init_groups(self, groups: list[GroupState]) -> None:
        self.groups = groups
        self.unmod_round_count = 0

    def next_unmod_round(self) -> int:
        self.unmod_round_count += 1
        return self.unmod_round_count

    @property
    def unmod_finished(self) -> bool:
        return self.unmod_round_count >= self.unmod_rounds

    # --- Voting 子流程 ---
    def start_vote(self, directive_id: str, vote_order: list[str]) -> None:
        self.active_vote_directive_id = directive_id
        self.vote_order = list(vote_order)
        self.vote_casts = {}
        self.vote_index = 0

    def next_voter(self) -> str | None:
        if self.vote_index >= len(self.vote_order):
            return None
        seat = self.vote_order[self.vote_index]
        self.vote_index += 1
        return seat

    def record_vote(self, seat: str, choice: str) -> None:
        self.vote_casts[seat] = choice

    @property
    def voting_finished(self) -> bool:
        return self.vote_index >= len(self.vote_order)

    def tally_votes(
        self, pass_threshold: str, veto_seats: list[str]
    ) -> tuple[str, dict[str, int]]:
        """计票(纯程序). 见 04§3 计票规则明细.

        返回 (result, tally_dict).
        result: passed | rejected
        tally_dict: {aye: N, nay: N, abstain: N}
        """
        tally = {"aye": 0, "nay": 0, "abstain": 0}
        for choice in self.vote_casts.values():
            if choice in tally:
                tally[choice] += 1

        # veto 检查: veto 席位投 nay → 直接否决
        for vseat in veto_seats:
            if self.vote_casts.get(vseat) == "nay":
                return "rejected", tally

        voted = tally["aye"] + tally["nay"]  # 弃权不计入分母
        if voted == 0:
            return "rejected", tally

        if pass_threshold == "majority":
            passed = tally["aye"] * 2 > voted
        elif pass_threshold == "two_thirds":
            passed = tally["aye"] * 3 >= voted * 2
        elif pass_threshold == "unanimous":
            passed = tally["nay"] == 0
        else:
            passed = tally["aye"] * 2 > voted

        return ("passed" if passed else "rejected"), tally

    def end_vote(self) -> Phase:
        """结束投票, 返回要恢复的阶段."""
        result_phase = self.interrupted_phase or "ModeratedCaucus"
        self.active_vote_directive_id = None
        self.vote_casts = {}
        self.vote_order = []
        self.vote_index = 0
        self.interrupted_phase = None
        return result_phase
