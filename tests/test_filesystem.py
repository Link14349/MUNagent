"""FileSystem 可见性与提交流程单元测试."""

from __future__ import annotations

from pathlib import Path

import pytest

from filesystem.filesystem import SYSTEM_ACTOR, FileSystem
from scenario.scenario import Scenario

TEMPLATE = Path(__file__).resolve().parent.parent / "scenario-template"

CHURCHILL = "winston_churchill"
STALIN = "joseph_stalin"
EDEN = "anthony_eden"


@pytest.fixture
def scenario() -> Scenario:
    loaded = Scenario()
    loaded.load(str(TEMPLATE))
    return loaded


@pytest.fixture
def fs(scenario: Scenario, tmp_path: Path) -> FileSystem:
    return FileSystem(tmp_path / "run", scenario)


@pytest.fixture
def venue_id(scenario: Scenario) -> str:
    return scenario.venues[0].id


def test_create_rep_file_private_by_default(fs: FileSystem) -> None:
    file = fs.create_rep_file(
        CHURCHILL,
        "notes.md",
        "私有笔记",
        description="丘吉尔私人备忘",
    )
    assert fs.read(f"reps/{CHURCHILL}/notes.md", CHURCHILL) == "私有笔记"
    assert file.owners == frozenset({CHURCHILL})
    assert file.scope == {CHURCHILL}
    assert file.description == "丘吉尔私人备忘"


def test_description_max_length_and_submit_copies(fs: FileSystem) -> None:
    with pytest.raises(ValueError, match="不能超过 20 字"):
        fs.create_rep_file(
            CHURCHILL,
            "long.md",
            "x",
            description="一二三四五六七八九十一二三四五六七八九十多",
        )
    draft = fs.create_rep_file(
        CHURCHILL,
        "draft.md",
        "草案",
        description="百分比草案初稿",
    )
    submitted = draft.submit(CHURCHILL)
    assert submitted.description == "百分比草案初稿"
    with pytest.raises(PermissionError, match="不可修改 description"):
        submitted.set_description(CHURCHILL, "改描述")


def test_set_description_requires_owner_and_persists(fs: FileSystem) -> None:
    path = f"reps/{CHURCHILL}/draft.md"
    draft = fs.create_rep_file(
        CHURCHILL,
        "draft.md",
        "草案",
        description="百分比草案",
    )
    fs.add_scope(path, CHURCHILL, {EDEN})
    with pytest.raises(PermissionError, match="不是文件"):
        fs.set_description(path, EDEN, "篡改简述")

    fs.set_description(path, CHURCHILL, "修订简述")
    assert draft.description == "修订简述"

    reloaded = FileSystem(fs.path, fs.scenario)
    assert reloaded.get(path, CHURCHILL).description == "修订简述"


def test_other_rep_cannot_read_private_file(fs: FileSystem) -> None:
    fs.create_rep_file(CHURCHILL, "notes.md", "私有笔记")
    with pytest.raises(PermissionError, match="不可见|无权读取"):
        fs.read(f"reps/{CHURCHILL}/notes.md", STALIN)


def test_add_scope_allows_read_but_not_write(fs: FileSystem) -> None:
    path = f"reps/{CHURCHILL}/draft.md"
    fs.create_rep_file(CHURCHILL, "draft.md", "草案")
    fs.add_scope(path, CHURCHILL, {EDEN})

    assert fs.read(path, EDEN) == "草案"
    with pytest.raises(PermissionError, match="不是文件 .* 的 owner"):
        fs.write(path, EDEN, "篡改")


def test_get_access_owner_only(fs: FileSystem) -> None:
    path = f"reps/{CHURCHILL}/draft.md"
    file = fs.create_rep_file(CHURCHILL, "draft.md", "内容", description="草案")
    access = file.get_access(CHURCHILL)
    assert access["owners"] == frozenset({CHURCHILL})
    assert access["scope"] == {CHURCHILL}
    assert access["primary_owner"] == CHURCHILL

    fs.add_scope(path, CHURCHILL, {EDEN})
    with pytest.raises(PermissionError, match="不是文件 .* 的 owner") as denied:
        file.get_access(EDEN)
    assert "当前 owner" not in str(denied.value)

    fs.add_owner(path, CHURCHILL, {EDEN})
    shared = file.get_access(EDEN)
    assert shared["owners"] == frozenset({CHURCHILL, EDEN})
    assert shared["scope"] == {CHURCHILL, EDEN}


