"""代表首条 system prompt 构造测试。"""

from pathlib import Path

import pytest

from agent.rep_prompt import build_representative_system_prompt
from scenario.representative import Representative
from scenario.scenario import Scenario
from scenario.venue import SessionPhase

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


def test_prompt_contains_venue_state_snapshot() -> None:
    scenario = Scenario()
    scenario.load(str(TEMPLATE))
    rep = scenario.reps["winston_churchill"]
    venue = rep._require_venue()

    prompt = build_representative_system_prompt(rep)

    assert "## 会场状态" in prompt
    assert venue.name in prompt
    assert venue.session_phase is not None
    assert venue.session_phase.value in prompt
    assert venue.current_agenda is not None
    assert venue.current_agenda.id in prompt
    assert all(question in prompt for question in venue.current_agenda.questions)
    assert all(agenda.id in prompt for agenda in venue.todo_agenda)
    assert "系统中立主席" in prompt
    assert all(power.value in prompt for power in venue.chair_power)


def test_prompt_explains_supported_core_session_phases() -> None:
    scenario = Scenario()
    scenario.load(str(TEMPLATE))

    prompt = build_representative_system_prompt(
        scenario.reps["winston_churchill"]
    )

    assert "有主持核心磋商" in prompt
    assert SessionPhase.CHAIRED_CORE.value in prompt
    assert "由主席确定讨论主题、发言顺序与程序节奏" in prompt
    assert "无主持核心磋商" in prompt
    assert SessionPhase.UNCHAIRED_CORE.value in prompt
    assert "可更直接地磋商、交换条件" in prompt
    assert "free_discussion" not in prompt


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


def test_prompt_requires_events_for_external_interactions() -> None:
    scenario = Scenario()
    scenario.load(str(TEMPLATE))

    prompt = build_representative_system_prompt(
        scenario.reps["winston_churchill"]
    )

    assert "所有会议发言都必须调用 `send_message` 提交 `MessageEvent`" in prompt
    assert "只是只有你自己能看到的内部思考" in prompt
    assert "所有与会场、其他代表或外部世界的交互" in prompt
    assert "提交对应的 Event 才会实际发生" in prompt


def test_prompt_requires_bound_venue() -> None:
    with pytest.raises(RuntimeError, match="尚未设置 id"):
        build_representative_system_prompt(Representative())
