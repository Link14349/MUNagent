"""场景包单文件操作与文件树 — 设计器人类编辑用."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from munagent.scenario.package import (
    Manifest,
    _find_scenario,
    _load_yaml,
    _read_text,
    _validate_package,
)

_TEXT_SUFFIXES = {".yaml", ".yml", ".md", ".txt"}
_HIDDEN_PREFIXES = ("chats/", ".history/")


class ValidationIssue(BaseModel):
    level: Literal["error", "warning"]
    message: str
    path: str | None = None


class FileNode(BaseModel):
    name: str
    path: str
    kind: Literal["file", "dir"]
    children: list[FileNode] | None = None


class FileContent(BaseModel):
    path: str
    content: str


class PutFileResult(BaseModel):
    validation: list[ValidationIssue]


class RenameFileRequest(BaseModel):
    new_path: str


def _assert_writable(source: Literal["builtin", "user"]) -> None:
    if source == "builtin":
        raise PermissionError("内置场景包只读")


def _normalize_rel(path: str) -> str:
    p = Path(path)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"非法路径: {path}")
    return p.as_posix()


def _is_tree_visible(rel: str) -> bool:
    return not any(rel.startswith(prefix) for prefix in _HIDDEN_PREFIXES)


def _is_text_file(path: Path) -> bool:
    return path.suffix.lower() in _TEXT_SUFFIXES


def _resolve_file(root: Path, rel: str) -> Path:
    rel = _normalize_rel(rel)
    target = (root / rel).resolve()
    root_resolved = root.resolve()
    if not str(target).startswith(str(root_resolved)):
        raise ValueError(f"非法路径: {rel}")
    return target


def validate_package_issues(root: Path) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    try:
        _validate_package(root)
    except ValueError as exc:
        msg = str(exc)
        path: str | None = None
        if "manifest.yaml" in msg:
            path = "manifest.yaml"
        elif "venues.yaml" in msg:
            path = "venues.yaml"
        elif "background.md" in msg:
            path = "background.md"
        elif "seats/" in msg:
            path = "seats/"
        issues.append(ValidationIssue(level="error", message=msg, path=path))
    seats_dir = root / "seats"
    if seats_dir.is_dir() and not list(seats_dir.glob("*.yaml")):
        issues.append(ValidationIssue(level="warning", message="seats/ 目录为空", path="seats/"))
    if not (root / "crisis_arcs.yaml").is_file():
        issues.append(ValidationIssue(level="warning", message="缺少 crisis_arcs.yaml", path="crisis_arcs.yaml"))
    return issues


def list_content_paths(root: Path) -> list[str]:
    paths: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if not _is_tree_visible(rel):
            continue
        if _is_text_file(path):
            paths.append(rel)
    return paths


def build_file_tree(root: Path) -> list[FileNode]:
    paths = list_content_paths(root)
    return _build_tree(paths)


def _build_tree(paths: list[str]) -> list[FileNode]:
    root_nodes: list[FileNode] = []
    for path in paths:
        parts = path.split("/")
        level = root_nodes
        for i, name in enumerate(parts):
            is_file = i == len(parts) - 1
            full = "/".join(parts[: i + 1])
            node = next((n for n in level if n.name == name), None)
            if node is None:
                node = FileNode(
                    name=name,
                    path=full,
                    kind="file" if is_file else "dir",
                    children=[] if not is_file else None,
                )
                level.append(node)
            if not is_file and node.children is not None:
                level = node.children
    _sort_nodes(root_nodes)
    return root_nodes


def _sort_nodes(nodes: list[FileNode]) -> None:
    nodes.sort(key=lambda n: (0 if n.kind == "dir" else 1, n.name))
    for n in nodes:
        if n.children:
            _sort_nodes(n.children)


def get_file(scenario_id: str, path: str) -> FileContent:
    root, _ = _find_scenario(scenario_id)
    rel = _normalize_rel(path)
    target = _resolve_file(root, rel)
    if not target.is_file():
        raise FileNotFoundError(f"文件不存在: {rel}")
    if not _is_text_file(target):
        raise ValueError(f"不支持的文件类型: {rel}")
    return FileContent(path=rel, content=_read_text(target))


def put_file(scenario_id: str, path: str, content: str) -> PutFileResult:
    root, source = _find_scenario(scenario_id)
    _assert_writable(source)
    rel = _normalize_rel(path)
    if not _is_tree_visible(rel):
        raise ValueError(f"不允许写入: {rel}")
    target = _resolve_file(root, rel)
    if target.suffix.lower() not in _TEXT_SUFFIXES:
        raise ValueError(f"不支持的文件类型: {rel}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    if rel == "manifest.yaml":
        data = _load_yaml(target)
        manifest = Manifest.model_validate(data)
        if manifest.id != scenario_id:
            raise ValueError("manifest.id 必须与场景 ID 一致")
    return PutFileResult(validation=validate_package_issues(root))


def delete_file(scenario_id: str, path: str) -> PutFileResult:
    root, source = _find_scenario(scenario_id)
    _assert_writable(source)
    rel = _normalize_rel(path)
    if rel in {"manifest.yaml", "venues.yaml", "background.md"}:
        raise ValueError(f"不可删除核心文件: {rel}")
    if not _is_tree_visible(rel):
        raise ValueError(f"不允许删除: {rel}")
    target = _resolve_file(root, rel)
    if not target.is_file():
        raise FileNotFoundError(f"文件不存在: {rel}")
    target.unlink()
    return PutFileResult(validation=validate_package_issues(root))


def rename_file(scenario_id: str, path: str, new_path: str) -> PutFileResult:
    root, source = _find_scenario(scenario_id)
    _assert_writable(source)
    rel = _normalize_rel(path)
    new_rel = _normalize_rel(new_path)
    if not _is_tree_visible(rel) or not _is_tree_visible(new_rel):
        raise ValueError("不允许重命名系统目录内文件")
    src = _resolve_file(root, rel)
    dst = _resolve_file(root, new_rel)
    if not src.is_file():
        raise FileNotFoundError(f"文件不存在: {rel}")
    if dst.exists():
        raise ValueError(f"目标已存在: {new_rel}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return PutFileResult(validation=validate_package_issues(root))


def scenario_design_meta(scenario_id: str) -> tuple[str, bool, list[FileNode], list[ValidationIssue]]:
    root, source = _find_scenario(scenario_id)
    manifest_path = root / "manifest.yaml"
    title = scenario_id
    if manifest_path.is_file():
        try:
            title = Manifest.model_validate(_load_yaml(manifest_path)).title
        except ValueError:
            pass
    return title, source == "builtin", build_file_tree(root), validate_package_issues(root)
