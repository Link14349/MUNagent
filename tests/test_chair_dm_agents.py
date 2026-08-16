"""ChairAgent / DMAgent 的权限、路由与危机更新闭环。"""

from __future__ import annotations

import json
from pathlib import Path
import re
import time

import pytest

from agent.chair_agent import ChairAgent
from agent.dm_agent import DMAgent
from agent.dm_tools import (
    DMToolExecutor,
    INSTRUCTION_TIER_PROBABILITIES,
    InstructionOutcomeTier,
    deterministic_instruction_roll,
)
from agent.inbox import ObservationKind
from agent.rep_agent_tools import RepresentativeToolExecutor
from agent.rep_agent import RepresentativeAgent
from engine.simulator import Simulator
from event.event import (
    ChairAction,
    ChairEvent,
    EventStatus,
    InstructionEvent,
    ResolutionEvent,
    SystemEvent,
    VoteEvent,
)
from llm import TextDelta, ToolCall, ToolCallsDelta
from scenario.scenario import Scenario
from scenario.venue import CHAIR_POWER

TEMPLATE = Path(__file__).resolve().parent.parent / "scenario-template"
CHURCHILL = "winston_churchill"
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


def _call(name: str, args: dict[str, object]) -> ToolCall:
    return ToolCall("test-call", name, json.dumps(args, ensure_ascii=False))


def _payload(raw: str) -> dict:
    return json.loads(raw)


def _resolution(scenario: Scenario, *, scope: set[str]) -> ResolutionEvent:
    rep = scenario.reps[CHURCHILL]
    file = rep.create_file("resolution.md", "第一条：建立联合协调机制。", "决议草案")
    return rep.submit_resolution("提交联合协调机制决议", scope, file)


def _instruction(scenario: Scenario, *, scope: set[str]) -> InstructionEvent:
    rep = scenario.reps[CHURCHILL]
    file = rep.create_file("instruction.md", "立即派联络员核实铁路通行状况。", "联络指令")
    return rep.submit_instruction("提交铁路核查指令", scope, file)


def test_chair_call_speaker_is_visible_to_all_but_targets_one(
    scenario: Scenario,
) -> None:
    venue = scenario.venues[0]
    chair = ChairAgent(venue)

    payload = _payload(
        chair.tools.execute(
            _call(
                "call_speaker",
                {"rep_id": STALIN, "content": "请苏方说明执行边界。"},
            )
        )
    )

    assert payload["ok"] is True
    event = venue._require_event_list().events[-1]
    assert isinstance(event, ChairEvent)
    assert event.action == ChairAction.CALL_SPEAKER
    assert event.target_reps == {STALIN}
    assert event.scope == set(venue.seats)


def test_representative_chair_does_not_gain_access_to_hidden_submission(
    scenario: Scenario,
) -> None:
    venue = scenario.venues[0]
    venue.chair = CHURCHILL
    hidden = _instruction(scenario, scope={STALIN})
    chair = ChairAgent(venue)

    assert "decide_instruction" not in {
        spec.name for spec in chair.tools.tool_specs
    }

    payload = _payload(
        chair.tools.execute(
            _call(
                "read_submission",
                {
                    "event_id": hidden.id,
                },
            )
        )
    )

    assert payload["ok"] is False
    assert payload["error_type"] == "ValueError"
    assert "不存在或主席不可见" in payload["error"]
    assert hidden.status == EventStatus.PENDING


def test_active_chair_agent_is_single_writer_for_chair_tools(
    scenario: Scenario,
) -> None:
    venue = scenario.venues[0]
    venue.chair = CHURCHILL
    venue.chair_agent_managed = True
    next_agenda = venue.todo_agenda[0]
    rep_tools = RepresentativeToolExecutor(scenario.reps[CHURCHILL])

    assert {
        "set_current_agenda",
        "add_agenda",
        "submit_phase_switch",
    }.isdisjoint({spec.name for spec in rep_tools.tool_specs})

    with pytest.raises(PermissionError, match="ChairAgent 单独持有"):
        scenario.reps[CHURCHILL].set_current_agenda(next_agenda)

    chair = ChairAgent(venue)
    venue.chair_agent_managed = True
    payload = _payload(
        chair.tools.execute(
            _call(
                "set_current_agenda",
                {"agenda_id": next_agenda.id, "finished": False},
            )
        )
    )
    assert payload["ok"] is True
    assert venue.current_agenda is next_agenda


