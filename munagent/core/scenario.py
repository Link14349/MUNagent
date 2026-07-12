"""场景包的加载与校验. 见 docs/design/02-scenario-design.md §3."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from munagent.core.timezone import to_utc_iso


class EndCondition(BaseModel):
    type: Literal["story_time_reached", "dm_judgement"]
    at: str | None = None  # story_time_reached
    desc: str | None = None  # dm_judgement


class Manifest(BaseModel):
    id: str
    title: str
    author: str = ""
    version: str = "1.0.0"
    created: str = ""
    language: str = "zh"
    start_story_time: str
    end_conditions: list[EndCondition] = Field(default_factory=list)

    @field_validator("start_story_time")
    @classmethod
    def _must_have_tz(cls, v: str) -> str:
        _require_tz(v)
        return to_utc_iso(v)


class DecisionRule(BaseModel):
    pass_threshold: Literal["majority", "two_thirds", "unanimous"] = "majority"
    veto_seats: list[str] = Field(default_factory=list)


class ClockRate(BaseModel):
    per_mod_speech: str = "5m"
    per_unmod_round: str = "15m"


class VenueSpec(BaseModel):
    id: str
    name: str
    kind: Literal["main", "sub"] = "main"
    timezone: str = "UTC"
    presiding_seat: str | None = None  # 戏内主持席(04§3, D15); None=中立主席
    decision_rule: DecisionRule = Field(default_factory=DecisionRule)
    initial_agenda: str = ""
    initial_phase: str = "ModeratedCaucus"
    seats: list[str] = Field(default_factory=list)
    clock_rate: ClockRate = Field(default_factory=ClockRate)

    @model_validator(mode="after")
    def _presiding_in_seats(self) -> VenueSpec:
        if self.presiding_seat is not None and self.seats:
            if self.presiding_seat not in self.seats:
                raise ValueError(
                    f"presiding_seat({self.presiding_seat}) 不在会场席位列表中"
                )
        return self

    @field_validator("timezone")
    @classmethod
    def _valid_iana(cls, v: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(v)
        except ZoneInfoNotFoundError as e:
            raise ValueError(f"非法 IANA 时区名: {v}") from e
        return v


class PublicInfo(BaseModel):
    title: str = ""
    faction: str = ""
    stance: str = ""


class PrivateInfo(BaseModel):
    secret_goals: list[str] = Field(default_factory=list)
    relationships: list[dict] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)


class PortfolioPower(BaseModel):
    power: str
    limits: str = ""


class Persona(BaseModel):
    personality: str = ""
    speech_style: str = ""
    decision_tendency: str = ""
    honesty: float = 0.7

    @field_validator("honesty")
    @classmethod
    def _range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("honesty 必须在 0~1 之间")
        return v


class SeatSpec(BaseModel):
    id: str
    name: str
    venue: str
    public: PublicInfo = Field(default_factory=PublicInfo)
    private: PrivateInfo = Field(default_factory=PrivateInfo)
    portfolio_powers: list[PortfolioPower] = Field(default_factory=list)
    persona: Persona = Field(default_factory=Persona)


class StatsEntity(BaseModel):
    id: str
    label: str
    owner: str
    tags: dict[str, str] | None = None
    values: dict[str, int] | None = None


class StatsConfig(BaseModel):
    mode: Literal["none", "tags", "numeric"] = "tags"
    visibility: Literal["owner_only", "faction", "all_public"] = "faction"
    entities: list[StatsEntity] = Field(default_factory=list)


class ArcTrigger(BaseModel):
    type: Literal["story_time", "condition", "manual"] = "story_time"
    at: str | None = None
    condition: str | None = None

    @field_validator("at")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        if v is not None:
            _require_tz(v)
            return to_utc_iso(v)
        return v


class CrisisArc(BaseModel):
    id: str
    trigger: ArcTrigger = Field(default_factory=ArcTrigger)
    content: str = ""
    default_scope: str = "global"


class RandomPoolEntry(BaseModel):
    id: str
    weight: int = 1
    content: str = ""


class TimelineNode(BaseModel):
    """故事时间关键节点(主席团专用): 主席跳时依据, DM推算takes_effect_at的参照."""

    at: str
    label: str = ""
    note: str = ""

    @field_validator("at")
    @classmethod
    def _must_have_tz(cls, v: str) -> str:
        _require_tz(v)
        return to_utc_iso(v)


class CrisisArcs(BaseModel):
    main_arc: list[CrisisArc] = Field(default_factory=list)
    random_pool: list[RandomPoolEntry] = Field(default_factory=list)
    timeline: list[TimelineNode] = Field(default_factory=list)


class Scenario:
    """加载后的场景包, 内存中持有全部子模型."""

    def __init__(
        self,
        path: Path,
        manifest: Manifest,
        background: str,
        venues: list[VenueSpec],
        seats: dict[str, SeatSpec],
        crisis_arcs: CrisisArcs,
        stats: StatsConfig,
        story_design: str = "",
    ) -> None:
        self.path = path
        self.manifest = manifest
        self.background = background
        self.venues = venues
        self.seats = seats
        self.crisis_arcs = crisis_arcs
        self.stats = stats
        self.story_design = story_design  # 剧情走向与时间线设计(主席团专用, 代表不可见)

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def venue_ids(self) -> list[str]:
        return [v.id for v in self.venues]

    def venue(self, venue_id: str) -> VenueSpec:
        for v in self.venues:
            if v.id == venue_id:
                return v
        raise KeyError(f"会场不存在: {venue_id}")

    def seats_of(self, venue_id: str) -> list[SeatSpec]:
        return [self.seats[sid] for sid in self.venue(venue_id).seats if sid in self.seats]

    def stats_for_seat(self, seat_id: str) -> list[StatsEntity]:
        """按 visibility 过滤该席位可见的 stats. 见 02§3."""
        if self.stats.mode == "none":
            return []
        seat = self.seats.get(seat_id)
        if seat is None:
            return []
        result: list[StatsEntity] = []
        for entity in self.stats.entities:
            if self.stats.visibility == "all_public":
                result.append(entity)
            elif self.stats.visibility == "owner_only":
                if entity.owner == f"seat:{seat_id}" or entity.owner == seat_id:
                    result.append(entity)
            elif self.stats.visibility == "faction":
                faction = seat.public.faction
                if entity.owner == f"seat:{seat_id}" or entity.owner == seat_id:
                    result.append(entity)
                elif entity.owner == f"faction:{faction}":
                    result.append(entity)
        return result


def _require_tz(iso_str: str) -> None:
    """校验时间串必须带时区偏移或 Z."""
    if not iso_str:
        return
    if "Z" not in iso_str and "+" not in iso_str and "-" not in iso_str[10:]:
        raise ValueError(f"时间必须带时区偏移或 Z: {iso_str}")


def load_scenario(path: str | Path) -> Scenario:
    """从目录加载场景包. 见 02§3."""
    p = Path(path)
    if not p.is_dir():
        raise FileNotFoundError(f"场景包目录不存在: {p}")

    manifest = Manifest.model_validate(
        yaml.safe_load((p / "manifest.yaml").read_text(encoding="utf-8"))
    )

    bg_path = p / "background.md"
    background = bg_path.read_text(encoding="utf-8") if bg_path.exists() else ""

    venues_data = yaml.safe_load((p / "venues.yaml").read_text(encoding="utf-8"))
    venues = [VenueSpec.model_validate(v) for v in venues_data.get("venues", [])]

    seats: dict[str, SeatSpec] = {}
    seats_dir = p / "seats"
    if seats_dir.is_dir():
        for seat_file in sorted(seats_dir.glob("*.yaml")):
            seat = SeatSpec.model_validate(yaml.safe_load(seat_file.read_text(encoding="utf-8")))
            seats[seat.id] = seat

    crisis_arcs = CrisisArcs()
    arcs_path = p / "crisis_arcs.yaml"
    if arcs_path.exists():
        crisis_arcs = CrisisArcs.model_validate(yaml.safe_load(arcs_path.read_text(encoding="utf-8")))

    stats = StatsConfig(mode="none")
    stats_path = p / "stats.yaml"
    if stats_path.exists():
        stats = StatsConfig.model_validate(yaml.safe_load(stats_path.read_text(encoding="utf-8")))

    story_design = ""
    sd_path = p / "story-design.md"
    if sd_path.exists():
        story_design = sd_path.read_text(encoding="utf-8")

    _validate_references(manifest, venues, seats, crisis_arcs, stats)
    return Scenario(p, manifest, background, venues, seats, crisis_arcs, stats, story_design)


def _validate_references(
    manifest: Manifest,
    venues: list[VenueSpec],
    seats: dict[str, SeatSpec],
    crisis_arcs: CrisisArcs,
    stats: StatsConfig,
) -> None:
    """02§5 一致性检查(简化版, P1 只做引用完整性)."""
    venue_ids = {v.id for v in venues}
    seat_ids = set(seats.keys())

    for v in venues:
        for sid in v.seats:
            if sid not in seat_ids:
                raise ValueError(f"会场 {v.id} 引用了不存在的席位: {sid}")
        for vid in v.decision_rule.veto_seats:
            if vid not in seat_ids:
                raise ValueError(f"会场 {v.id} 的 veto_seats 引用了不存在的席位: {vid}")

    for seat in seats.values():
        if seat.venue not in venue_ids:
            raise ValueError(f"席位 {seat.id} 引用了不存在的会场: {seat.venue}")

    for entity in stats.entities:
        owner = entity.owner
        if owner.startswith("seat:") and owner[5:] not in seat_ids:
            raise ValueError(f"stats entity {entity.id} 的 owner 席位不存在: {owner}")
        # faction:xxx 不强校验, 自由文本
