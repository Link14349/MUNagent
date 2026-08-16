"""DM 首条 system prompt 构造测试。"""

from pathlib import Path

from agent.dm_prompt import build_dm_system_prompt
from scenario.scenario import Scenario
from scenario.venue import SessionPhase

TEMPLATE = Path(__file__).resolve().parent.parent / "scenario-template"


def _prompt() -> str:
    scenario = Scenario()
    scenario.load(str(TEMPLATE))
    return build_dm_system_prompt(scenario.venues[0])


def test_prompt_introduces_historical_committee_and_dm_role() -> None:
    prompt = _prompt()

    assert "模拟联合国历史委员会 DM Agent" in prompt
    assert "确定的历史时点" in prompt
    assert "不是主席或代表" in prompt
    assert "开场时点之后才发生的真实历史结果" in prompt
    assert "指令不经过主席接受或拒绝" in prompt
    assert "普通文本不会发布给代表" in prompt


def test_prompt_contains_scenario_background_and_targets() -> None:
    scenario = Scenario()
    scenario.load(str(TEMPLATE))
    venue = scenario.venues[0]

    prompt = build_dm_system_prompt(venue)

    assert scenario.title in prompt
    assert scenario.description in prompt
    assert scenario.background in prompt
    assert all(target in prompt for target in scenario.targets)
    assert venue.name in prompt
    assert venue.id in prompt
    assert venue.description in prompt
    assert venue.timezone in prompt
    assert scenario.start_time is not None
    assert scenario.start_time.isoformat() in prompt


def test_prompt_contains_venue_state_snapshot() -> None:
    scenario = Scenario()
    scenario.load(str(TEMPLATE))
    venue = scenario.venues[0]

    prompt = build_dm_system_prompt(venue)

    assert "## 会场状态" in prompt
    assert venue.session_phase is not None
    assert venue.session_phase.value in prompt
    assert venue.current_agenda is not None
    assert venue.current_agenda.id in prompt
    assert all(question in prompt for question in venue.current_agenda.questions)
    assert all(agenda.id in prompt for agenda in venue.todo_agenda)
    assert "系统中立主席" in prompt
    assert all(power.value in prompt for power in venue.chair_power)


def test_prompt_contains_venue_roster_public_fields_only() -> None:
    scenario = Scenario()
    scenario.load(str(TEMPLATE))
    venue = scenario.venues[0]

    prompt = build_dm_system_prompt(venue)

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
        assert all(item.objective not in prompt for item in other.private_target)
        assert all(item not in prompt for item in other.private_red_lines)
        assert all(item not in prompt for item in other.private_information)


def test_prompt_explains_supported_core_session_phases() -> None:
    prompt = _prompt()

    assert "有主持核心磋商" in prompt
    assert SessionPhase.CHAIRED_CORE.value in prompt
    assert "由主席确定讨论主题、发言顺序与程序节奏" in prompt
    assert "无主持核心磋商" in prompt
    assert SessionPhase.UNCHAIRED_CORE.value in prompt
    assert "可更直接地磋商、交换条件" in prompt
    assert "free_discussion" not in prompt


def test_prompt_keeps_adjudication_and_visibility_rules() -> None:
    prompt = _prompt()

    assert "very_likely_success" in prompt
    assert "very_likely_failure" in prompt
    assert "`adjudicate_instruction`" in prompt
    assert "roll < probability" in prompt
    assert "`publish_crisis_update`" in prompt
    assert "scope 是硬可见性边界" in prompt
    assert "rejected 决议不得执行" in prompt
    assert "不要生成新的代表指令或决议" in prompt
