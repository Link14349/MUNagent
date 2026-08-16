"""自动终局检查：确定性时间条件与可注入文本裁判。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.rep_agent import RepresentativeAgent
from condition.condition import Condition
from engine.end_conditions import (
    LLMTextEndConditionEvaluator,
    TextEndConditionMatch,
)
from engine.simulator import Simulator
from event.event import EventType
from llm import ToolCall, ToolCallsDelta
from scenario.scenario import Scenario
from scenario.venue import SessionPhase
from service.meeting_service import MeetingRun, RunState


TEMPLATE = Path(__file__).resolve().parent.parent / "scenario-template"


class MatchingEvaluator:
    def __init__(self, condition_index: int) -> None:
        self.condition_index = condition_index
        self.calls = 0
        self.stopped = False

    def evaluate(self, conditions, evidence):
        self.calls += 1
        assert conditions
        assert "story_time" in evidence
        return [
            TextEndConditionMatch(
                condition_index=self.condition_index,
                reason="测试证据已经明确满足终局条件",
                evidence_event_ids=(),
            )
        ]

    def stop(self) -> None:
        self.stopped = True


class ReportingLLM:
    def __init__(self) -> None:
        self.stopped = False
        self.tool_choice = None

    async def stream(self, messages, **kwargs):
        self.tool_choice = kwargs["tool_choice"]
        assert "权威会议证据" in messages[-1].content
        yield ToolCallsDelta(
            (
                ToolCall(
                    "condition-call",
                    "report_end_conditions",
                    json.dumps(
                        {
                            "matched_conditions": [
                                {
                                    "condition_index": 2,
                                    "reason": "决议与表决证据一致",
                                    "evidence_event_ids": [4, 7],
                                }
                            ]
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
        )

    def stop(self) -> None:
        self.stopped = True


@pytest.fixture
def scenario(tmp_path: Path) -> Scenario:
    loaded = Scenario()
    loaded.load(str(TEMPLATE))
    loaded.root_path = tmp_path
    return loaded


def _keep_representatives_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    def wait_for_stop(self: RepresentativeAgent) -> None:
        if not self.wait_until_stopped(timeout=3.0):
            raise TimeoutError("测试代表未收到终局停止信号")

    monkeypatch.setattr(RepresentativeAgent, "run", wait_for_stop)


def test_condition_check_is_deterministic_for_time(scenario: Scenario) -> None:
    scenario.initialize()
    assert Condition("time", scenario.time, scenario).check() is True
    assert Condition("text", "已经达成协议", scenario).check() is False
    assert (
        Condition("text", "已经达成协议", scenario).check(lambda content: "协议" in content)
        is True
    )


def test_simulator_automatically_ends_on_time_condition(
    scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _keep_representatives_alive(monkeypatch)
    assert scenario.start_time is not None
    scenario.end_conditions = [Condition("time", scenario.start_time, scenario)]
    simulator = Simulator(scenario)

    simulator.run()

    match = simulator.end_condition_match
    assert match is not None
    assert match.condition_type == "time"
    venue = scenario.venues[0]
    assert venue.session_phase == SessionPhase.MEETING_ENDED
    assert venue.event_list is not None
    assert venue.event_list.events[-1].type == EventType.PHASE_SWITCH


def test_simulator_batches_text_conditions_and_ends(
    scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _keep_representatives_alive(monkeypatch)
    evaluator = MatchingEvaluator(condition_index=0)
    simulator = Simulator(scenario, text_end_condition_evaluator=evaluator)

    simulator.run()

    match = simulator.end_condition_match
    assert match is not None
    assert match.condition_type == "text"
    assert match.reason == "测试证据已经明确满足终局条件"
    assert evaluator.calls == 1
    assert evaluator.stopped is True


def test_llm_text_evaluator_requires_structured_report() -> None:
    llm = ReportingLLM()
    evaluator = LLMTextEndConditionEvaluator(llm)  # type: ignore[arg-type]

    matches = evaluator.evaluate(
        [(0, "谈判破裂"), (2, "决议已经通过")],
        '{"story_time":"1944-10-09T23:00:00+03:00"}',
    )

    assert matches == [
        TextEndConditionMatch(
            condition_index=2,
            reason="决议与表决证据一致",
            evidence_event_ids=(4, 7),
        )
    ]
    assert llm.tool_choice == {
        "type": "function",
        "function": {"name": "report_end_conditions"},
    }


def test_meeting_run_persists_seed_and_final_state(
    scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _keep_representatives_alive(monkeypatch)
    assert scenario.start_time is not None
    scenario.end_conditions = [Condition("time", scenario.start_time, scenario)]
    meeting = MeetingRun(scenario, seed="replay-seed", archive_interval_s=0.05)

    meeting.start()
    assert meeting.wait(timeout=3.0)

    assert meeting.state == RunState.ENDED
    assert meeting.run_dir is not None
    metadata = json.loads((meeting.run_dir / "run.json").read_text(encoding="utf-8"))
    assert metadata["seed"] == "replay-seed"
    assert metadata["state"] == "ended"
    assert metadata["end_condition"]["condition_type"] == "time"
    event_lines = (meeting.run_dir / "events.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert any(
        json.loads(line).get("target_phase") == "meeting_ended"
        for line in event_lines
    )


def test_same_minute_runs_receive_distinct_directories(tmp_path: Path) -> None:
    first = Scenario()
    first.load(str(TEMPLATE))
    first.root_path = tmp_path
    second = Scenario()
    second.load(str(TEMPLATE))
    second.root_path = tmp_path

    first.initialize()
    second.initialize()

    assert first.filesystem is not None
    assert second.filesystem is not None
    assert first.filesystem.path != second.filesystem.path
    assert first.filesystem.path.parent == second.filesystem.path.parent
