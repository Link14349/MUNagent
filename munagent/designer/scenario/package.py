"""场景包加载/校验/保存 — 见 docs/design/02-scenario-design.md §3."""

from __future__ import annotations

import io
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

_SCENARIO_ID_RE = re.compile(r"^[a-z0-9-]+$")
_HIDDEN_PREFIXES = ("chats/", ".history/")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def builtin_scenarios_dir() -> Path:
    return _repo_root() / "scenarios"


def user_scenarios_dir() -> Path:
    return Path.home() / ".munagent" / "scenarios"


class EndCondition(BaseModel):
    """推演终局条件 — 定义在 crisis_arcs.yaml, 非 manifest."""

    type: str
    at: str | None = None
    desc: str | None = None

    @model_validator(mode="after")
    def check_type_fields(self) -> EndCondition:
        if self.type == "story_time_reached" and not self.at:
            raise ValueError("end_conditions: story_time_reached 须填写 at")
        if self.type == "dm_judgement" and not self.desc:
            raise ValueError("end_conditions: dm_judgement 须填写 desc")
        return self


class Manifest(BaseModel):
    id: str
    title: str
    author: str = ""
    version: str = "1.0.0"
    created: str = ""
    language: str = "zh"
    start_story_time: str
    description: str = Field(default="", description="一句话简介, ≤100 字")
    content: str = Field(default="", description="长梗概, ≤500 字")

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not _SCENARIO_ID_RE.match(v):
            raise ValueError("manifest.id 须为 [a-z0-9-]")
        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        if len(v) > 100:
            raise ValueError("manifest.description 不得超过 100 字")
        return v

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        if len(v) > 500:
            raise ValueError("manifest.content 不得超过 500 字")
        return v


class CrisisArcsFile(BaseModel):
    """crisis_arcs.yaml 顶层结构(校验用)."""

    main_arc: list[Any] = Field(default_factory=list)
    random_pool: list[Any] = Field(default_factory=list)
    end_conditions: list[EndCondition] = Field(default_factory=list)


_SEAT_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class VenueSeatEntry(BaseModel):
    id: str
    name: str

    @field_validator("id")
    @classmethod
    def validate_seat_id(cls, v: str) -> str:
        if not _SEAT_ID_RE.match(v):
            raise ValueError(f"席位 id 须为 [a-z][a-z0-9_]*: {v}")
        return v


class VenueEntry(BaseModel):
    id: str
    name: str
    kind: str = "main"
    timezone: str = "Asia/Shanghai"
    presiding_seat: str | None = None
    decision_rule: dict[str, Any] = Field(default_factory=dict)
    initial_agenda: str = ""
    initial_phase: str = "ModeratedCaucus"
    seats: list[VenueSeatEntry] = Field(default_factory=list)
    clock_rate: dict[str, str] | None = None


class VenuesFile(BaseModel):
    venues: list[VenueEntry]


class SeatPublic(BaseModel):
    title: str = ""
    faction: str = ""
    stance: str = ""


class SeatPrivate(BaseModel):
    secret_goals: list[str] = Field(default_factory=list)
    relationships: list[dict[str, Any]] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)


class SeatPersona(BaseModel):
    personality: str = ""
    speech_style: str = ""
    decision_tendency: str = ""
    honesty: float = Field(default=0.5, ge=0.0, le=1.0)


class PortfolioPower(BaseModel):
    power: str
    limits: str = ""


class SeatFile(BaseModel):
    id: str
    name: str
    venue: str
    public: SeatPublic = Field(default_factory=SeatPublic)
    private: SeatPrivate = Field(default_factory=SeatPrivate)
    portfolio_powers: list[PortfolioPower] = Field(default_factory=list)
    persona: SeatPersona = Field(default_factory=SeatPersona)

    @field_validator("id")
    @classmethod
    def validate_seat_id(cls, v: str) -> str:
        if not _SEAT_ID_RE.match(v):
            raise ValueError(f"席位 id 须为 [a-z][a-z0-9_]*: {v}")
        return v


