"""Representative 对 FileSystem 的封装接口."""

from __future__ import annotations

from pathlib import Path

import pytest

from scenario.scenario import Scenario

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
    for rep in scenario.representatives:
        if rep.id == rep_id:
            return rep
    raise AssertionError(f"missing rep {rep_id}")


def _events(scenario: Scenario):
    event_list = scenario.venues[0].event_list
    assert event_list is not None
    return event_list


def test_scenario_and_venue_reps_index(scenario: Scenario) -> None:
    venue = scenario.venues[0]
    assert venue.initial_agenda == "meaning_of_percentages"
    assert venue.current_agenda is not None
    assert venue.current_agenda.id == venue.initial_agenda
    assert set(scenario.reps) == {rep.id for rep in scenario.representatives}
    assert set(venue.reps) == set(venue.seats)
    for rep_id, rep in scenario.reps.items():
        assert rep is scenario.reps[rep_id]
        assert rep.id == rep_id
    for seat_id in venue.seats:
        assert venue.reps[seat_id] is scenario.reps[seat_id]


def test_representative_is_chair_from_venue(scenario: Scenario) -> None:
    # 模板会场 chair.rep: none → 引擎侧 None，全体代表均非主席
    from scenario.venue import CHAIR_POWER

    venue = scenario.venues[0]
    assert venue.chair is None
    assert venue.chair_power == {
        CHAIR_POWER.DECIDE_RESOLUTION: False,
        CHAIR_POWER.DECIDE_SWITCH_PHASE: False,
    }
    assert all(not rep.is_chair for rep in scenario.representatives)
    for rep in scenario.representatives:
        assert rep.is_chair is (rep.venue is not None and rep.venue.chair == rep.id)

    venue.chair = CHURCHILL
    assert venue.chair == CHURCHILL
    assert _rep(scenario, CHURCHILL).is_chair is True
    assert _rep(scenario, STALIN).is_chair is False

    venue.chair = STALIN
    assert _rep(scenario, CHURCHILL).is_chair is False
    assert _rep(scenario, STALIN).is_chair is True

    venue.chair = None
    assert venue.chair is None
    assert all(not rep.is_chair for rep in scenario.representatives)


def test_representative_file_api(scenario: Scenario) -> None:
    churchill = _rep(scenario, CHURCHILL)
    stalin = _rep(scenario, STALIN)

    draft = churchill.create_file("draft.md", "百分比初稿", "百分比草案")
    assert draft.description == "百分比草案"
    assert churchill.read_file(draft) == "百分比初稿"

    churchill.write_file(draft, "百分比修订稿")
    assert churchill.read_file(draft) == "百分比修订稿"

    visible = churchill.list_visible()
    writable = churchill.list_writable()
    assert [f.path.name for f in visible] == ["draft.md"]
    assert [f.path.name for f in writable] == ["draft.md"]
    assert visible[0].description == "百分比草案"

    assert stalin.list_visible() == []
    with pytest.raises(PermissionError):
        stalin.read_file(draft)
    with pytest.raises(PermissionError):
        stalin.write_file(draft, "篡改")


def test_representative_add_scope_and_owner(scenario: Scenario) -> None:
    churchill = _rep(scenario, CHURCHILL)
    eden = _rep(scenario, EDEN)
    stalin = _rep(scenario, STALIN)

    draft = churchill.create_file("draft.md", "百分比初稿", "百分比草案")

    with pytest.raises(PermissionError):
        churchill.add_owner(draft, EDEN)

    churchill.add_scope(draft, EDEN)
    assert eden.read_file(draft) == "百分比初稿"
    with pytest.raises(PermissionError):
        eden.write_file(draft, "篡改")

    with pytest.raises(PermissionError):
        eden.add_scope(draft, STALIN)

    churchill.add_owner(draft, {EDEN})
    eden.write_file(draft, "艾登修订")
    assert churchill.read_file(draft) == "艾登修订"
    assert draft.primary_owner == CHURCHILL

    assert stalin.list_visible() == []


