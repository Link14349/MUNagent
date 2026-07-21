"""场景包版本快照 — .history/ 目录."""

from __future__ import annotations

import difflib
import random
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from munagent.designer.scenario.package import _find_scenario, _read_text
from munagent.designer.scenario.files import (
    PutFileResult,
    ValidationIssue,
    _is_tree_visible,
    list_content_paths,
    validate_package_issues,
)

_HISTORY_KIND = Literal["auto", "manual", "restore_backup"]
_ROLLING_LIMIT = 30
_SNAP_ID_RE = re.compile(r"^\d{14}-(auto|manual|restore_backup)$")
_SNAP_META_NAME = ".meta.yaml"
_LEGACY_SNAP_META_NAME = "meta.yaml"
_SNAP_META_NAMES = frozenset({_SNAP_META_NAME, _LEGACY_SNAP_META_NAME})


class HistorySnapshot(BaseModel):
    id: str
    created_at: str
    kind: _HISTORY_KIND
    reason: str
    note: str | None = None
    chat_id: str | None = None
    turn: int | None = None


class HistoryDiffEntry(BaseModel):
    path: str
    status: Literal["added", "modified", "deleted"]
    additions: int = 0
    deletions: int = 0
    diff: str | None = None


class CreateSnapshotRequest(BaseModel):
    note: str | None = None


def _history_root(scenario_root: Path) -> Path:
    return scenario_root / ".history"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _format_snap_id(kind: _HISTORY_KIND) -> str:
    d = datetime.now()
    stamp = d.strftime("%Y%m%d%H%M%S")
    return f"{stamp}-{kind}"


def _resolve_snap_meta_path(snap_dir: Path) -> Path:
    for name in (_SNAP_META_NAME, _LEGACY_SNAP_META_NAME):
        path = snap_dir / name
        if path.is_file():
            return path
    raise ValueError(f"快照缺少 {_SNAP_META_NAME}: {snap_dir.name}")


def _load_snap_meta(snap_dir: Path) -> HistorySnapshot:
    meta_path = _resolve_snap_meta_path(snap_dir)
    data: dict[str, Any] = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
    return HistorySnapshot(
        id=data.get("id", snap_dir.name),
        created_at=data.get("created_at", ""),
        kind=data.get("kind", "manual"),
        reason=data.get("reason", ""),
        note=data.get("note"),
        chat_id=data.get("chat_id"),
        turn=data.get("turn"),
    )