def test_add_owner_requires_already_in_scope(fs: FileSystem) -> None:
    path = f"reps/{CHURCHILL}/draft.md"
    fs.create_rep_file(CHURCHILL, "draft.md", "草案")
    with pytest.raises(PermissionError, match="不在文件 .* 的 scope"):
        fs.add_owner(path, CHURCHILL, {EDEN})

    fs.add_scope(path, CHURCHILL, {EDEN})
    fs.add_owner(path, CHURCHILL, {EDEN})
    fs.write(path, EDEN, "联合修改")
    assert fs.read(path, CHURCHILL) == "联合修改"


def test_non_owner_cannot_expand_scope(fs: FileSystem) -> None:
    path = f"reps/{CHURCHILL}/draft.md"
    fs.create_rep_file(CHURCHILL, "draft.md", "草案")
    fs.add_scope(path, CHURCHILL, {EDEN})
    with pytest.raises(PermissionError, match="不是文件 .* 的 owner"):
        fs.add_scope(path, EDEN, {STALIN})


def test_cannot_create_directly_under_submissions(fs: FileSystem, venue_id: str) -> None:
    with pytest.raises(ValueError, match="File.submit"):
        fs.create_file(
            f"submissions/{venue_id}/x.md",
            "非法",
            owner=CHURCHILL,
        )


def test_submit_copies_with_empty_owner_and_scope(fs: FileSystem, venue_id: str) -> None:
    draft = fs.create_rep_file(CHURCHILL, "draft.md", "可提交草案")
    assert draft.can_submit(CHURCHILL)
    assert not draft.can_submit(STALIN)

    copy = draft.submit(CHURCHILL)
    rel = f"submissions/{venue_id}/{CHURCHILL}+draft.md+v1"
    assert copy.path.name == f"{CHURCHILL}+draft.md+v1"
    assert copy.owners == frozenset()
    assert copy.scope == set()
    assert copy.is_submission
    assert not draft.is_submission
    assert fs.read(rel, SYSTEM_ACTOR) == "可提交草案"


def test_rep_cannot_read_or_write_submission(fs: FileSystem, venue_id: str) -> None:
    draft = fs.create_rep_file(CHURCHILL, "draft.md", "可提交草案")
    draft.submit(CHURCHILL)
    rel = f"submissions/{venue_id}/{CHURCHILL}+draft.md+v1"

    with pytest.raises(PermissionError):
        fs.read(rel, CHURCHILL)
    with pytest.raises(PermissionError):
        fs.write(rel, SYSTEM_ACTOR, "系统也改不了")


def test_submit_snapshot_does_not_follow_original(fs: FileSystem, venue_id: str) -> None:
    draft = fs.create_rep_file(CHURCHILL, "draft.md", "初稿")
    draft.submit(CHURCHILL)
    fs.write(f"reps/{CHURCHILL}/draft.md", CHURCHILL, "改稿")
    assert fs.read(f"submissions/{venue_id}/{CHURCHILL}+draft.md+v1", SYSTEM_ACTOR) == "初稿"


def test_unchanged_content_rejects_resubmit(fs: FileSystem) -> None:
    draft = fs.create_rep_file(CHURCHILL, "draft.md", "草案")
    copy = draft.submit(CHURCHILL)
    assert not draft.can_submit(CHURCHILL)
    with pytest.raises(ValueError, match="内容相对最新提交未变化"):
        draft.submit(CHURCHILL)
    with pytest.raises(PermissionError, match="不能再次提交"):
        copy.submit(CHURCHILL)


def test_changed_content_gets_new_version(fs: FileSystem, venue_id: str) -> None:
    draft = fs.create_rep_file(CHURCHILL, "draft.md", "初稿")
    v1 = draft.submit(CHURCHILL)
    assert v1.path.name == f"{CHURCHILL}+draft.md+v1"

    fs.write(f"reps/{CHURCHILL}/draft.md", CHURCHILL, "二稿")
    assert draft.can_submit(CHURCHILL)
    v2 = draft.submit(CHURCHILL)
    assert v2.path.name == f"{CHURCHILL}+draft.md+v2"
    assert fs.read(f"submissions/{venue_id}/{CHURCHILL}+draft.md+v1", SYSTEM_ACTOR) == "初稿"
    assert fs.read(f"submissions/{venue_id}/{CHURCHILL}+draft.md+v2", SYSTEM_ACTOR) == "二稿"


