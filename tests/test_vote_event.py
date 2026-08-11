"""投票事件基本构造与校验."""

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
        remark="无否决权适用;按简单多数通过",
    )
    assert vote.type == EventType.VOTE
    assert vote.venue == venue_id
    assert vote.time is None
    assert vote.target is target
    assert vote.valid_votes == 4
    assert vote.named is True
    assert vote.supporters == ["winston_churchill", "anthony_eden"]
    assert vote.against == ["joseph_stalin"]
    assert vote.abstentions == ["vyacheslav_molotov"]
    assert vote.support_count == 2
    assert vote.against_count == 1
    assert vote.abstention_count == 1
    assert vote.pass_mode == VotePassMode.SIMPLE_MAJORITY
    assert vote.passed is True
    assert "否决权" in vote.remark


def test_vote_event_anonymous_hides_ballots(
    scenario: Scenario, venue_id: str
) -> None:
    target = _motion(scenario, venue_id)
    vote = VoteEvent(
        "不记名表决",
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
        named=False,
    )
    assert vote.named is False
    assert vote.support_count == 2
    assert vote.against_count == 1
    assert vote.abstention_count == 1
    with pytest.raises(PermissionError, match="不记名投票"):
        _ = vote.supporters
    with pytest.raises(PermissionError, match="不记名投票"):
        _ = vote.against
    with pytest.raises(PermissionError, match="不记名投票"):
        _ = vote.abstentions


def test_vote_event_named_ballot_properties_return_copies(
    scenario: Scenario, venue_id: str
) -> None:
    target = _motion(scenario, venue_id)
    vote = VoteEvent(
        "记名表决副本",
        venue_id,
        {rep.id for rep in scenario.representatives},
        target,
        valid_votes=2,
        pass_mode=VotePassMode.SIMPLE_MAJORITY,
        scenario=scenario,
        supporters=["winston_churchill"],
        against=["joseph_stalin"],
        named=True,
    )
    supporters = vote.supporters
    against = vote.against
    abstentions = vote.abstentions
    supporters.clear()
    against.clear()
    abstentions.append("anthony_eden")
    assert vote.supporters == ["winston_churchill"]
    assert vote.against == ["joseph_stalin"]
    assert vote.abstentions == []


def test_vote_event_rejects_overlap(scenario: Scenario, venue_id: str) -> None:
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
        remark="全体一致;无强制通过或否决",
    )
    assert isinstance(vote.target, ResolutionEvent)
    assert vote.target.resolution is submitted
    assert vote.venue == resolution.venue == venue_id
    assert vote.time is None
    assert resolution.time is None