def _content_paths_in_dir(base: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for rel in list_content_paths(base):
        if rel in _SNAP_META_NAMES:
            continue
        files[rel] = _read_text(base / rel)
    return files


def _copy_content_files(src_root: Path, dst_root: Path) -> None:
    for rel in list_content_paths(src_root):
        src = src_root / rel
        dst = dst_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _prune_rolling(history_dir: Path) -> None:
    snaps = [p for p in history_dir.iterdir() if p.is_dir()]
    rolling = []
    for snap in snaps:
        try:
            meta = _load_snap_meta(snap)
        except ValueError:
            continue
        if meta.kind in ("auto", "restore_backup"):
            rolling.append((meta.created_at, snap))
    rolling.sort(key=lambda x: x[0])
    while len(rolling) > _ROLLING_LIMIT:
        _, oldest = rolling.pop(0)
        shutil.rmtree(oldest)


def create_snapshot(
    scenario_id: str,
    *,
    kind: _HISTORY_KIND = "manual",
    reason: str | None = None,
    note: str | None = None,
    chat_id: str | None = None,
    turn: int | None = None,
) -> HistorySnapshot:
    root, source = _find_scenario(scenario_id)
    if source == "builtin":
        raise PermissionError("内置场景包只读")
    history_dir = _history_root(root)
    history_dir.mkdir(parents=True, exist_ok=True)
    snap_id = _format_snap_id(kind)
    snap_dir = history_dir / snap_id
    if snap_dir.exists():
        snap_id = f"{snap_id}-{random.randint(1000, 9999)}"
        snap_dir = history_dir / snap_id
    snap_dir.mkdir()
    _copy_content_files(root, snap_dir)
    created_at = _now_iso()
    default_reason = {
        "manual": note or "手动存档",
        "auto": reason or "自动存档",
        "restore_backup": reason or "恢复前备份",
    }[kind]
    meta = {
        "id": snap_id,
        "created_at": created_at,
        "kind": kind,
        "reason": reason or default_reason,
        "note": note,
        "chat_id": chat_id,
        "turn": turn,
    }
    (snap_dir / _SNAP_META_NAME).write_text(
        yaml.safe_dump(meta, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    if kind in ("auto", "restore_backup"):
        _prune_rolling(history_dir)
    return HistorySnapshot(**{k: v for k, v in meta.items() if k in HistorySnapshot.model_fields})


def list_snapshots(scenario_id: str) -> list[HistorySnapshot]:
    root, _ = _find_scenario(scenario_id)
    history_dir = _history_root(root)
    if not history_dir.is_dir():
        return []
    items: list[HistorySnapshot] = []
    for child in history_dir.iterdir():
        if not child.is_dir():
            continue
        try:
            items.append(_load_snap_meta(child))
        except ValueError:
            continue
    items.sort(key=lambda s: s.created_at, reverse=True)
    return items


def _unified_diff(old: str, new: str, path: str) -> str:
    lines = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return "".join(lines)


def _diff_stats(diff: str) -> tuple[int, int]:
    adds = dels = 0
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            adds += 1
        elif line.startswith("-") and not line.startswith("---"):
            dels += 1
    return adds, dels


def history_diff(scenario_id: str, snap_id: str) -> list[HistoryDiffEntry]:
    root, _ = _find_scenario(scenario_id)
    snap_dir = _history_root(root) / snap_id
    if not snap_dir.is_dir():
        raise FileNotFoundError(f"快照不存在: {snap_id}")
    current = _content_paths_in_dir(root)
    snap_files = _content_paths_in_dir(snap_dir)
    all_paths = sorted(set(current) | set(snap_files))
    entries: list[HistoryDiffEntry] = []
    for path in all_paths:
        cur = current.get(path)
        old = snap_files.get(path)
        if cur == old:
            continue
        if cur is None and old is not None:
            diff = _unified_diff(old, "", path)
            _, dels = _diff_stats(diff)
            entries.append(HistoryDiffEntry(path=path, status="deleted", deletions=dels, diff=diff))
        elif old is None and cur is not None:
            diff = _unified_diff("", cur, path)
            adds, _ = _diff_stats(diff)
            entries.append(HistoryDiffEntry(path=path, status="added", additions=adds, diff=diff))
        else:
            diff = _unified_diff(old or "", cur or "", path)
            adds, dels = _diff_stats(diff)
            entries.append(
                HistoryDiffEntry(
                    path=path,
                    status="modified",
                    additions=adds,
                    deletions=dels,
                    diff=diff,
                )
            )
    return entries


def restore_snapshot(scenario_id: str, snap_id: str, *, active_task: bool = False) -> PutFileResult:
    if active_task:
        raise RuntimeError("有 Agent 任务在运行, 请先中止")
    root, source = _find_scenario(scenario_id)
    if source == "builtin":
        raise PermissionError("内置场景包只读")
    snap_dir = _history_root(root) / snap_id
    if not snap_dir.is_dir():
        raise FileNotFoundError(f"快照不存在: {snap_id}")
    create_snapshot(
        scenario_id,
        kind="restore_backup",
        reason=f"恢复到 {snap_id} 之前的自动备份",
    )
    current_paths = set(list_content_paths(root))
    snap_paths = set(list_content_paths(snap_dir))
    for rel in current_paths - snap_paths:
        if _is_tree_visible(rel):
            (root / rel).unlink(missing_ok=True)
    for rel in snap_paths:
        src = snap_dir / rel
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return PutFileResult(validation=validate_package_issues(root))


def delete_snapshot(scenario_id: str, snap_id: str) -> None:
    root, source = _find_scenario(scenario_id)
    if source == "builtin":
        raise PermissionError("内置场景包只读")
    snap_dir = _history_root(root) / snap_id
    if not snap_dir.is_dir():
        raise FileNotFoundError(f"快照不存在: {snap_id}")
    meta = _load_snap_meta(snap_dir)
    if meta.kind != "manual":
        raise PermissionError("仅可删除手动快照")
    shutil.rmtree(snap_dir)
