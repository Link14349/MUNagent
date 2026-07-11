"""单会场前场状态机(P1 最小版). 见 04§3.

P1 仅: Opening → ModeratedCaucus → Adjourned
- 点名 + 保底轮询(K=会场人数轮无人发言则强制点名)
- 每回合按 clock_rate.per_mod_speech 推进故事时钟
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

Phase = Literal["Opening", "ModeratedCaucus", "UnmoderatedCaucus", "Suspended", "Adjourned"]


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


class VenueStateMachine:
    """单会场状态机(P1 最小版)."""

    def __init__(
        self,
        venue_id: str,
        seat_ids: list[str],
        initial_phase: Phase,
        start_story_time: str,
        per_mod_speech: str = "5m",
        max_speeches: int = 12,
    ) -> None:
        self.venue_id = venue_id
        self.seat_ids = seat_ids
        self.phase: Phase = initial_phase
        self.story_time = start_story_time  # ISO UTC 字符串
        self._story_dt = datetime.fromisoformat(start_story_time)
        self.per_mod_speech_delta = parse_clock_delta(per_mod_speech)
        self.max_speeches = max_speeches
        self.mod_speech_count = 0
        # 保底轮询: 记录连续未发言席位
        self.spoken_this_phase: list[str] = []
        self.unspoken_count = 0

    def advance_clock(self) -> str:
        """按 per_mod_speech 推进故事时钟, 返回新时间(UTC ISO)."""
        self._story_dt = self._story_dt + self.per_mod_speech_delta
        self.story_time = self._story_dt.isoformat()
        return self.story_time

    def transition(self, to: Phase) -> None:
        self.phase = to
        if to == "ModeratedCaucus":
            self.mod_speech_count = 0
            self.spoken_this_phase = []

    def record_speech(self, seat_id: str) -> None:
        self.mod_speech_count += 1
        if seat_id not in self.spoken_this_phase:
            self.spoken_this_phase.append(seat_id)
        self.unspoken_count = 0

    def record_no_speech(self) -> None:
        """连续无人发言计数+1."""
        self.unspoken_count += 1

    @property
    def floor_rotation_due(self) -> bool:
        """保底轮询: 连续 K=会场人数 轮未发言则强制. 见 04§3."""
        return self.unspoken_count >= len(self.seat_ids)

    @property
    def budget_exceeded(self) -> bool:
        return self.mod_speech_count >= self.max_speeches

    def next_for_floor_rotation(self) -> str | None:
        """保底轮询: 选最久未发言的席位."""
        for sid in self.seat_ids:
            if sid not in self.spoken_this_phase:
                return sid
        # 全部发言过, 重置
        self.spoken_this_phase = []
        return self.seat_ids[0] if self.seat_ids else None