def test_resolution_direct_decision_requires_power_and_writes_scoped_audit(
    scenario: Scenario,
) -> None:
    venue = scenario.venues[0]
    resolution = _resolution(scenario, scope={CHURCHILL})
    chair = ChairAgent(venue)
    args = {
        "event_id": resolution.id,
        "decision": "accepted",
        "reason": "条款处于主席直接裁定权限内",
    }

    denied = _payload(chair.tools.execute(_call("decide_resolution", args)))
    assert denied["ok"] is False
    assert resolution.status == EventStatus.PENDING

    venue.chair_power[CHAIR_POWER.DECIDE_RESOLUTION] = True
    allowed = _payload(chair.tools.execute(_call("decide_resolution", args)))
    assert allowed["ok"] is True
    assert resolution.status == EventStatus.ACCEPTED
    audit = venue._require_event_list().events[-1]
    assert isinstance(audit, ChairEvent)
    assert audit.scope == {CHURCHILL}
    assert f"事件 #{resolution.id}" in audit.content


def test_record_vote_adjudicates_resolution_without_direct_power(
    scenario: Scenario,
) -> None:
    venue = scenario.venues[0]
    resolution = _resolution(scenario, scope=set(venue.seats))
    chair = ChairAgent(venue)
    payload = _payload(
        chair.tools.execute(
            _call(
                "record_vote",
                {
                    "event_id": resolution.id,
                    "supporters": [CHURCHILL, STALIN],
                    "against": ["anthony_eden"],
                    "abstentions": ["vyacheslav_molotov"],
                    "pass_mode": "simple_majority",
                    "remark": "弃权不计入 present and voting",
                },
            )
        )
    )

    assert payload["ok"] is True
    assert resolution.status == EventStatus.ACCEPTED
    vote = venue._require_event_list().events[-1]
    assert isinstance(vote, VoteEvent)
    assert vote.passed is True


def test_dm_publishes_linked_scoped_crisis_update(scenario: Scenario) -> None:
    venue = scenario.venues[0]
    instruction = _instruction(scenario, scope={CHURCHILL, STALIN})
    executor = DMToolExecutor(venue, random_seed="test-seed")
    executor.begin_tasks([instruction])

    adjudication = _payload(
        executor.execute(
            _call(
                "adjudicate_instruction",
                {
                    "source_event_id": instruction.id,
                    "tier": "possible_success",
                    "rationale": "联络员权限充分，但铁路状况存在不确定性。",
                },
            )
        )
    )

    payload = _payload(
        executor.execute(
            _call(
                "publish_crisis_update",
                {
                    "source_event_id": instruction.id,
                    "content": "联络员报告铁路仍可通行，但两处枢纽出现延误。",
                    "action": ["铁路核查完成", "运输延误待处理"],
                    "scope": [CHURCHILL, STALIN],
                },
            )
        )
    )

    assert adjudication["ok"] is True
    assert adjudication["result"]["probability"] == 0.60
    assert 0 <= adjudication["result"]["roll"] < 1
    expected_status = (
        EventStatus.COMPLETED
        if adjudication["result"]["roll"] < 0.60
        else EventStatus.FAILED
    )
    assert instruction.status == expected_status
    duplicate = _payload(
        executor.execute(
            _call(
                "adjudicate_instruction",
                {
                    "source_event_id": instruction.id,
                    "tier": "very_likely_success",
                    "rationale": "试图换档重抽。",
                },
            )
        )
    )
    assert duplicate["ok"] is False
    assert payload["ok"] is True
    update = venue._require_event_list().events[-1]
    assert isinstance(update, SystemEvent)
    assert update.scope == {CHURCHILL, STALIN}
    assert f"source_event:{instruction.id}" in update.action
    assert f"source_status:{instruction.status.value}" in update.action
    assert "tier:possible_success" in update.action


