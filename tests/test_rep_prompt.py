"""代表首条 system prompt 构造测试。"""

from pathlib import Path

import pytest

from agent.rep_prompt import build_representative_system_prompt
from scenario.representative import Representative
from scenario.scenario import Scenario

TEMPLATE = Path(__file__).resolve().parent.parent / "scenario-template"


def test_prompt_contains_scenario_and_complete_role_card() -> None:
    scenario = Scenario()
    scenario.load(str(TEMPLATE))
    rep = scenario.reps["winston_churchill"]

    prompt = build_representative_system_prompt(rep)

    assert scenario.title in prompt
    assert scenario.description in prompt
    assert scenario.background in prompt
    assert rep.name in prompt
    assert rep.position in prompt
    assert all(item in prompt for item in rep.public_target)
    assert all(item.objective in prompt for item in rep.private_target)
    assert all(item in prompt for item in rep.private_red_lines)
    assert all(item in prompt for item in rep.private_bargaining_space)
    assert all(item in prompt for item in rep.private_information)
    assert all(description in prompt for description in rep.relationships.values())
    assert rep._agent_directive in prompt


def test_prompt_contains_venue_roster_public_fields_only() -> None:
    scenario = Scenario()
    scenario.load(str(TEMPLATE))
    rep = scenario.reps["winston_churchill"]
    venue = rep._require_venue()

    prompt = build_representative_system_prompt(rep)

    assert "## 会场代表" in prompt
    for seat_id in venue.seats:
        other = venue.reps[seat_id]
        assert other.id in prompt
        assert other.name in prompt
        assert other.delegation in prompt
        assert other.role in prompt
        assert other.title in prompt
        assert all(item in prompt for item in other.public_formal_powers)
        assert all(item in prompt for item in other.public_limits)
        # 他人私密内容不得进入会场代表一览（本角色私密另在角色卡中）。
        if other.id != rep.id:
            assert all(
                item.objective not in prompt for item in other.private_target
            )
            assert all(item not in prompt for item in other.private_red_lines)
            assert all(
                item not in prompt for item in other.private_information
            )


def test_prompt_explains_file_submission_workflow() -> None:
    scenario = Scenario()
    scenario.load(str(TEMPLATE))

    prompt = build_representative_system_prompt(
        scenario.reps["winston_churchill"]
    )

    assert "精准、简洁" in prompt
    assert "全部必要信息与细节" in prompt
    assert "submit_file" not in prompt
    assert "submit_instruction" in prompt
    assert "submit_resolution" in prompt
    assert "scope" in prompt
    assert "owner" in prompt
    assert "get_file_access" in prompt


def test_prompt_requires_bound_venue() -> None:
    with pytest.raises(RuntimeError, match="尚未设置 id"):
        build_representative_system_prompt(Representative())
