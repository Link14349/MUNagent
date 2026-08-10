from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from scenario.load_helpers import REP_FORBIDDEN_TARGET_KEYS, forbid_keys, load_yaml, require_keys

if TYPE_CHECKING:
    from scenario.venue import Venue


class PrivateTarget:
    def __init__(self, id: str, objective: str, importance: str):
        self.id = id
        self.objective = objective
        self.importance = importance


class Representative:
    def __init__(self):
        self.id: str = ""
        self.name: str = ""
        self.venue: Venue | None = None
        self.delegation: str = ""
        self.role: str = ""

        self.title: str = ""
        self.position: str = ""
        self.public_target: list[str] = []
        self.public_formal_powers: list[str] = []
        self.public_limits: list[str] = []
        self.private_target: list[PrivateTarget] = []
        self.private_red_lines: list[str] = []
        self.private_bargaining_space: list[str] = []
        self.private_information: list[str] = []
        self.relationships: dict[str, str] = {}

        self._persona: dict[str, str | float] = {}
        self._agent_directive: str = ""

    def load(self, representative_path: str, venues: dict[str, Venue]) -> None:
        path = Path(representative_path)
        self.id = path.stem
        if not self.id:
            raise ValueError(f"代表文件名无效: {path}")

        data = load_yaml(path)
        context = f"代表 {self.id}"

        forbid_keys(data, {"id"}, context=context)
        require_keys(
            data,
            {"name", "venue", "delegation", "role", "public", "private", "persona", "agent_directive"},
            context=context,
        )

        self.name = _require_str(data["name"], field=f"{context}.name")
        venue_id = _require_str(data["venue"], field=f"{context}.venue")
        if venue_id not in venues:
            raise ValueError(f"{context}.venue 引用未知会场: {venue_id}")
        self.venue = venues[venue_id]
        self.delegation = _require_str(data["delegation"], field=f"{context}.delegation")
        self.role = _require_str(data["role"], field=f"{context}.role")

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

        self.title = _require_str(public["title"], field=f"{context}.public.title")
        self.position = _require_str(public["position"], field=f"{context}.public.position")
        self.public_target = _parse_str_list(public["target"], field=f"{context}.public.target")
        self.public_formal_powers = _parse_str_list(
            public["formal_powers"],
            field=f"{context}.public.formal_powers",
        )
        self.public_limits = _parse_str_list(public["limits"], field=f"{context}.public.limits")

        self.private_target = _parse_private_targets(
            private["target"],
            field=f"{context}.private.target",
        )
        self.private_red_lines = _parse_str_list(
            private["red_lines"],
            field=f"{context}.private.red_lines",
        )
        self.private_bargaining_space = _parse_str_list(
            private["bargaining_space"],
            field=f"{context}.private.bargaining_space",
        )
        self.private_information = _parse_str_list(
            private["private_information"],
            field=f"{context}.private.private_information",
        )
        self.relationships = _parse_relationships(
            private["relationships"],
            field=f"{context}.private.relationships",
        )

        self._persona = {
            "personality": _require_str(persona["personality"], field=f"{context}.persona.personality"),
            "speech_style": _require_str(persona["speech_style"], field=f"{context}.persona.speech_style"),
            "decision_tendency": _require_str(
                persona["decision_tendency"],
                field=f"{context}.persona.decision_tendency",
            ),
            "honesty": _parse_honesty(persona["honesty"], field=f"{context}.persona.honesty"),
        }
        self._agent_directive = _require_str(
            data["agent_directive"],
            field=f"{context}.agent_directive",
        )


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
