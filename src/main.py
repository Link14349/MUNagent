"""MUNagent 入口：加载并打印场景包摘要。"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from scenario.scenario import Scenario


def main() -> None:
    root = Path(__file__).resolve().parent.parent / "scenario-template"
    scenario = Scenario()
    scenario.load(str(root))

    print(f"场景: {scenario.title}")
    print(f"时区: {scenario.timezone}")
    print(f"开场时间: {scenario.time}")
    print(f"背景字数: {len(scenario.background)}")
    print(f"场景目标数: {len(scenario.targets)}")
    print(f"会场数: {len(scenario.venues)}")
    print(f"代表数: {len(scenario.representatives)}")
    print(f"外部事件数: {len(scenario.event_pool)}")
    print(f"结束条件数: {len(scenario.end_conditions)}")

    venue = scenario.venues[0]
    print(f"\n会场: {venue.name} ({venue.id})")
    print(f"  主席: {venue.chair}")
    print(f"  席位: {', '.join(venue.seats)}")
    print(f"  议题阶段数: {len(venue.agenda)}")

    print("\n代表:")
    for rep in scenario.representatives:
        print(f"  - {rep.name} ({rep.id}) @ {rep.venue.id if rep.venue else '?'}")

    print("\n外部事件:")
    for event in scenario.event_pool:
        print(f"  - [{event.condition.type}] {event.content[:40]}...")


if __name__ == "__main__":
    main()
