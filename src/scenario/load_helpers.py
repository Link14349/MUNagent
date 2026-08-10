"""场景包加载辅助函数：YAML 解析、时间与跨文件校验。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = "0.1"
ALLOWED_CONDITION_TYPES = frozenset({"time_reached", "text"})

INDEX_FORBIDDEN_KEYS = frozenset({
    "id",
    "files",
    "historical_scope",
    "venues",
    "representatives",
    "content_notice",
    "subtitle",
    "date",
    "player_count",
})

REP_FORBIDDEN_TARGET_KEYS = frozenset({
    "public_target",
    "public_targets",
    "private_target",
    "private_targets",
    "priorities",
})

EVENT_FORBIDDEN_KEYS = frozenset({"inference", "historicity", "scope", "effects", "trigger"})


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"缺少文件: {path}")
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} 顶层须为 YAML 对象")
    return data


def require_keys(data: dict[str, Any], keys: set[str], *, context: str) -> None:
    missing = keys - data.keys()
    if missing:
        joined = "、".join(sorted(missing))
        raise ValueError(f"{context} 缺少必需字段: {joined}")


def forbid_keys(data: dict[str, Any], keys: set[str], *, context: str) -> None:
    present = keys & data.keys()
    if present:
        joined = "、".join(sorted(present))
        raise ValueError(f"{context} 包含禁止字段: {joined}")


def parse_iso_datetime(value: str, *, context: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} 须为非空 ISO 8601 时间字符串")
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{context} 不是合法 ISO 8601 时间: {value}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{context} 必须包含 UTC 偏移: {value}")
    return parsed


def parse_condition(raw: dict[str, Any], *, context: str) -> tuple[str, str | datetime]:
    if not isinstance(raw, dict):
        raise ValueError(f"{context} 须为对象")
    require_keys(raw, {"type", "content"}, context=context)
    extra = set(raw.keys()) - {"type", "content"}
    if extra:
        joined = "、".join(sorted(extra))
        raise ValueError(f"{context} 只能包含 type 和 content，多余字段: {joined}")

    cond_type = raw["type"]
    if cond_type not in ALLOWED_CONDITION_TYPES:
        raise ValueError(
            f"{context}.type 只能是 time_reached 或 text，实际为: {cond_type!r}"
        )

    content = raw["content"]
    if cond_type == "time_reached":
        if not isinstance(content, str):
            raise ValueError(f"{context}.content 须为时间字符串")
        return cond_type, parse_iso_datetime(content, context=f"{context}.content")

    if not isinstance(content, str) or not content.strip():
        raise ValueError(f"{context}.content 须为非空字符串")
    return cond_type, content


def validate_scenario_layout(root: Path) -> None:
    if not root.is_dir():
        raise FileNotFoundError(f"场景目录不存在: {root}")

    for name in ("index.yaml", "background.md", "storyline.yaml"):
        if not (root / name).is_file():
            raise FileNotFoundError(f"缺少固定文件: {root / name}")

    venues_dir = root / "venues"
    reps_dir = root / "reps"
    if not venues_dir.is_dir():
        raise FileNotFoundError(f"缺少目录: {venues_dir}")
    if not reps_dir.is_dir():
        raise FileNotFoundError(f"缺少目录: {reps_dir}")

    venue_files = sorted(venues_dir.glob("*.yaml"))
    rep_files = sorted(reps_dir.glob("*.yaml"))
    if not venue_files:
        raise ValueError(f"{venues_dir} 中至少需要一个 YAML 文件")
    if not rep_files:
        raise ValueError(f"{reps_dir} 中至少需要一个 YAML 文件")

    mechanism_yaml = root / "mechanism.yaml"
    if mechanism_yaml.exists():
        raise ValueError(f"禁止存在 mechanism.yaml: {mechanism_yaml}")

    mechanism_py = root / "mechanism.py"
    if mechanism_py.is_file() and mechanism_py.stat().st_size != 0:
        raise ValueError(f"mechanism.py 须为 0 字节占位文件: {mechanism_py}")
