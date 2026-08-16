"""服务终端按 EventList 增量显示事件。"""

from __future__ import annotations

from pathlib import Path

from scenario.scenario import Scenario
from service.console_events import VenueEventConsoleReporter


TEMPLATE = Path(__file__).resolve().parent.parent / "scenario-template"


def test_console_reporter_emits_new_and_updated_events(
    tmp_path: Path,
    venue_engine_runner,
) -> None:
    scenario = Scenario()
    scenario.load(str(TEMPLATE))
    scenario.root_path = tmp_path
    scenario.initialize()
    venue = scenario.venues[0]
    venue_engine_runner.start(venue)
    output: list[str] = []
    reporter = VenueEventConsoleReporter(scenario, output=output.append)

    event = scenario.reps["winston_churchill"].submit_motion_switch(
        "提议转入有主持核心磋商",
        "chaired_core",
    )
    assert reporter.emit_changes() == 1
    assert reporter.emit_changes() == 0

    event.content = "修订：提议立即转入有主持核心磋商"
    event.status = "accepted"
    assert reporter.emit_changes() == 1

    assert output[0].startswith(
        f"[事件] {venue.id}#0 1944-10-09T22:00:00+03:00 "
        "[motion_switch/pending]"
    )
    assert "scope=[" in output[0]
    assert output[1].startswith(
        f"[更新] {venue.id}#0 1944-10-09T22:00:00+03:00 "
        "[motion_switch/accepted]"
    )
    assert "修订：提议立即转入有主持核心磋商" in output[1]
