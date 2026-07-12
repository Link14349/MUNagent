"""场景包单文件与历史快照测试."""

from __future__ import annotations

from pathlib import Path

import pytest

from munagent.designer.scenario import chats as chat_svc
from munagent.designer.scenario import package as scenario_svc
from munagent.designer.scenario import files as file_svc
from munagent.designer.scenario import history as history_svc
from munagent.designer.scenario.package import ScenarioCreate


@pytest.fixture()
def user_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(scenario_svc, "user_scenarios_dir", lambda: tmp_path)
    scenario_svc.create_scenario(ScenarioCreate(id="edit-me", title="可编辑"))
    return tmp_path / "edit-me"


def test_put_and_get_file(user_root: Path) -> None:
    file_svc.put_file("edit-me", "notes.md", "# 备注\n")
    got = file_svc.get_file("edit-me", "notes.md")
    assert got.content.startswith("# 备注")
    _, _, tree, _ = file_svc.scenario_design_meta("edit-me")
    flat = list(_flatten(tree))
    assert any(n.path == "notes.md" for n in flat if n.kind == "file")


def _flatten(nodes):
    for n in nodes:
        yield n
        if n.children:
            yield from _flatten(n.children)


def test_manual_snapshot_and_restore(user_root: Path) -> None:
    file_svc.put_file("edit-me", "background.md", "# 版本 A\n")
    snap = history_svc.create_snapshot("edit-me", kind="manual", note="改背景前")
    file_svc.put_file("edit-me", "background.md", "# 版本 B\n")
    assert file_svc.get_file("edit-me", "background.md").content.startswith("# 版本 B")
    history_svc.restore_snapshot("edit-me", snap.id)
    assert file_svc.get_file("edit-me", "background.md").content.startswith("# 版本 A")


def test_duplicate_and_export(user_root: Path) -> None:
    detail = scenario_svc.duplicate_scenario("edit-me", "edit-copy", "副本")
    assert detail.id == "edit-copy"
    data = scenario_svc.export_scenario_zip("edit-copy")
    assert b"edit-copy/manifest.yaml" in data or b"PK" in data[:4]


def test_create_chat(user_root: Path) -> None:
    chat = chat_svc.create_chat("edit-me", "初始场景生成")
    chats = chat_svc.list_chats("edit-me")
    assert len(chats) == 1
    assert chats[0].id == chat.id


def test_venues_seats_consistency_builtin() -> None:
    from munagent.designer.scenario import package as scenario_svc

    root = scenario_svc.builtin_scenarios_dir() / "cabinet-crisis"
    issues = file_svc.validate_package_issues(root)
    errors = [i for i in issues if i.level == "error"]
    assert errors == []
