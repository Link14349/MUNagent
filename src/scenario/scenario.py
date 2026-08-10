from __future__ import annotations

from datetime import datetime
from pathlib import Path

from condition.condition import Condition
from event.eventlist import EventList, PullUpEvent
from scenario.load_helpers import (
    EVENT_FORBIDDEN_KEYS,
    INDEX_FORBIDDEN_KEYS,
    SCHEMA_VERSION,
    forbid_keys,
    load_yaml,
    parse_condition,
    parse_iso_datetime,
    require_keys,
    validate_scenario_layout,
)
from scenario.representative import Representative
from scenario.venue import Venue


class Scenario:
    title: str
    background: str
    targets: list[str]
    description: str
    timezone: str
    time: datetime | None
    event_pool: list[PullUpEvent]
    end_conditions: list[Condition]
    venues: list[Venue]
    representatives: list[Representative]
    event_list: EventList | None

    def __init__(self) -> None:
        self.title = ""
        self.background = ""
        self.targets = []
        self.description = ""
        self.timezone = ""
        self.time = None
        self.event_pool = []
        self.end_conditions = []
        self.venues = []
        self.representatives = []
        self.event_list = None

    def load(self, scenario_path: str) -> None:
        root = Path(scenario_path).resolve()
        validate_scenario_layout(root)

        index = load_yaml(root / "index.yaml")
        self._load_index(index)

        background_path = root / "background.md"
        self.background = background_path.read_text(encoding="utf-8").strip()
        if not self.background:
            raise ValueError(f"background.md 不能为空: {background_path}")

        storyline = load_yaml(root / "storyline.yaml")
        self._load_storyline(storyline)

        venues_by_id: dict[str, Venue] = {}
        for venue_path in sorted((root / "venues").glob("*.yaml")):
            venue = Venue(self)
            venue.load(str(venue_path))
            if venue.id in venues_by_id:
                raise ValueError(f"重复的会场 ID: {venue.id}")
            venues_by_id[venue.id] = venue
        self.venues = list(venues_by_id.values())

        representatives_by_id: dict[str, Representative] = {}
        for rep_path in sorted((root / "reps").glob("*.yaml")):
            rep = Representative()
            rep.load(str(rep_path), venues_by_id)
            if rep.id in representatives_by_id:
                raise ValueError(f"重复的代表 ID: {rep.id}")
            representatives_by_id[rep.id] = rep
        self.representatives = list(representatives_by_id.values())

        self._validate_cross_references(venues_by_id, representatives_by_id)
        self.event_list = EventList(self)

    def _load_index(self, index: dict) -> None:
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

        self.title = _require_str(index["title"], field=f"{context}.title")
        self.description = _require_str(index["description"], field=f"{context}.description")
        self.timezone = _require_str(index["timezone"], field=f"{context}.timezone")
        self.time = parse_iso_datetime(
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

    def _load_storyline(self, storyline: dict) -> None:
        context = "storyline.yaml"
        require_keys(storyline, {"targets", "events", "end_conditions"}, context=context)

        targets_raw = storyline["targets"]
        if not isinstance(targets_raw, list) or not targets_raw:
            raise ValueError(f"{context}.targets 须为非空列表")
        self.targets = []
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
            self.targets.append(_require_str(target["description"], field=f"{target_context}.description"))

        events_raw = storyline["events"]
        if not isinstance(events_raw, list):
            raise ValueError(f"{context}.events 须为列表")
        self.event_pool = []
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
            self.event_pool.append(
                PullUpEvent(
                    condition=Condition(cond_type, cond_content, self),
                    content=content,
                    scenario=self,
                )
            )

        end_conditions_raw = storyline["end_conditions"]
        if not isinstance(end_conditions_raw, list) or not end_conditions_raw:
            raise ValueError(f"{context}.end_conditions 须为非空列表")
        self.end_conditions = []
        for index, end_condition in enumerate(end_conditions_raw):
            end_context = f"{context}.end_conditions[{index}]"
            if not isinstance(end_condition, dict):
                raise ValueError(f"{end_context} 须为对象")
            cond_type, cond_content = parse_condition(end_condition, context=end_context)
            self.end_conditions.append(Condition(cond_type, cond_content, self))

    def _validate_cross_references(
        self,
        venues_by_id: dict[str, Venue],
        representatives_by_id: dict[str, Representative],
    ) -> None:
        rep_ids = set(representatives_by_id)
        venue_ids = set(venues_by_id)

        for venue in self.venues:
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

        for rep in self.representatives:
            context = f"代表 {rep.id}"
            if rep.venue is None or rep.venue.id not in venue_ids:
                raise ValueError(f"{context}.venue 引用未知会场")
            for related_id in rep.relationships:
                if related_id not in rep_ids:
                    raise ValueError(f"{context}.relationships 引用未知代表: {related_id}")

        all_seated = {
            seat_id
            for venue in self.venues
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

    def run(self) -> None:
        pass


def _require_str(value, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 须为非空字符串")
    return value.strip()