def test_representative_get_file_access_owner_only(scenario: Scenario) -> None:
    churchill = _rep(scenario, CHURCHILL)
    eden = _rep(scenario, EDEN)
    stalin = _rep(scenario, STALIN)

    draft = churchill.create_file("draft.md", "百分比初稿", "百分比草案")
    access = churchill.get_file_access(draft)
    assert access["owners"] == frozenset({CHURCHILL})
    assert access["scope"] == {CHURCHILL}
    assert access["primary_owner"] == CHURCHILL

    churchill.add_scope(draft, EDEN)
    with pytest.raises(PermissionError, match="不是文件 .* 的 owner"):
        eden.get_file_access(draft)
    with pytest.raises(PermissionError, match="不是文件 .* 的 owner") as denied:
        stalin.get_file_access(draft)
    assert "当前 owner" not in str(denied.value)
    assert EDEN not in str(denied.value)

    churchill.add_owner(draft, EDEN)
    shared = eden.get_file_access(draft)
    assert shared["owners"] == frozenset({CHURCHILL, EDEN})
    assert shared["scope"] == {CHURCHILL, EDEN}
    assert shared["primary_owner"] == CHURCHILL


def test_representative_submit_file(scenario: Scenario) -> None:
    churchill = _rep(scenario, CHURCHILL)
    stalin = _rep(scenario, STALIN)
    draft = churchill.create_file("draft.md", "百分比初稿", "百分比草案")

    assert churchill.can_submit(draft)
    assert not stalin.can_submit(draft)

    submitted = churchill.submit_file(draft)
    assert submitted.is_submission
    assert submitted.owners == frozenset()
    assert submitted.scope == set()
    assert submitted.path.name.startswith(f"{CHURCHILL}+draft.md+v")
    assert submitted not in churchill.list_visible()
    assert not churchill.can_submit(draft)


def test_representative_set_description(scenario: Scenario) -> None:
    churchill = _rep(scenario, CHURCHILL)
    stalin = _rep(scenario, STALIN)
    draft = churchill.create_file("draft.md", "百分比初稿", "百分比草案")

    with pytest.raises(PermissionError):
        stalin.set_description(draft, "篡改简述")

    churchill.set_description(draft, "修订简述")
    assert draft.description == "修订简述"
    assert churchill.list_visible()[0].description == "修订简述"


def test_representative_send_message(scenario: Scenario) -> None:
    churchill = _rep(scenario, CHURCHILL)
    stalin = _rep(scenario, STALIN)
    events = _events(scenario)

    msg = churchill.send_message("希腊事务应交由伦敦主导")
    assert msg.id is not None
    assert msg.from_rep == CHURCHILL
    assert msg.content == "希腊事务应交由伦敦主导"
    assert churchill.venue is not None
    assert set(msg.scope) == set(churchill.venue.seats)
    assert msg in events.get_events(STALIN)


def test_representative_pass_note(scenario: Scenario) -> None:
    churchill = _rep(scenario, CHURCHILL)
    stalin = _rep(scenario, STALIN)
    events = _events(scenario)

    note = churchill.pass_note("试探希腊条款", EDEN)
    assert note.id is not None
    assert note.from_rep == CHURCHILL
    assert note.to_reps == {EDEN}
    assert note.scope == {CHURCHILL, EDEN}
    assert note in events.get_events(EDEN)
    assert note in events.get_events(CHURCHILL)
    assert note not in events.get_events(STALIN)

    multi = churchill.pass_note("共同核对底线", {EDEN, STALIN})
    assert multi.to_reps == {EDEN, STALIN}
    assert multi.scope == {CHURCHILL, EDEN, STALIN}

    with pytest.raises(ValueError, match="传纸条收件人 不能为空"):
        churchill.pass_note("空收件人", set())
    with pytest.raises(ValueError, match="不在会场"):
        churchill.pass_note("场外收件人", "not_a_seat")


def test_representative_submit_phase_switch(scenario: Scenario) -> None:
    from event.event import EventStatus, EventType
    from scenario.venue import CHAIR_POWER, SessionPhase

    churchill = _rep(scenario, CHURCHILL)
    stalin = _rep(scenario, STALIN)
    venue = scenario.venues[0]
    events = _events(scenario)
    before = venue.session_phase

    with pytest.raises(PermissionError, match="系统主席"):
        churchill.submit_phase_switch("越权切阶段", SessionPhase.FREE_DISCUSSION)

    venue.chair = CHURCHILL
    with pytest.raises(PermissionError, match="不是会场 .* 的主席"):
        stalin.submit_phase_switch("非主席切阶段", SessionPhase.FREE_DISCUSSION)
    with pytest.raises(PermissionError, match="decide_switch_phase=False"):
        churchill.submit_phase_switch("无权力切阶段", SessionPhase.FREE_DISCUSSION)
    assert venue.session_phase == before

    venue.chair_power[CHAIR_POWER.DECIDE_SWITCH_PHASE] = True
    event = churchill.submit_phase_switch(
        "主席裁定进入自由讨论", SessionPhase.FREE_DISCUSSION
    )
    assert event.id is not None
    assert event.type == EventType.PHASE_SWITCH
    assert event.status == EventStatus.COMPLETED
    assert event.previous_phase == before
    assert event.target_phase == SessionPhase.FREE_DISCUSSION
    assert venue.session_phase == SessionPhase.FREE_DISCUSSION
    assert event in events.get_events(STALIN)


