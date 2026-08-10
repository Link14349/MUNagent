"""场景包加载：从目录构造 Scenario 及下属对象。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from condition.condition import Condition
from event.eventlist import EventList, PullUpEvent
from scenario.load_helpers import (
    EVENT_FORBIDDEN_KEYS,
    INDEX_FORBIDDEN_KEYS,
    REP_FORBIDDEN_TARGET_KEYS,
    SCHEMA_VERSION,
    forbid_keys,
    load_yaml,
    parse_condition,
    parse_iso_datetime,
    require_keys,
    validate_scenario_layout,
)
from scenario.representative import PrivateTarget, Representative
from scenario.scenario import Scenario
from scenario.venue import Agenda, Venue


def load_scenario(path: str | Path) -> Scenario:
    """从场景包目录加载并返回 Scenario。"""
    scenario = Scenario()
    populate_scenario(scenario, path)
    return scenario


def populate_scenario(scenario: Scenario, scenario_path: str | Path) -> None:
    """将场景包目录内容填入已有 Scenario 实例。"""
    root = Path(scenario_path).resolve()
    validate_scenario_layout(root)

    index = load_yaml(root / "index.yaml")
    _load_index(scenario, index)

    background_path = root / "background.md"
    scenario.background = background_path.read_text(encoding="utf-8").strip()
    if not scenario.background:
        raise ValueError(f"background.md 不能为空: {background_path}")

    storyline = load_yaml(root / "storyline.yaml")
    _load_storyline(scenario, storyline)

    venues_by_id: dict[str, Venue] = {}
    for venue_path in sorted((root / "venues").glob("*.yaml")):
        venue = _load_venue(scenario, venue_path)
        if venue.id in venues_by_id:
            raise ValueError(f"重复的会场 ID: {venue.id}")
        venues_by_id[venue.id] = venue
    scenario.venues = list(venues_by_id.values())

    representatives_by_id: dict[str, Representative] = {}
    for rep_path in sorted((root / "reps").glob("*.yaml")):
        rep = _load_representative(rep_path, venues_by_id)
        if rep.id in representatives_by_id:
            raise ValueError(f"重复的代表 ID: {rep.id}")
        representatives_by_id[rep.id] = rep
    scenario.representatives = list(representatives_by_id.values())

    _validate_cross_references(scenario, venues_by_id, representatives_by_id)
    scenario.event_list = EventList(scenario)


def _load_index(scenario: Scenario, index: dict[str, Any]) -> None:
    context = "index.yaml"
    forbid_keys(index, INDEX_FORBIDDEN_KEYS, context=context)
    require_keys(
        index,
        {
            "schema_version",
            "title",
            "author",
            "version",
            "language",
            "start_story_time",
            "timezone",
            "description",
            "sources",
        },
        context=context,
    )

    schema_version = index["schema_version"]
    if schema_version != SCHEMA_VERSION:
        raise ValueError(
            f"{context}.schema_version 须为 {SCHEMA_VERSION!r}，实际为 {schema_version!r}"
        )

    scenario.title = _require_str(index["title"], field=f"{context}.title")
    scenario.description = _require_str(index["description"], field=f"{context}.description")
    scenario.timezone = _require_str(index["timezone"], field=f"{context}.timezone")
    scenario.time = parse_iso_datetime(
        index["start_story_time"],
        context=f"{context}.start_story_time",
    )

    sources = index["sources"]
    if not isinstance(sources, list) or not sources:
        raise ValueError(f"{context}.sources 须为非空列表")
    for index_no, source in enumerate(sources):
        source_context = f"{context}.sources[{index_no}]"
        if not isinstance(source, dict):
            raise ValueError(f"{source_context} 须为对象")
        require_keys(source, {"title", "url", "note"}, context=source_context)


def _load_storyline(scenario: Scenario, storyline: dict[str, Any]) -> None:
    context = "storyline.yaml"
    require_keys(storyline, {"targets", "events", "end_conditions"}, context=context)

    targets_raw = storyline["targets"]
    if not isinstance(targets_raw, list) or not targets_raw:
        raise ValueError(f"{context}.targets 须为非空列表")
    scenario.targets = []
    seen_target_ids: set[str] = set()
    for index, target in enumerate(targets_raw):
        target_context = f"{context}.targets[{index}]"
        if not isinstance(target, dict):
            raise ValueError(f"{target_context} 须为对象")
        require_keys(target, {"id", "description"}, context=target_context)
        target_id = _require_str(target["id"], field=f"{target_context}.id")
        if target_id in seen_target_ids:
            raise ValueError(f"重复的场景目标 ID: {target_id}")
        seen_target_ids.add(target_id)
        scenario.targets.append(
            _require_str(target["description"], field=f"{target_context}.description")
        )

    events_raw = storyline["events"]
    if not isinstance(events_raw, list):
        raise ValueError(f"{context}.events 须为列表")
    scenario.event_pool = []
    seen_event_ids: set[str] = set()
    for index, event in enumerate(events_raw):
        event_context = f"{context}.events[{index}]"
        if not isinstance(event, dict):
            raise ValueError(f"{event_context} 须为对象")
        require_keys(event, {"id", "condition", "content"}, context=event_context)
        forbid_keys(event, EVENT_FORBIDDEN_KEYS, context=event_context)
        extra = set(event.keys()) - {"id", "condition", "content"}
        if extra:
            joined = "、".join(sorted(extra))
            raise ValueError(f"{event_context} 只能包含 id、condition 和 content，多余字段: {joined}")

        event_id = _require_str(event["id"], field=f"{event_context}.id")
        if event_id in seen_event_ids:
            raise ValueError(f"重复的事件 ID: {event_id}")
        seen_event_ids.add(event_id)

        cond_type, cond_content = parse_condition(
            event["condition"],
            context=f"{event_context}.condition",
        )
        content = _require_str(event["content"], field=f"{event_context}.content")
        scenario.event_pool.append(
            PullUpEvent(
                condition=Condition(cond_type, cond_content, scenario),
                content=content,
                scenario=scenario,
            )
        )

    end_conditions_raw = storyline["end_conditions"]
    if not isinstance(end_conditions_raw, list) or not end_conditions_raw:
        raise ValueError(f"{context}.end_conditions 须为非空列表")
    scenario.end_conditions = []
    for index, end_condition in enumerate(end_conditions_raw):
        end_context = f"{context}.end_conditions[{index}]"
        if not isinstance(end_condition, dict):
            raise ValueError(f"{end_context} 须为对象")
        cond_type, cond_content = parse_condition(end_condition, context=end_context)
        scenario.end_conditions.append(Condition(cond_type, cond_content, scenario))


def _load_venue(scenario: Scenario, venue_path: Path) -> Venue:
    data = load_yaml(venue_path)
    context = f"会场 {venue_path.name}"

    require_keys(
        data,
        {
            "id",
            "name",
            "timezone",
            "description",
            "chair",
            "seats",
            "initial_agenda",
            "agenda",
        },
        context=context,
    )

    venue = Venue(scenario)
    venue.id = _require_str(data["id"], field=f"{context}.id")
    venue.name = _require_str(data["name"], field=f"{context}.name")
    venue.timezone = _require_str(data["timezone"], field=f"{context}.timezone")
    venue.description = _require_str(data["description"], field=f"{context}.description")
    venue.initial_agenda = _require_str(
        data["initial_agenda"],
        field=f"{context}.initial_agenda",
    )

    chair = data["chair"]
    if not isinstance(chair, str) or not chair.strip():
        raise ValueError(f"{context}.chair 须为非空字符串")
    venue.chair = chair.strip()

    seats = data["seats"]
    if not isinstance(seats, list) or not seats:
        raise ValueError(f"{context}.seats 须为非空列表")
    venue.seats = []
    for index, seat in enumerate(seats):
        if not isinstance(seat, str) or not seat.strip():
            raise ValueError(f"{context}.seats[{index}] 须为非空代表 ID 字符串")
        venue.seats.append(seat.strip())

    agenda_raw = data["agenda"]
    if not isinstance(agenda_raw, list) or not agenda_raw:
        raise ValueError(f"{context}.agenda 须为非空列表")

    venue.agenda = []
    for index, item in enumerate(agenda_raw):
        item_context = f"{context}.agenda[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{item_context} 须为对象")
        require_keys(item, {"id", "title", "questions"}, context=item_context)
        questions = item["questions"]
        if not isinstance(questions, list) or not questions:
            raise ValueError(f"{item_context}.questions 须为非空列表")
        parsed_questions: list[str] = []
        for q_index, question in enumerate(questions):
            if not isinstance(question, str) or not question.strip():
                raise ValueError(
                    f"{item_context}.questions[{q_index}] 须为非空字符串"
                )
            parsed_questions.append(question.strip())
        venue.agenda.append(
            Agenda(
                id=_require_str(item["id"], field=f"{item_context}.id"),
                title=_require_str(item["title"], field=f"{item_context}.title"),
                questions=parsed_questions,
            )
        )
    return venue


def _load_representative(
    representative_path: Path,
    venues: dict[str, Venue],
) -> Representative:
    rep_id = representative_path.stem
    if not rep_id:
        raise ValueError(f"代表文件名无效: {representative_path}")

    data = load_yaml(representative_path)
    context = f"代表 {rep_id}"

    forbid_keys(data, {"id"}, context=context)
    require_keys(
        data,
        {"name", "venue", "delegation", "role", "public", "private", "persona", "agent_directive"},
        context=context,
    )

    rep = Representative()
    rep.id = rep_id
    rep.name = _require_str(data["name"], field=f"{context}.name")
    venue_id = _require_str(data["venue"], field=f"{context}.venue")
    if venue_id not in venues:
        raise ValueError(f"{context}.venue 引用未知会场: {venue_id}")
    rep.venue = venues[venue_id]
    rep.delegation = _require_str(data["delegation"], field=f"{context}.delegation")
    rep.role = _require_str(data["role"], field=f"{context}.role")

    public = data["public"]
    private = data["private"]
    persona = data["persona"]
    if not isinstance(public, dict):
        raise ValueError(f"{context}.public 须为对象")
    if not isinstance(private, dict):
        raise ValueError(f"{context}.private 须为对象")
    if not isinstance(persona, dict):
        raise ValueError(f"{context}.persona 须为对象")

    forbid_keys(public, {"id", *REP_FORBIDDEN_TARGET_KEYS}, context=f"{context}.public")
    forbid_keys(private, REP_FORBIDDEN_TARGET_KEYS, context=f"{context}.private")

    require_keys(
        public,
        {"title", "position", "target", "formal_powers", "limits"},
        context=f"{context}.public",
    )
    require_keys(
        private,
        {"target", "red_lines", "bargaining_space", "private_information", "relationships"},
        context=f"{context}.private",
    )
    require_keys(
        persona,
        {"personality", "speech_style", "decision_tendency", "honesty"},
        context=f"{context}.persona",
    )

    rep.title = _require_str(public["title"], field=f"{context}.public.title")
    rep.position = _require_str(public["position"], field=f"{context}.public.position")
    rep.public_target = _parse_str_list(public["target"], field=f"{context}.public.target")
    rep.public_formal_powers = _parse_str_list(
        public["formal_powers"],
        field=f"{context}.public.formal_powers",
    )
    rep.public_limits = _parse_str_list(public["limits"], field=f"{context}.public.limits")

    rep.private_target = _parse_private_targets(
        private["target"],
        field=f"{context}.private.target",
    )
    rep.private_red_lines = _parse_str_list(
        private["red_lines"],
        field=f"{context}.private.red_lines",
    )
    rep.private_bargaining_space = _parse_str_list(
        private["bargaining_space"],
        field=f"{context}.private.bargaining_space",
    )
    rep.private_information = _parse_str_list(
        private["private_information"],
        field=f"{context}.private.private_information",
    )
    rep.relationships = _parse_relationships(
        private["relationships"],
        field=f"{context}.private.relationships",
    )

    rep._persona = {
        "personality": _require_str(persona["personality"], field=f"{context}.persona.personality"),
        "speech_style": _require_str(persona["speech_style"], field=f"{context}.persona.speech_style"),
        "decision_tendency": _require_str(
            persona["decision_tendency"],
            field=f"{context}.persona.decision_tendency",
        ),
        "honesty": _parse_honesty(persona["honesty"], field=f"{context}.persona.honesty"),
    }
    rep._agent_directive = _require_str(
        data["agent_directive"],
        field=f"{context}.agent_directive",
    )
    return rep


def _validate_cross_references(
    scenario: Scenario,
    venues_by_id: dict[str, Venue],
    representatives_by_id: dict[str, Representative],
) -> None:
    rep_ids = set(representatives_by_id)
    venue_ids = set(venues_by_id)

    for venue in scenario.venues:
        context = f"会场 {venue.id}"
        if venue.chair != "none" and venue.chair not in rep_ids:
            raise ValueError(f"{context}.chair 引用未知代表: {venue.chair}")
        if venue.chair != "none" and venue.chair not in venue.seats:
            raise ValueError(f"{context}.chair 必须是 none 或 seats 中的代表 ID")

        seat_ids = set(venue.seats)
        if len(seat_ids) != len(venue.seats):
            raise ValueError(f"{context}.seats 存在重复代表 ID")

        for seat_id in venue.seats:
            if seat_id not in rep_ids:
                raise ValueError(f"{context}.seats 引用未知代表: {seat_id}")

    for rep in scenario.representatives:
        context = f"代表 {rep.id}"
        if rep.venue is None or rep.venue.id not in venue_ids:
            raise ValueError(f"{context}.venue 引用未知会场")
        for related_id in rep.relationships:
            if related_id not in rep_ids:
                raise ValueError(f"{context}.relationships 引用未知代表: {related_id}")

    all_seated = {
        seat_id
        for venue in scenario.venues
        for seat_id in venue.seats
    }
    missing_reps = all_seated - rep_ids
    if missing_reps:
        joined = "、".join(sorted(missing_reps))
        raise ValueError(f"venue.seats 中的代表缺少角色文件: {joined}")

    unused_reps = rep_ids - all_seated
    if unused_reps:
        joined = "、".join(sorted(unused_reps))
        raise ValueError(f"角色文件存在但未出现在任何 venue.seats 中: {joined}")


def _require_str(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 须为非空字符串")
    return value.strip()


def _parse_str_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} 须为非空列表")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field}[{index}] 须为非空字符串")
        result.append(item.strip())
    return result


def _parse_private_targets(value: Any, *, field: str) -> list[PrivateTarget]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} 须为非空列表")
    result: list[PrivateTarget] = []
    for index, item in enumerate(value):
        item_field = f"{field}[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{item_field} 须为对象")
        require_keys(item, {"id", "objective", "importance"}, context=item_field)
        result.append(
            PrivateTarget(
                id=_require_str(item["id"], field=f"{item_field}.id"),
                objective=_require_str(item["objective"], field=f"{item_field}.objective"),
                importance=_require_str(item["importance"], field=f"{item_field}.importance"),
            )
        )
    return result


def _parse_relationships(value: Any, *, field: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} 须为映射")
    result: dict[str, str] = {}
    for rep_id, note in value.items():
        if not isinstance(rep_id, str) or not rep_id.strip():
            raise ValueError(f"{field} 的键须为非空代表 ID")
        if not isinstance(note, str) or not note.strip():
            raise ValueError(f"{field}.{rep_id} 须为非空字符串")
        result[rep_id.strip()] = note.strip()
    return result


def _parse_honesty(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} 须为 0 至 1 的数值")
    numeric = float(value)
    if numeric < 0 or numeric > 1:
        raise ValueError(f"{field} 须为 0 至 1 的数值")
    return numeric