def test_submit_uses_primary_owner_not_submitter(fs: FileSystem, venue_id: str) -> None:
    draft = fs.create_rep_file(CHURCHILL, "draft.md", "联合草案")
    fs.add_scope(f"reps/{CHURCHILL}/draft.md", CHURCHILL, {EDEN})
    fs.add_owner(f"reps/{CHURCHILL}/draft.md", CHURCHILL, {EDEN})
    assert draft.primary_owner == CHURCHILL

    submitted = draft.submit(EDEN)
    assert submitted.path.name == f"{CHURCHILL}+draft.md+v1"
    assert fs.read(
        f"submissions/{venue_id}/{CHURCHILL}+draft.md+v1",
        SYSTEM_ACTOR,
    ) == "联合草案"


def test_list_visible_and_writable_only_reps(fs: FileSystem) -> None:
    draft = fs.create_rep_file(CHURCHILL, "draft.md", "草案")
    shared = fs.create_rep_file(CHURCHILL, "shared.md", "共享草稿")
    fs.add_scope(f"reps/{CHURCHILL}/shared.md", CHURCHILL, {EDEN})
    draft.submit(CHURCHILL)

    assert [f.path.name for f in fs.list_visible(CHURCHILL)] == ["draft.md", "shared.md"]
    assert [f.path.name for f in fs.list_writable(CHURCHILL)] == ["draft.md", "shared.md"]
    assert [f.path.name for f in fs.list_visible(EDEN)] == ["shared.md"]
    assert [f.path.name for f in fs.list_writable(EDEN)] == []
    assert fs.list_visible(STALIN) == []
    assert fs.list_writable(STALIN) == []
    # submissions 不出现在上述列表中,但仍在 list_all 里
    assert len(fs.list_all()) == 3

    fs.add_owner(f"reps/{CHURCHILL}/shared.md", CHURCHILL, {EDEN})
    assert [f.path.name for f in fs.list_writable(EDEN)] == ["shared.md"]


def test_manifest_roundtrip(fs: FileSystem, scenario: Scenario, venue_id: str) -> None:
    draft = fs.create_rep_file(CHURCHILL, "draft.md", "草案")
    fs.add_scope(f"reps/{CHURCHILL}/draft.md", CHURCHILL, {EDEN})
    draft.submit(CHURCHILL)

    reloaded = FileSystem(fs.path, scenario)
    assert reloaded.read(f"reps/{CHURCHILL}/draft.md", EDEN) == "草案"
    with pytest.raises(PermissionError):
        reloaded.read(f"submissions/{venue_id}/{CHURCHILL}+draft.md+v1", CHURCHILL)
    assert (
        reloaded.read(f"submissions/{venue_id}/{CHURCHILL}+draft.md+v1", SYSTEM_ACTOR)
        == "草案"
    )
    # 回读后仍能按 hash 拒绝未改动的再次提交
    reloaded_draft = reloaded.get(f"reps/{CHURCHILL}/draft.md", CHURCHILL)
    with pytest.raises(ValueError, match="内容相对最新提交未变化"):
        reloaded_draft.submit(CHURCHILL)


def test_scenario_initialize_binds_filesystem(scenario: Scenario, tmp_path: Path) -> None:
    scenario.root_path = tmp_path
    (tmp_path / "simulation").mkdir()
    scenario.initialize()
    assert scenario.filesystem is not None
    assert scenario.filesystem.path.parent == tmp_path / "simulation"
    assert (scenario.filesystem.path / "reps" / CHURCHILL).is_dir()
    assert scenario.event_list is not None
    time_pool = [e for e in scenario.event_pool if e.condition.type == "time"]
    assert time_pool
    assert len(scenario.event_list.pullup_events) == len(time_pool)
    with pytest.raises(RuntimeError, match="不能重复 initialize"):
        scenario.initialize()
