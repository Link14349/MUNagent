"""完整状态机单元测试."""

from __future__ import annotations

import pytest

from munagent.core.state_machine import GroupState, VenueStateMachine


def _mk_sm(**kwargs) -> VenueStateMachine:
    defaults = dict(
        venue_id="v1",
        seat_ids=["a", "b", "c"],
        initial_phase="Opening",
        start_story_time="2026-03-15T09:00:00+08:00",
    )
    defaults.update(kwargs)
    return VenueStateMachine(**defaults)


class TestTransitions:
    def test_opening_to_mod(self) -> None:
        sm = _mk_sm()
        sm.transition("ModeratedCaucus")
        assert sm.phase == "ModeratedCaucus"

    def test_mod_to_unmod(self) -> None:
        sm = _mk_sm(initial_phase="ModeratedCaucus")
        sm.transition("UnmoderatedCaucus")
        assert sm.phase == "UnmoderatedCaucus"

    def test_unmod_to_mod(self) -> None:
        sm = _mk_sm(initial_phase="UnmoderatedCaucus")
        sm.transition("ModeratedCaucus")
        assert sm.phase == "ModeratedCaucus"

    def test_mod_to_voting_returns_after(self) -> None:
        sm = _mk_sm(initial_phase="ModeratedCaucus")
        sm.transition("Voting", interrupted_from="ModeratedCaucus")
        assert sm.phase == "Voting"
        assert sm.interrupted_phase == "ModeratedCaucus"

    def test_illegal_transition_raises(self) -> None:
        sm = _mk_sm(initial_phase="Opening")
        with pytest.raises(ValueError, match="非法状态转移"):
            sm.transition("UnmoderatedCaucus")  # Opening 不能直接到 Unmod

    def test_adjourned_is_terminal(self) -> None:
        sm = _mk_sm(initial_phase="Adjourned")
        assert sm.can_transition("ModeratedCaucus") is False


class TestModBudget:
    def test_budget_exceeded(self) -> None:
        sm = _mk_sm(initial_phase="ModeratedCaucus", max_speeches=3)
        sm.record_speech("a")
        sm.record_speech("b")
        assert not sm.budget_exceeded
        sm.record_speech("c")
        assert sm.budget_exceeded

    def test_floor_rotation(self) -> None:
        sm = _mk_sm(initial_phase="ModeratedCaucus")
        # 3 席位, 3 轮无人发言 → 触发
        sm.record_no_speech()
        sm.record_no_speech()
        assert not sm.floor_rotation_due
        sm.record_no_speech()
        assert sm.floor_rotation_due
        forced = sm.next_for_floor_rotation()
        assert forced == "a"  # 最久未发言

    def test_transition_resets_mod_counters(self) -> None:
        sm = _mk_sm(initial_phase="ModeratedCaucus")
        sm.record_speech("a")
        sm.record_speech("b")
        sm.transition("UnmoderatedCaucus")
        sm.transition("ModeratedCaucus")
        assert sm.mod_speech_count == 0
        assert sm.spoken_this_phase == []