def test_dm_rejected_resolution_cannot_advance_time(scenario: Scenario) -> None:
    venue = scenario.venues[0]
    resolution = _resolution(scenario, scope={CHURCHILL})
    resolution.status = EventStatus.REJECTED
    executor = DMToolExecutor(venue)
    executor.begin_tasks([resolution])
    before = scenario.time

    payload = _payload(
        executor.execute(
            _call(
                "advance_time",
                {
                    "source_event_id": resolution.id,
                    "minutes": 60,
                    "reason": "尝试错误推进",
                },
            )
        )
    )

    assert payload["ok"] is False
    assert payload["error_type"] == "PermissionError"
    assert scenario.time == before


def test_simulator_routes_pending_instruction_and_terminal_resolution_to_dm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = Scenario()
    loaded.load(str(TEMPLATE))
    loaded.root_path = tmp_path
    (tmp_path / "simulation").mkdir()
    dm_received = []
    chair_received = []

    def record_dm(self: DMAgent, observation) -> bool:
        dm_received.append(observation)
        return True

    def record_chair(self: ChairAgent, observation) -> bool:
        chair_received.append(observation)
        return True

    monkeypatch.setattr(DMAgent, "notify", record_dm)
    monkeypatch.setattr(ChairAgent, "notify", record_chair)
    simulator = Simulator(loaded)
    simulator.start()
    instruction = _instruction(loaded, scope={CHURCHILL})
    resolution = _resolution(loaded, scope={CHURCHILL})
    resolution.status = EventStatus.ACCEPTED
    loaded.reps[CHURCHILL].pass_note("只给斯大林看的纸条", {STALIN})
    simulator.stop()
    simulator.join(timeout=2.0)

    assert len(dm_received) == 2
    assert dm_received[0].event.id == instruction.id
    assert dm_received[0].kind == ObservationKind.EVENT_CREATED
    assert dm_received[0].event.status == "pending"
    assert dm_received[1].event.id == resolution.id
    assert dm_received[1].kind == ObservationKind.EVENT_STATUS_CHANGED
    assert dm_received[1].event.status == "accepted"
    assert all(item.event.event_type != "note" for item in chair_received)
    assert all(item.event.event_type != "instruction" for item in chair_received)


def test_simulator_chair_event_only_activates_called_speaker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = Scenario()
    loaded.load(str(TEMPLATE))
    loaded.root_path = tmp_path
    (tmp_path / "simulation").mkdir()
    received = []

    def record_rep(self: RepresentativeAgent, observation) -> bool:
        received.append((self.rep.id, observation))
        return True

    monkeypatch.setattr(RepresentativeAgent, "notify", record_rep)
    simulator = Simulator(loaded)
    simulator.start()
    venue = loaded.venues[0]
    chair = simulator.chair_agents[venue.id]
    payload = _payload(
        chair.tools.execute(
            _call(
                "call_speaker",
                {"rep_id": STALIN, "content": "请苏方陈述意见。"},
            )
        )
    )
    simulator.stop()
    simulator.join(timeout=2.0)

    assert payload["ok"] is True
    chair_observations = [
        (rep_id, item)
        for rep_id, item in received
        if item.event.event_type == "chair"
    ]
    assert {rep_id for rep_id, _ in chair_observations} == set(venue.seats)
    assert {
        rep_id for rep_id, item in chair_observations if item.activates_agent
    } == {STALIN}


