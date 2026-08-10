"""MUNagent 入口：演示 FileSystem（权限控制 + 提交版本管理）。"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from filesystem.filesystem import SYSTEM_ACTOR
from scenario.scenario import Scenario

CHURCHILL = "winston_churchill"
STALIN = "joseph_stalin"
EDEN = "anthony_eden"


def _section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(title)
    print("=" * 60)


def _ok(message: str) -> None:
    print(f"  ✓ {message}")


def _denied(action: str, exc: BaseException) -> None:
    print(f"  ✗ 拒绝：{action}")
    print(f"      → {exc}")


def _hash_short(value: str) -> str:
    return value[:12] + "…"


def demo_permissions(fs, venue_id: str) -> None:
    _section("A. 权限：私有文件 / scope / owner")
    draft = fs.create_rep_file(
        CHURCHILL,
        "percentages.md",
        "希腊 90% / 罗马尼亚 10%",
        description="百分比草案",
    )
    _ok(f"创建私有文件 owner={sorted(draft.owners)} scope={sorted(draft.scope)}")
    _ok(f"description={draft.description!r}")
    _ok(f"primary_owner={draft.primary_owner!r}（提交命名将使用它）")

    try:
        fs.read(f"reps/{CHURCHILL}/percentages.md", STALIN)
    except PermissionError as exc:
        _denied("斯大林读取丘吉尔私有草案", exc)

    fs.add_scope(f"reps/{CHURCHILL}/percentages.md", CHURCHILL, {EDEN})
    _ok(f"艾登加入 scope 后可读: {fs.read(f'reps/{CHURCHILL}/percentages.md', EDEN)!r}")
    try:
        fs.write(f"reps/{CHURCHILL}/percentages.md", EDEN, "艾登篡改")
    except PermissionError as exc:
        _denied("艾登写入（在 scope 非 owner）", exc)

    try:
        fs.add_scope(f"reps/{CHURCHILL}/percentages.md", EDEN, {STALIN})
    except PermissionError as exc:
        _denied("非 owner 扩大 scope", exc)

    fs.add_owner(f"reps/{CHURCHILL}/percentages.md", CHURCHILL, {EDEN})
    fs.write(f"reps/{CHURCHILL}/percentages.md", EDEN, "希腊 90% / 罗马尼亚 10%（艾登修订）")
    _ok(f"提升 owner 后艾登可写；owners={sorted(draft.owners)}")
    _ok(f"primary_owner 仍为 {draft.primary_owner!r}（不因 add_owner 改变）")

    fs.create_rep_file(STALIN, "red_lines.md", "巴尔干红线", description="斯大林红线")
    try:
        fs.add_owner(f"reps/{STALIN}/red_lines.md", STALIN, {CHURCHILL})
    except PermissionError as exc:
        _denied("未入 scope 不能成为 owner", exc)

    try:
        fs.create_file(f"submissions/{venue_id}/forged.md", "伪造", owner=CHURCHILL)
    except ValueError as exc:
        _denied("禁止直接创建 submissions/", exc)

    return draft


def demo_versioning(fs, draft, venue_id: str) -> None:
    _section("B1. 首次提交 → v1（命名 = primary_owner+原文件名+v版本）")
    content_v1 = fs.read(f"reps/{CHURCHILL}/percentages.md", CHURCHILL)
    _ok(f"提交前内容: {content_v1!r}")
    _ok(f"content_hash: {_hash_short(draft.content_hash)}")
    _ok(f"can_submit(丘吉尔)={draft.can_submit(CHURCHILL)}, can_submit(斯大林)={draft.can_submit(STALIN)}")

    v1 = draft.submit(CHURCHILL)
    rel_v1 = f"submissions/{venue_id}/{v1.path.name}"
    _ok(f"生成: {rel_v1}")
    assert v1.path.name == f"{CHURCHILL}+percentages.md+v1"
    _ok(f"副本 owner/scope 为空: owners={sorted(v1.owners)}, scope={sorted(v1.scope)}")
    _ok(f"系统可读 v1: {fs.read(rel_v1, SYSTEM_ACTOR)!r}")

    _section("B2. 未改动再次提交 → 拒绝（hash 相同）")
    _ok(f"can_submit(丘吉尔) 现在应为 False → {draft.can_submit(CHURCHILL)}")
    try:
        draft.submit(CHURCHILL)
    except ValueError as exc:
        _denied("内容相对 v1 未变化", exc)

    _section("B3. 改稿后再提交 → v2（旧版本保留）")
    fs.write(
        f"reps/{CHURCHILL}/percentages.md",
        CHURCHILL,
        "希腊 90% / 罗马尼亚 10%（二稿）",
    )
    content_v2 = fs.read(f"reps/{CHURCHILL}/percentages.md", CHURCHILL)
    _ok(f"原文件已改为: {content_v2!r}")
    _ok(f"新 hash: {_hash_short(draft.content_hash)}（与 v1 不同）")
    _ok(f"can_submit(丘吉尔)={draft.can_submit(CHURCHILL)}")

    v2 = draft.submit(CHURCHILL)
    rel_v2 = f"submissions/{venue_id}/{v2.path.name}"
    assert v2.path.name == f"{CHURCHILL}+percentages.md+v2"
    _ok(f"生成: {rel_v2}")
    _ok(f"v1 仍保留旧稿: {fs.read(rel_v1, SYSTEM_ACTOR)!r}")
    _ok(f"v2 为新稿:     {fs.read(rel_v2, SYSTEM_ACTOR)!r}")

    _section("B4. 再改一版 → v3；未改动仍拒绝")
    fs.write(
        f"reps/{CHURCHILL}/percentages.md",
        CHURCHILL,
        "希腊 90% / 罗马尼亚 10%（三稿，最终）",
    )
    v3 = draft.submit(CHURCHILL)
    rel_v3 = f"submissions/{venue_id}/{v3.path.name}"
    assert v3.path.name == f"{CHURCHILL}+percentages.md+v3"
    _ok(f"生成: {rel_v3}")
    try:
        draft.submit(CHURCHILL)
    except ValueError as exc:
        _denied("相对最新 v3 未改动", exc)

    _section("B5. 联合 owner 提交：文件名仍用 primary_owner，不是提交者")
    # 艾登已是 owner；由艾登提交，文件名仍以丘吉尔为前缀
    fs.write(
        f"reps/{CHURCHILL}/percentages.md",
        EDEN,
        "希腊 90% / 罗马尼亚 10%（艾登四稿）",
    )
    v4 = draft.submit(EDEN)
    assert v4.path.name == f"{CHURCHILL}+percentages.md+v4"
    _ok(f"提交者=艾登，但文件名为: {v4.path.name}")
    _ok(f"primary_owner={draft.primary_owner!r} 决定命名前缀")

    _section("B6. 版本链一览 + 提交副本不可再 submit / 代表不可见")
    versions = sorted(
        f.path.name
        for f in fs.list_all()
        if f.is_submission and f.path.name.startswith(f"{CHURCHILL}+percentages.md+v")
    )
    print("  版本链:")
    for name in versions:
        body = fs.read(f"submissions/{venue_id}/{name}", SYSTEM_ACTOR)
        print(f"    - {name}: {body!r}")

    try:
        v1.submit(CHURCHILL)
    except PermissionError as exc:
        _denied("对提交副本再次 submit", exc)
    try:
        fs.read(f"submissions/{venue_id}/{v4.path.name}", CHURCHILL)
    except PermissionError as exc:
        _denied("代表读取任一提交副本", exc)

    _section("B7. list_visible / list_writable（仅 reps/，不含 submissions）")
    for rep_id in (CHURCHILL, STALIN, EDEN):
        visible = [f.path.relative_to(fs.path).as_posix() for f in fs.list_visible(rep_id)]
        writable = [f.path.relative_to(fs.path).as_posix() for f in fs.list_writable(rep_id)]
        print(f"  {rep_id}")
        print(f"    visible:  {visible}")
        print(f"    writable: {writable}")
    all_names = [f.path.relative_to(fs.path).as_posix() for f in fs.list_all()]
    print(f"  系统全部文件（含 submissions）: {all_names}")


def demo_filesystem(scenario: Scenario) -> None:
    fs = scenario.filesystem
    if fs is None:
        raise RuntimeError("Scenario 尚未 initialize，filesystem 为空")

    venue_id = scenario.venues[0].id
    print(f"推演目录: {fs.path}")
    print(f"会场: {venue_id}")

    draft = demo_permissions(fs, venue_id)
    demo_versioning(fs, draft, venue_id)


def main() -> None:
    root = Path(__file__).resolve().parent.parent / "scenario-template"
    scenario = Scenario()
    scenario.load(str(root))
    scenario.initialize()
    run_dir = scenario.filesystem.path if scenario.filesystem is not None else None

    try:
        _section("场景已加载并 initialize")
        print(f"  标题: {scenario.title}")
        print(f"  代表: {', '.join(rep.id for rep in scenario.representatives)}")
        assert scenario.filesystem is not None

        demo_filesystem(scenario)
        print("\n演示结束。")
    finally:
        if run_dir is not None and run_dir.is_dir():
            shutil.rmtree(run_dir)
            print(f"已清理演示目录: {run_dir}")


if __name__ == "__main__":
    main()