class ScenarioSummary(BaseModel):
    id: str
    title: str
    author: str = ""
    version: str = ""
    source: Literal["builtin", "user"]
    readonly: bool = False


class ScenarioDetail(BaseModel):
    id: str
    title: str
    source: Literal["builtin", "user"]
    readonly: bool
    manifest: Manifest
    files: dict[str, str]


class ScenarioCreate(BaseModel):
    id: str
    title: str
    author: str = "user"
    start_story_time: str = "2026-01-01T09:00:00+08:00"


class DuplicateScenarioRequest(BaseModel):
    new_id: str
    new_title: str

    @field_validator("new_id")
    @classmethod
    def validate_new_id(cls, v: str) -> str:
        if not _SCENARIO_ID_RE.match(v):
            raise ValueError("new_id 须为 [a-z0-9-]")
        return v


def _load_yaml(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as exc:
        rel = path.name if path.parent.name == "seats" else path.as_posix()
        raise ValueError(f"YAML 语法错误: {rel}: {exc}") from exc


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _collect_text_files(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if path.suffix in {".yaml", ".yml", ".md", ".txt"}:
            files[rel] = _read_text(path)
    return files


def _validate_package(root: Path) -> Manifest:
    manifest_path = root / "manifest.yaml"
    if not manifest_path.is_file():
        raise ValueError(f"缺少 manifest.yaml: {root}")
    manifest = Manifest.model_validate(_load_yaml(manifest_path))
    if manifest.id != root.name:
        raise ValueError(f"目录名 {root.name} 与 manifest.id {manifest.id} 不一致")
    venues_path = root / "venues.yaml"
    if not venues_path.is_file():
        raise ValueError("缺少 venues.yaml")
    seats_dir = root / "seats"
    if not seats_dir.is_dir():
        raise ValueError("缺少 seats/ 目录")
    seat_files = list(seats_dir.glob("*.yaml"))
    if len(seat_files) < 1:
        raise ValueError("seats/ 至少需要一个席位文件")
    bg = root / "background.md"
    if not bg.is_file():
        raise ValueError("缺少 background.md")
    return manifest


def _is_exportable_rel(rel: str, *, include_raw: bool) -> bool:
    if rel.startswith(_HIDDEN_PREFIXES[0]) or rel.startswith(_HIDDEN_PREFIXES[1]):
        return False
    if rel.startswith("references/raw/") and not include_raw:
        return False
    return True


def _list_copyable_rels(root: Path) -> list[str]:
    rels: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if _is_exportable_rel(rel, include_raw=False) and path.suffix.lower() in {
            ".yaml",
            ".yml",
            ".md",
            ".txt",
        }:
            rels.append(rel)
    return rels


def _scenario_root(scenario_id: str, source: Literal["builtin", "user"]) -> Path:
    base = builtin_scenarios_dir() if source == "builtin" else user_scenarios_dir()
    return base / scenario_id


def _find_scenario(scenario_id: str) -> tuple[Path, Literal["builtin", "user"]]:
    user_path = user_scenarios_dir() / scenario_id
    if user_path.is_dir():
        return user_path, "user"
    builtin_path = builtin_scenarios_dir() / scenario_id
    if builtin_path.is_dir():
        return builtin_path, "builtin"
    raise FileNotFoundError(f"场景包不存在: {scenario_id}")


def list_scenarios() -> list[ScenarioSummary]:
    items: list[ScenarioSummary] = []
    seen: set[str] = set()
    for source, base in (("builtin", builtin_scenarios_dir()), ("user", user_scenarios_dir())):
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue
            try:
                manifest = _validate_package(child)
            except ValueError:
                continue
            if manifest.id in seen:
                continue
            seen.add(manifest.id)
            items.append(
                ScenarioSummary(
                    id=manifest.id,
                    title=manifest.title,
                    author=manifest.author,
                    version=manifest.version,
                    source=source,  # type: ignore[arg-type]
                    readonly=source == "builtin",
                )
            )
    return items


def load_scenario(scenario_id: str) -> ScenarioDetail:
    root, source = _find_scenario(scenario_id)
    manifest = _validate_package(root)
    return ScenarioDetail(
        id=manifest.id,
        title=manifest.title,
        source=source,
        readonly=source == "builtin",
        manifest=manifest,
        files=_collect_text_files(root),
    )


def create_scenario(body: ScenarioCreate) -> ScenarioDetail:
    user_scenarios_dir().mkdir(parents=True, exist_ok=True)
    root = user_scenarios_dir() / body.id
    if root.exists():
        raise ValueError(f"场景包已存在: {body.id}")
    root.mkdir()
    (root / "seats").mkdir()
    manifest = Manifest(
        id=body.id,
        title=body.title,
        author=body.author,
        created="",
        start_story_time=body.start_story_time,
        description="",
        content="",
    )
    (root / "manifest.yaml").write_text(
        yaml.safe_dump(manifest.model_dump(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (root / "seats" / "placeholder.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "placeholder",
                "name": "待定义",
                "venue": "main",
                "public": {"title": "", "faction": "", "stance": ""},
                "private": {"secret_goals": [], "relationships": [], "resources": []},
                "portfolio_powers": [],
                "persona": {
                    "personality": "",
                    "speech_style": "",
                    "decision_tendency": "",
                    "honesty": 0.5,
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (root / "venues.yaml").write_text(
        yaml.safe_dump(
            {
                "venues": [
                    {
                        "id": "main",
                        "name": "主会场",
                        "kind": "main",
                        "timezone": "Asia/Shanghai",
                        "decision_rule": {"pass_threshold": "majority", "veto_seats": []},
                        "initial_agenda": "待定",
                        "initial_phase": "ModeratedCaucus",
                        "seats": [{"id": "placeholder", "name": "待定义"}],
                    }
                ]
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (root / "background.md").write_text(f"# {body.title}\n\n(待编写)\n", encoding="utf-8")
    (root / "crisis_arcs.yaml").write_text(
        yaml.safe_dump(
            {"main_arc": [], "random_pool": [], "end_conditions": []},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return load_scenario(body.id)


def save_scenario_files(scenario_id: str, files: dict[str, str]) -> ScenarioDetail:
    root, source = _find_scenario(scenario_id)
    if source == "builtin":
        raise PermissionError("内置场景包只读")
    for rel, content in files.items():
        if ".." in Path(rel).parts:
            raise ValueError(f"非法路径: {rel}")
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return load_scenario(scenario_id)


def delete_scenario(scenario_id: str) -> None:
    root, source = _find_scenario(scenario_id)
    if source == "builtin":
        raise PermissionError("内置场景包不可删除")
    shutil.rmtree(root)


def duplicate_scenario(scenario_id: str, new_id: str, new_title: str) -> ScenarioDetail:
    src_root, _ = _find_scenario(scenario_id)
    user_scenarios_dir().mkdir(parents=True, exist_ok=True)
    dst_root = user_scenarios_dir() / new_id
    if dst_root.exists():
        raise ValueError(f"场景包已存在: {new_id}")
    created = create_scenario(
        ScenarioCreate(id=new_id, title=new_title, author="user", start_story_time="2026-01-01T09:00:00+08:00")
    )
    dst_root = user_scenarios_dir() / created.id
    for rel in _list_copyable_rels(src_root):
        if rel.startswith("references/raw/"):
            continue
        src = src_root / rel
        dst = dst_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    manifest_path = dst_root / "manifest.yaml"
    manifest = Manifest.model_validate(_load_yaml(manifest_path))
    manifest.id = new_id
    manifest.title = new_title
    manifest_path.write_text(
        yaml.safe_dump(manifest.model_dump(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return load_scenario(new_id)


def export_scenario_zip(scenario_id: str, *, include_raw: bool = False) -> bytes:
    root, _ = _find_scenario(scenario_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if not _is_exportable_rel(rel, include_raw=include_raw):
                continue
            zf.write(path, arcname=f"{scenario_id}/{rel}")
    return buf.getvalue()
