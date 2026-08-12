"""RepresentativeAgent 工具定义与分发."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.rep_agent_tools import REP_TOOL_SPECS, RepresentativeToolExecutor
from llm.types import ToolCall
from scenario.scenario import Scenario
from scenario.venue import CHAIR_POWER, SessionPhase

TEMPLATE = Path(__file__).resolve().parent.parent / "scenario-template"

CHURCHILL = "winston_churchill"
EDEN = "anthony_eden"
STALIN = "joseph_stalin"


@pytest.fixture
def scenario(tmp_path: Path, venue_engine_runner) -> Scenario:
    loaded = Scenario()
    loaded.load(str(TEMPLATE))
    loaded.root_path = tmp_path
    (tmp_path / "simulation").mkdir()
    loaded.initialize()
    for venue in loaded.venues:
        venue_engine_runner.start(venue)
    return loaded


def _rep(scenario: Scenario, rep_id: str):
    return scenario.reps[rep_id]


def _call(tool_name: str, **args) -> ToolCall:
    return ToolCall(
        id="call_test",
        name=tool_name,
        arguments=json.dumps(args, ensure_ascii=False),
    )


def test_rep_tool_specs_cover_handlers() -> None:
    names = {spec.name for spec in REP_TOOL_SPECS}
    assert "send_message" in names
    assert "submit_instruction" in names
    assert "submit_file" not in names
    assert "list_agendas" in names
    assert len(REP_TOOL_SPECS) == len(names)


def test_executor_send_message_and_note(scenario: Scenario) -> None:
    churchill = _rep(scenario, CHURCHILL)
    executor = RepresentativeToolExecutor(churchill)

    msg = json.loads(executor.execute(_call("send_message", content="希腊应归伦敦主导")))
    assert msg["ok"] is True
    assert msg["result"]["type"] == "message"

    note = json.loads(
        executor.execute(_call("pass_note", content="试探底线", to=EDEN))
    )
    assert note["ok"] is True
    assert note["result"]["type"] == "note"

    bad = json.loads(
        executor.execute(_call("pass_note", content="场外", to="not_a_seat"))
    )
    assert bad["ok"] is False


def test_executor_files_submit_instruction(scenario: Scenario) -> None:
    churchill = _rep(scenario, CHURCHILL)
    executor = RepresentativeToolExecutor(churchill)

    created = json.loads(
        executor.execute(
            _call(
                "create_file",
                name="instruction.md",
                content="请外长核对",
                description="外长指示",
            )
        )
    )
    assert created["ok"] is True
    path = created["result"]["path"]
    assert created["result"]["owners"] == [CHURCHILL]

    access = json.loads(executor.execute(_call("get_file_access", path=path)))
    assert access["ok"] is True
    assert access["result"]["owners"] == [CHURCHILL]
    assert access["result"]["scope"] == [CHURCHILL]

    instruction = json.loads(
        executor.execute(
            _call(
                "submit_instruction",
                content="外长指示已提交",
                fr=[CHURCHILL, EDEN],
                path=path,
            )
        )
    )
    assert instruction["ok"] is True
    assert instruction["result"]["type"] == "instruction"
    assert "submissions/" in instruction["result"]["file"]["path"]


def test_executor_get_file_access_owner_only(scenario: Scenario) -> None:
    churchill = _rep(scenario, CHURCHILL)
    eden = _rep(scenario, EDEN)
    owner_ex = RepresentativeToolExecutor(churchill)
    reader_ex = RepresentativeToolExecutor(eden)

    created = json.loads(
        owner_ex.execute(
            _call(
                "create_file",
                name="shared.md",
                content="草案",
                description="共享草案",
            )
        )
    )
    path = created["result"]["path"]
    scoped = json.loads(
        owner_ex.execute(_call("add_scope", path=path, others=EDEN))
    )
    assert scoped["ok"] is True

    visible = json.loads(reader_ex.execute(_call("list_visible_files")))
    assert visible["ok"] is True
    assert len(visible["result"]) == 1
    assert "owners" not in visible["result"][0]
    assert "scope" not in visible["result"][0]

    denied = json.loads(reader_ex.execute(_call("get_file_access", path=path)))
    assert denied["ok"] is False
    assert "不是文件" in denied["error"]
    assert "当前 owner" not in denied["error"]


def test_executor_agenda_and_phase_requires_chair(scenario: Scenario) -> None:
    churchill = _rep(scenario, CHURCHILL)
    venue = scenario.venues[0]
    executor = RepresentativeToolExecutor(churchill)

    info = json.loads(executor.execute(_call("get_session_info")))
    assert info["ok"] is True
    assert info["result"]["rep_id"] == CHURCHILL

    agendas = json.loads(executor.execute(_call("list_agendas")))
    assert agendas["ok"] is True
    assert agendas["result"]["current"] is not None

    denied = json.loads(
        executor.execute(
            _call(
                "submit_phase_switch",
                content="切阶段",
                target_phase=SessionPhase.FREE_DISCUSSION.value,
            )
        )
    )
    assert denied["ok"] is False

    venue.chair = CHURCHILL
    venue.chair_power[CHAIR_POWER.DECIDE_SWITCH_PHASE] = True
    ok = json.loads(
        executor.execute(
            _call(
                "submit_phase_switch",
                content="主席裁定自由讨论",
                target_phase=SessionPhase.FREE_DISCUSSION.value,
            )
        )
    )
    assert ok["ok"] is True
    assert venue.session_phase == SessionPhase.FREE_DISCUSSION


def test_executor_unknown_tool(scenario: Scenario) -> None:
    executor = RepresentativeToolExecutor(_rep(scenario, STALIN))
    result = json.loads(executor.execute(_call("not_a_tool")))
    assert result["ok"] is False
    assert "未知工具" in result["error"]
