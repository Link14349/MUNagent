from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.simulator import Simulator
    from scenario.venue import Venue


class VenueEngine:
    """单个会场的推进循环;由 ``Simulator`` 在独立线程中调用 ``run``."""

    simulator: Simulator
    venue: Venue

    def __init__(self, simulator: Simulator, venue: Venue) -> None:
        self.simulator = simulator
        self.venue = venue

    def run(self) -> None:
        """会场主循环(当前为空实现,由后续里程碑填充)."""
        return
