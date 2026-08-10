"""投票事件基本构造与校验。"""

from __future__ import annotations

from pathlib import Path

import pytest

from event.event import (
    EventType,
    MotionSwitchEvent,
    ResolutionEvent,
    VoteEvent,
    VotePassMode,
)
from scenario.scenario import Scenario
from scenario.venue import SessionPhase

TEMPLATE = Path(__file__).resolve().parent.parent / "scenario-template"


@pytest.fixture
def scenario() -> Scenario:
    loaded = Scenario()
    loaded.load(str(TEMPLATE))
    return loaded


@pytest.fixture
def venue_id(scenario: Scenario) -> str:
    return scenario.venues[0].id


def _motion(scenario: Scenario, venue_id: str) -> MotionSwitchEvent:
    return MotionSwitchEvent(
        "动议进入自由讨论",
        SessionPhase.FREE_DISCUSSION,
        venue_id,
        {rep.id for rep in scenario.representatives},
        scenario,
    )


def test_vote_event_records_ballots(scenario: Scenario, venue_id: str) -> None:
    target = _motion(scenario, venue_id)
    vote = VoteEvent(
        "就阶段切换动议表决",
        venue_id,
        {rep.id for rep in scenario.representatives},
        target,
        valid_votes=4,
        pass_mode=VotePassMode.SIMPLE_MAJORITY,
        scenario=scenario,
        supporters=["winston_churchill", "anthony_eden"],
        against=["joseph_stalin"],
        abstentions=["vyacheslav_molotov"],
        passed=True,
        remark="无否决权适用；按简单多数通过",
    )
    assert vote.type == EventType.VOTE
    assert vote.venue == venue_id
    assert vote.time is None
    assert vote.target is target
    assert vote.valid_votes == 4
    assert vote.supporters == ["winston_churchill", "anthony_eden"]
    assert vote.against == ["joseph_stalin"]
    assert vote.abstentions == ["vyacheslav_molotov"]
    assert vote.pass_mode == VotePassMode.SIMPLE_MAJORITY
    assert vote.passed is True
    assert "否决权" in vote.remark


def test_vote_event_rejects_overlap_and_bad_target(scenario: Scenario, venue_id: str) -> None:
    target = _motion(scenario, venue_id)
    with pytest.raises(ValueError, match="同时出现"):
        VoteEvent(
            "重复投票",
            venue_id,
            {rep.id for rep in scenario.representatives},
            target,
            valid_votes=4,
            pass_mode="two_thirds",
            scenario=scenario,
            supporters=["winston_churchill"],
            against=["winston_churchill"],
        )
    with pytest.raises(TypeError, match="ResolutionEvent 或 MotionSwitchEvent"):
        VoteEvent(
            "错误目标",
            venue_id,
            set(),
            object(),  # type: ignore[arg-type]
            valid_votes=1,
            pass_mode=VotePassMode.UNANIMOUS,
            scenario=scenario,
        )


def test_vote_event_accepts_resolution_target(
    scenario: Scenario,
    venue_id: str,
    tmp_path: Path,
) -> None:
    from filesystem.filesystem import FileSystem

    scenario.filesystem = FileSystem(tmp_path / "run", scenario)
    draft = scenario.filesystem.create_rep_file(
        "winston_churchill",
        "res.md",
        "百分比草案",
    )
    submitted = draft.submit("winston_churchill")
    resolution = ResolutionEvent(
        "提出决议",
        {"winston_churchill"},
        submitted,
        venue_id,
        scenario,
    )
    vote = VoteEvent(
        "决议表决",
        venue_id,
        {rep.id for rep in scenario.representatives},
        resolution,
        valid_votes=4,
        pass_mode=VotePassMode.UNANIMOUS,
        scenario=scenario,
        supporters=["winston_churchill", "anthony_eden", "joseph_stalin", "vyacheslav_molotov"],
        passed=True,
        remark="全体一致；无强制通过或否决",
    )
    assert isinstance(vote.target, ResolutionEvent)
    assert vote.target.resolution is submitted
    assert vote.venue == resolution.venue == venue_id
    assert vote.time is None
    assert resolution.time is None