def test_representative_submit_motion_switch(scenario: Scenario) -> None:
    from event.event import EventStatus, EventType
    from scenario.venue import SessionPhase

    churchill = _rep(scenario, CHURCHILL)
    stalin = _rep(scenario, STALIN)
    events = _events(scenario)
    assert churchill.venue is not None
    before_phase = churchill.venue.session_phase

    motion = churchill.submit_motion_switch(
        "动议进入自由讨论",
        SessionPhase.FREE_DISCUSSION,
    )
    assert motion.id is not None
    assert motion.type == EventType.MOTION_SWITCH
    assert motion.status == EventStatus.PENDING
    assert motion.target_phase == SessionPhase.FREE_DISCUSSION
    assert set(motion.scope) == set(churchill.venue.seats)
    assert motion in events.get_events(STALIN)
    assert motion.id in events.pending_event_ids
    # 动议不改变会场阶段
    assert churchill.venue.session_phase == before_phase


def test_representative_submit_instruction(scenario: Scenario) -> None:
    from event.event import EventStatus, EventType, InstructionEvent

    churchill = _rep(scenario, CHURCHILL)
    stalin = _rep(scenario, STALIN)
    events = _events(scenario)

    draft = churchill.create_file("instruction.md", "请外长核对希腊条款", "外长指示")
    instruction = churchill.submit_instruction(
        "外长指示已提交", {CHURCHILL, EDEN}, draft
    )
    submitted = instruction.instruction
    assert submitted.is_submission
    assert submitted.path.name.startswith(f"{CHURCHILL}+instruction.md+v")
    assert instruction.id is not None
    assert instruction.type == EventType.INSTRUCTION
    assert instruction.status == EventStatus.PENDING
    assert instruction.from_reps == {CHURCHILL, EDEN}
    assert instruction.scope == {CHURCHILL, EDEN}
    assert instruction in events.get_events(EDEN)
    assert instruction in events.get_events(CHURCHILL)
    assert instruction not in events.get_events(STALIN)
    linked = [
        e
        for e in events.get_events(EDEN)
        if isinstance(e, InstructionEvent)
    ]
    assert linked[0].instruction is submitted

    # 内容未变时再次从工作文件提交会被拒绝;已有 submission 可直接复用绑定
    with pytest.raises(ValueError, match="内容相对最新提交未变化"):
        churchill.submit_instruction("重复内容", {CHURCHILL, EDEN}, draft)
    reused = churchill.submit_instruction(
        "复用已有副本", {CHURCHILL, EDEN}, submitted
    )
    assert reused.instruction is submitted

    with pytest.raises(ValueError, match="fr 不能为空"):
        churchill.submit_instruction("空 fr", set(), submitted)
    with pytest.raises(ValueError, match="不在会场"):
        churchill.submit_instruction("场外 fr", {CHURCHILL, "not_a_seat"}, submitted)


def test_representative_submit_resolution(scenario: Scenario) -> None:
    from event.event import EventStatus, EventType

    churchill = _rep(scenario, CHURCHILL)
    stalin = _rep(scenario, STALIN)
    events = _events(scenario)
    assert churchill.venue is not None

    draft = churchill.create_file("resolution.md", "百分比草案", "决议草案")
    resolution = churchill.submit_resolution(
        "提出百分比决议", set(churchill.venue.seats), draft
    )
    submitted = resolution.resolution
    assert submitted.is_submission
    assert resolution.id is not None
    assert resolution.type == EventType.RESOLUTION
    assert resolution.status == EventStatus.PENDING
    assert resolution.from_reps == set(churchill.venue.seats)
    assert set(resolution.scope) == set(churchill.venue.seats)
    assert resolution in events.get_events(STALIN)

    limited = churchill.submit_resolution(
        "仅英方可见草案", {CHURCHILL, EDEN}, submitted
    )
    assert limited.resolution is submitted
    assert limited.from_reps == {CHURCHILL, EDEN}
    assert limited.scope == {CHURCHILL, EDEN}
    assert limited in events.get_events(EDEN)
    assert limited not in events.get_events(STALIN)
