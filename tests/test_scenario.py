"""场景包加载测试."""

from __future__ import annotations

from pathlib import Path

import pytest

from munagent.core.scenario import load_scenario

SCENARIO_DIR = Path(__file__).parent.parent / "scenarios" / "cabinet-crisis"


def test_load_cabinet_crisis() -> None:
    sc = load_scenario(SCENARIO_DIR)
    assert sc.manifest.id == "cabinet-crisis"
    assert sc.manifest.title == "三人内阁危机"
    assert "Z" not in sc.manifest.start_story_time  # 带 +08:00
    assert "+" in sc.manifest.start_story_time

    assert len(sc.venues) == 1
    venue = sc.venues[0]
    assert venue.id == "cabinet"
    assert venue.timezone == "Asia/Shanghai"
    assert len(venue.seats) == 3
    assert venue.decision_rule.pass_threshold == "majority"

    assert set(sc.seats.keys()) == {"premier", "defense_minister", "foreign_minister"}
    premier = sc.seats["premier"]
    assert premier.public.faction == "温和派"
    assert premier.persona.honesty == 0.6
    assert len(premier.portfolio_powers) == 2

    defense = sc.seats["defense_minister"]
    assert defense.persona.honesty == 0.3

    assert len(sc.crisis_arcs.main_arc) == 1
    arc = sc.crisis_arcs.main_arc[0]
    assert arc.id == "border_skirmish"
    assert arc.trigger.type == "story_time"

    assert sc.stats.mode == "tags"
    assert sc.stats.visibility == "faction"


def test_stats_for_seat_faction_visibility() -> None:
    sc = load_scenario(SCENARIO_DIR)
    # 温和派总理能看到温和派条目, 看不到强硬派条目
    premier_stats = sc.stats_for_seat("premier")
    stat_ids = [e.id for e in premier_stats]
    assert "cabinet_stability" in stat_ids
    assert "military_readiness" not in stat_ids

    # 强硬派国防部长能看到强硬派条目
    defense_stats = sc.stats_for_seat("defense_minister")
    stat_ids = [e.id for e in defense_stats]
    assert "military_readiness" in stat_ids
    assert "cabinet_stability" not in stat_ids


def test_seats_of_venue() -> None:
    sc = load_scenario(SCENARIO_DIR)
    seats = sc.seats_of("cabinet")
    assert len(seats) == 3
    assert {s.id for s in seats} == {"premier", "defense_minister", "foreign_minister"}


def test_invalid_tz_raises(tmp_path: Path) -> None:
    import yaml

    (tmp_path / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "bad",
                "title": "bad",
                "start_story_time": "2026-03-15T09:00:00",  # 裸时间, 无时区
            }
        )
    )
    (tmp_path / "venues.yaml").write_text(yaml.safe_dump({"venues": []}))
    with pytest.raises(Exception, match="时区"):
        load_scenario(tmp_path)


def test_presiding_seat_is_premier() -> None:
    """内阁危机场景设了 presiding_seat: premier."""
    sc = load_scenario(SCENARIO_DIR)
    assert sc.venues[0].presiding_seat == "premier"


def test_presiding_seat_loaded(tmp_path: Path) -> None:
    """设了 presiding_seat 时能读出来."""
    import shutil
    import yaml

    # 复制内阁场景, 加上 presiding_seat
    target = tmp_path / "cabinet"
    shutil.copytree(SCENARIO_DIR, target)
    venues = yaml.safe_load((target / "venues.yaml").read_text())
    venues["venues"][0]["presiding_seat"] = "premier"
    (target / "venues.yaml").write_text(yaml.safe_dump(venues))

    sc = load_scenario(target)
    assert sc.venues[0].presiding_seat == "premier"


def test_presiding_seat_must_be_in_seats(tmp_path: Path) -> None:
    """presiding_seat 必须在 seats 列表中."""
    import shutil
    import yaml

    target = tmp_path / "cabinet"
    shutil.copytree(SCENARIO_DIR, target)
    venues = yaml.safe_load((target / "venues.yaml").read_text())
    venues["venues"][0]["presiding_seat"] = "nonexistent_seat"
    (target / "venues.yaml").write_text(yaml.safe_dump(venues))

    with pytest.raises(Exception, match="不在会场席位列表中"):
        load_scenario(target)


def test_build_delegate_g_global_includes_background_and_seats() -> None:
    from munagent.agents.delegate import build_delegate_g_global

    sc = load_scenario(SCENARIO_DIR)
    g = build_delegate_g_global(sc, "cabinet")
    assert "背景文书" in g
    assert "宪政危机" in g  # background.md 全文
    assert "内阁会议室" in g
    assert "总理" in g and "国防部长" in g and "外交部长" in g
    assert "召集内阁会议并设定议程" in g
    assert "本会场主持席" in g
    assert "<你的秘密信息>" not in g  # 秘密目标只在 L1

