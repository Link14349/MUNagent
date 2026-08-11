"""venue.chair 映射形(rep + powers)的加载与校验."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from scenario.load import _parse_chair, _parse_chair_power
from scenario.scenario import Scenario
from scenario.venue import CHAIR_POWER

TEMPLATE = Path(__file__).resolve().parent.parent / "scenario-template"

CHURCHILL = "winston_churchill"


def test_parse_chair_none_and_full_powers() -> None:
    chair_id, powers = _parse_chair(
        {
            "rep": "none",
            "powers": {
                "decide_resolution": False,
                "decide_switch_phase": False,
            },
        },
        field="chair",
    )
    assert chair_id is None
    assert powers == {
        CHAIR_POWER.DECIDE_RESOLUTION: False,
        CHAIR_POWER.DECIDE_SWITCH_PHASE: False,
    }


def test_parse_chair_rep_and_enabled_powers() -> None:
    chair_id, powers = _parse_chair(
        {
            "rep": CHURCHILL,
            "powers": {
                "decide_resolution": True,
                "decide_switch_phase": True,
            },
        },
        field="chair",
    )
    assert chair_id == CHURCHILL
    assert powers[CHAIR_POWER.DECIDE_RESOLUTION] is True
    assert powers[CHAIR_POWER.DECIDE_SWITCH_PHASE] is True


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        ("none", "须为对象"),
        ([{"rep": "none", "powers": {}}], "须为对象"),
        ({"rep": "none"}, "缺少必需字段"),
        ({"powers": {"decide_resolution": False}}, "缺少必需字段"),
    ],
)
def test_parse_chair_rejects_bad_shape(raw: object, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        _parse_chair(raw, field="chair")


def test_parse_chair_power_rejects_unknown_missing_and_non_bool() -> None:
    with pytest.raises(ValueError, match="不是合法主席权力"):
        _parse_chair_power(
            {
                "decide_resolution": False,
                "decide_switch_phase": False,
                "decide_everything": True,
            },
            field="chair.powers",
        )
    with pytest.raises(ValueError, match="必须声明全部主席权力"):
        _parse_chair_power(
            {"decide_resolution": True},
            field="chair.powers",
        )
    with pytest.raises(ValueError, match="须为布尔值"):
        _parse_chair_power(
            {
                "decide_resolution": "yes",
                "decide_switch_phase": False,
            },
            field="chair.powers",
        )


def _load_mutated_venue(tmp_path: Path, chair: dict) -> Scenario:
    root = tmp_path / "scenario"
    shutil.copytree(TEMPLATE, root)
    venue_path = root / "venues" / "main.yaml"
    data = yaml.safe_load(venue_path.read_text(encoding="utf-8"))
    data["chair"] = chair
    venue_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    scenario = Scenario()
    scenario.load(str(root))
    return scenario


def test_load_template_chair_mapping(tmp_path: Path) -> None:
    scenario = Scenario()
    scenario.load(str(TEMPLATE))
    venue = scenario.venues[0]
    assert venue.chair is None
    assert venue.chair_power == {
        CHAIR_POWER.DECIDE_RESOLUTION: False,
        CHAIR_POWER.DECIDE_SWITCH_PHASE: False,
    }
    assert all(not rep.is_chair for rep in scenario.representatives)


def test_load_chair_rep_with_powers(tmp_path: Path) -> None:
    scenario = _load_mutated_venue(
        tmp_path,
        {
            "rep": CHURCHILL,
            "powers": {
                "decide_resolution": True,
                "decide_switch_phase": False,
            },
        },
    )
    venue = scenario.venues[0]
    assert venue.chair == CHURCHILL
    assert venue.chair_power[CHAIR_POWER.DECIDE_RESOLUTION] is True
    assert venue.chair_power[CHAIR_POWER.DECIDE_SWITCH_PHASE] is False
    assert scenario.reps[CHURCHILL].is_chair is True
    assert all(
        (rep.id == CHURCHILL) is rep.is_chair for rep in scenario.representatives
    )


def test_load_rejects_legacy_string_chair(tmp_path: Path) -> None:
    root = tmp_path / "scenario"
    shutil.copytree(TEMPLATE, root)
    venue_path = root / "venues" / "main.yaml"
    data = yaml.safe_load(venue_path.read_text(encoding="utf-8"))
    data["chair"] = "none"
    venue_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    scenario = Scenario()
    with pytest.raises(ValueError, match="须为对象"):
        scenario.load(str(root))