def test_dm_agent_loop_processes_terminal_event_once(tmp_path: Path) -> None:
    loaded = Scenario()
    loaded.load(str(TEMPLATE))
    loaded.root_path = tmp_path
    (tmp_path / "simulation").mkdir()

    class CrisisLLM:
        def stop(self) -> None:
            pass

        async def stream(self, messages, **kwargs):
            if messages[-1].role == "user":
                match = re.search(r"事件 #(\d+)", messages[-1].content)
                assert match is not None
                event_id = int(match.group(1))
                yield ToolCallsDelta(
                    (
                        _call(
                            "adjudicate_instruction",
                            {
                                "source_event_id": event_id,
                                "tier": "success",
                                "rationale": "权限与人手充分，运输条件基本可控。",
                            },
                        ),
                    )
                )
            elif messages[-1].name == "adjudicate_instruction":
                match = re.search(r"事件 #(\d+)", messages[1].content)
                assert match is not None
                event_id = int(match.group(1))
                yield ToolCallsDelta(
                    (
                        _call(
                            "publish_crisis_update",
                            {
                                "source_event_id": event_id,
                                "content": "铁路核查行动完成了首次现场反馈。",
                                "action": ["核查产生结果"],
                                "scope": [CHURCHILL],
                            },
                        ),
                    )
                )
            else:
                yield TextDelta("本批任务处理完成。")

    fake_llm = CrisisLLM()
    simulator = Simulator(
        loaded,
        dm_llm_factory=lambda venue: fake_llm,  # type: ignore[return-value]
    )
    simulator.start()
    instruction = _instruction(loaded, scope={CHURCHILL})
    dm = simulator.dm_agents[loaded.venues[0].id]

    deadline = time.monotonic() + 2.0
    while instruction.id not in dm.processed_event_ids:
        if time.monotonic() >= deadline:
            pytest.fail("DMAgent 未在期限内处理指令")
        time.sleep(0.01)

    simulator.stop()
    simulator.join(timeout=2.0)
    matching = [
        event
        for event in loaded.venues[0]._require_event_list().events
        if isinstance(event, SystemEvent)
        and f"source_event:{instruction.id}" in event.action
        and "instruction_adjudication" not in event.action
    ]
    assert len(matching) == 1
    assert dm.outcomes[0].published_event_ids == (matching[0].id,)
    assert dm.outcomes[0].instruction_adjudication is not None
    assert instruction.status in {EventStatus.COMPLETED, EventStatus.FAILED}


def test_instruction_tiers_and_roll_are_stable() -> None:
    assert INSTRUCTION_TIER_PROBABILITIES == {
        InstructionOutcomeTier.VERY_LIKELY_SUCCESS: 0.95,
        InstructionOutcomeTier.SUCCESS: 0.80,
        InstructionOutcomeTier.POSSIBLE_SUCCESS: 0.60,
        InstructionOutcomeTier.POSSIBLE_FAILURE: 0.40,
        InstructionOutcomeTier.FAILURE: 0.20,
        InstructionOutcomeTier.VERY_LIKELY_FAILURE: 0.05,
    }
    first = deterministic_instruction_roll("seed-42", "venue", 7, "正文")
    second = deterministic_instruction_roll("seed-42", "venue", 7, "正文")
    assert first == second
    assert 0 <= first < 1
    assert deterministic_instruction_roll("seed-43", "venue", 7, "正文") != first
    assert deterministic_instruction_roll("seed-42", "venue", 7, "新正文") != first


def test_instruction_and_resolution_use_different_terminal_statuses(
    scenario: Scenario,
) -> None:
    instruction = _instruction(scenario, scope={CHURCHILL})
    resolution = _resolution(scenario, scope={CHURCHILL})

    with pytest.raises(ValueError, match="不能使用 accepted/rejected"):
        instruction.status = EventStatus.ACCEPTED
    with pytest.raises(ValueError, match="accepted/rejected"):
        resolution.status = EventStatus.COMPLETED

    assert instruction.status == EventStatus.PENDING
    assert resolution.status == EventStatus.PENDING