class TestVoting:
    def test_majority_pass(self) -> None:
        sm = _mk_sm(initial_phase="ModeratedCaucus")
        sm.transition("Voting", interrupted_from="ModeratedCaucus")
        sm.start_vote("d1", ["a", "b", "c"])
        sm.record_vote("a", "aye")
        sm.record_vote("b", "aye")
        sm.record_vote("c", "nay")
        result, tally = sm.tally_votes("majority", [])
        assert result == "passed"
        assert tally == {"aye": 2, "nay": 1, "abstain": 0}

    def test_majority_with_abstain_not_in_denominator(self) -> None:
        """弃权不计入分母: 2赞成 1反对 1弃权 → 2/3 = majority 通过."""
        sm = _mk_sm(initial_phase="ModeratedCaucus", seat_ids=["a", "b", "c", "d"])
        sm.transition("Voting", interrupted_from="ModeratedCaucus")
        sm.start_vote("d1", ["a", "b", "c", "d"])
        sm.record_vote("a", "aye")
        sm.record_vote("b", "aye")
        sm.record_vote("c", "nay")
        sm.record_vote("d", "abstain")
        result, tally = sm.tally_votes("majority", [])
        assert result == "passed"  # 2/3, 不是 2/4

    def test_veto_blocks(self) -> None:
        sm = _mk_sm(initial_phase="ModeratedCaucus")
        sm.transition("Voting", interrupted_from="ModeratedCaucus")
        sm.start_vote("d1", ["a", "b", "c"])
        sm.record_vote("a", "aye")
        sm.record_vote("b", "aye")
        sm.record_vote("c", "nay")  # c 是 veto 席
        result, tally = sm.tally_votes("majority", ["c"])
        assert result == "rejected"

    def test_veto_abstain_not_blocks(self) -> None:
        """veto 席位弃权不构成否决."""
        sm = _mk_sm(initial_phase="ModeratedCaucus", seat_ids=["a", "b", "c", "d"])
        sm.transition("Voting", interrupted_from="ModeratedCaucus")
        sm.start_vote("d1", ["a", "b", "c", "d"])
        sm.record_vote("a", "aye")
        sm.record_vote("b", "aye")
        sm.record_vote("c", "nay")
        sm.record_vote("d", "abstain")  # d 是 veto 席但弃权
        result, tally = sm.tally_votes("majority", ["d"])
        assert result == "passed"  # 2/3, veto 未触发

    def test_all_abstain_rejected(self) -> None:
        sm = _mk_sm(initial_phase="ModeratedCaucus")
        sm.transition("Voting", interrupted_from="ModeratedCaucus")
        sm.start_vote("d1", ["a", "b", "c"])
        sm.record_vote("a", "abstain")
        sm.record_vote("b", "abstain")
        sm.record_vote("c", "abstain")
        result, _ = sm.tally_votes("majority", [])
        assert result == "rejected"

    def test_end_vote_returns_to_interrupted(self) -> None:
        sm = _mk_sm(initial_phase="ModeratedCaucus")
        sm.transition("Voting", interrupted_from="ModeratedCaucus")
        sm.start_vote("d1", ["a"])
        sm.record_vote("a", "aye")
        return_phase = sm.end_vote()
        assert return_phase == "ModeratedCaucus"

    def test_two_thirds_threshold(self) -> None:
        sm = _mk_sm(initial_phase="ModeratedCaucus")
        sm.transition("Voting", interrupted_from="ModeratedCaucus")
        sm.start_vote("d1", ["a", "b", "c"])
        sm.record_vote("a", "aye")
        sm.record_vote("b", "aye")
        sm.record_vote("c", "nay")
        result, _ = sm.tally_votes("two_thirds", [])
        # 2/2 voted, 2/3 threshold = need 2*3 >= 2*2 → 6 >= 4 → passed
        assert result == "passed"

    def test_unanimous(self) -> None:
        sm = _mk_sm(initial_phase="ModeratedCaucus")
        sm.transition("Voting", interrupted_from="ModeratedCaucus")
        sm.start_vote("d1", ["a", "b", "c"])
        sm.record_vote("a", "aye")
        sm.record_vote("b", "aye")
        sm.record_vote("c", "abstain")  # 弃权不阻止一致通过
        result, _ = sm.tally_votes("unanimous", [])
        assert result == "passed"


class TestUnmod:
    def test_init_groups(self) -> None:
        sm = _mk_sm(initial_phase="UnmoderatedCaucus")
        g1 = GroupState("g1", ["a", "b"])
        g2 = GroupState("g2", ["c"])
        sm.init_groups([g1, g2])
        assert len(sm.groups) == 2
        assert sm.unmod_round_count == 0

    def test_unmod_finished(self) -> None:
        sm = _mk_sm(initial_phase="UnmoderatedCaucus", unmod_rounds=3)
        sm.init_groups([GroupState("g1", ["a"])])
        sm.next_unmod_round()
        sm.next_unmod_round()
        assert not sm.unmod_finished
        sm.next_unmod_round()
        assert sm.unmod_finished
