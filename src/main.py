"""MUNagent 入口：演示 EventList（可见性 / pull-up / 权限）与 FileSystem。"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from event.event import (
    EventStatus,
    InstructionEvent,
    MessageEvent,
    MotionSwitchEvent,
    NoteEvent,
    SystemEvent,
)
from filesystem.filesystem import SYSTEM_ACTOR
from scenario.scenario import Scenario
from scenario.venue import SessionPhase

CHURCHILL = "winston_churchill"
STALIN = "joseph_stalin"
EDEN = "anthony_eden"
MOLOTOV = "vyacheslav_molotov"


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


def _show_visible(events, label: str, rep_id: str) -> None:
    visible = events.get_events(rep_id)
    print(f"  {label} ({rep_id}) 可见 {len(visible)} 条:")
    for event in visible:
        stamp = event.time.isoformat() if event.time else "?"
        print(f"    [{event.id}] {event.type.value} @{stamp}: {event.content[:48]}…")


def demo_eventlist(scenario: Scenario) -> None:
    events = scenario.event_list
    if events is None:
        raise RuntimeError("Scenario 尚未 initialize，event_list 为空")
    fs = scenario.filesystem
    if fs is None:
        raise RuntimeError("Scenario 尚未 initialize，filesystem 为空")

    venue_id = scenario.venues[0].id
    moscow = ZoneInfo("Europe/Moscow")

    _section("E1. initialize 已挂载 time 条件 pull-up")
    _ok(f"剧情时钟: {events.time.isoformat()}")
    _ok(f"event_pool 中 time 事件: {sum(1 for e in scenario.event_pool if e.condition.type == 'time')}")
    _ok(f"已 pull-up 待触发: {len(events.pullup_events)}")
    for pullup in events.pullup_events:
        due = pullup.condition.time.isoformat() if pullup.condition.time else "?"
        print(f"    - due={due}: {pullup.content[:40]}…")

    _section("E2. submit_event 盖戳 + get_events 按 scope 过滤")
    events.submit_event(
        SystemEvent(
            "全员通报：会议正式开始",
            [],
            venue_id,
            {CHURCHILL, STALIN, EDEN, MOLOTOV},
            scenario,
        )
    )
    events.submit_event(NoteEvent("仅丘艾可见的密信：试探希腊条款", CHURCHILL, {EDEN}, venue_id, scenario))
    events.submit_event(NoteEvent("仅丘斯可见的密信：罗马尼亚底线", CHURCHILL, {STALIN}, venue_id, scenario))
    _ok("已添加：全员通报 + 两封不同 scope 的纸条")

    for rep_id, label in (
        (CHURCHILL, "丘吉尔"),
        (EDEN, "艾登"),
        (STALIN, "斯大林"),
        (MOLOTOV, "莫洛托夫"),
        ("__GOD__", "上帝视角"),
    ):
        _show_visible(events, label, rep_id)

    _section("E3. pull-up：推进时钟触发外部 SystemEvent")
    first_due = datetime(1944, 10, 9, 22, 45, tzinfo=moscow)
    events.update_time(first_due)
    _ok(f"update_time → {events.time.isoformat()}，待触发剩余 {len(events.pullup_events)}")
    fired = [e for e in events.get_events("__GOD__") if e.type.value == "system"]
    _ok(f"系统事件累计 {len(fired)} 条；最新: {fired[-1].content[:48]}…")

    events.time_pass(timedelta(hours=1))
    _ok(f"time_pass(+1h) → {events.time.isoformat()}，待触发剩余 {len(events.pullup_events)}")
    _show_visible(events, "丘吉尔（含外部事件）", CHURCHILL)

    _section("E4. 权限：终态不可改 / time·id 不可改 / CoT 仅发送者")
    pending = MotionSwitchEvent(
        "动议进入自由讨论",
        SessionPhase.FREE_DISCUSSION,
        venue_id,
        {CHURCHILL, STALIN, EDEN, MOLOTOV},
        scenario,
    )
    events.submit_event(pending)
    _ok(f"PENDING 入表后 pending_event_ids={events.pending_event_ids}")
    pending.content = "动议说明已修订"
    _ok(f"PENDING 可改 content → {pending.content!r}")

    try:
        pending.time = events.time + timedelta(minutes=5)
    except PermissionError as exc:
        _denied("改写已盖戳的 time", exc)
    try:
        pending.id = 999
    except PermissionError as exc:
        _denied("改写已分配的 id", exc)

    pending.status = EventStatus.COMPLETED
    _ok(f"离开 PENDING 后 pending_event_ids={events.pending_event_ids}")
    try:
        pending.content = "终态篡改"
    except PermissionError as exc:
        _denied("COMPLETED 后修改 content", exc)
    try:
        pending.scope = {STALIN}
    except PermissionError as exc:
        _denied("COMPLETED 后修改 scope", exc)

    msg = MessageEvent(
        "丘吉尔公开发言：希腊事务应交由伦敦主导",
        "内心：先试探斯大林是否接受 90/10",
        CHURCHILL,
        venue_id,
        scenario,
    )
    events.submit_event(msg)
    _ok(f"发送者可读 CoT: {msg.get_CoT(CHURCHILL)!r}")
    try:
        msg.get_CoT(STALIN)
    except ValueError as exc:
        _denied("斯大林读取丘吉尔 CoT", exc)
    try:
        msg.CoT = "偷改思维链"
    except PermissionError as exc:
        _denied("修改已完成消息的 CoT", exc)

    _section("E5. InstructionEvent：经 scope 可见，submission 仍不可直接读")
    draft = fs.create_rep_file(
        CHURCHILL,
        "foreign_office_note.md",
        "请艾登核对希腊过渡安排措辞",
        description="外长指示稿",
    )
    submitted = draft.submit(CHURCHILL)
    instruction = InstructionEvent(
        "外长指示已提交",
        {CHURCHILL, EDEN},
        submitted,
        venue_id,
        scenario,
    )
    events.submit_event(instruction)
    eden_events = events.get_events(EDEN)
    linked = [e for e in eden_events if isinstance(e, InstructionEvent)]
    _ok(f"艾登经事件看到 Instruction: {len(linked)} 条，文件={linked[0].instruction.path.name}")
    stalin_linked = [e for e in events.get_events(STALIN) if isinstance(e, InstructionEvent)]
    _ok(f"斯大林看不到该 Instruction: {len(stalin_linked)} 条")

    rel = submitted.path.relative_to(fs.path).as_posix()
    try:
        fs.read(rel, EDEN)
    except PermissionError as exc:
        _denied("艾登直接读 submissions/（即使事件可见）", exc)
    try:
        fs.read(rel, STALIN)
    except PermissionError as exc:
        _denied("斯大林直接读 submissions/", exc)
    _ok(f"系统可读 submission: {fs.read(rel, SYSTEM_ACTOR)!r}")


def demo_permissions(fs, venue_id: str):
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
        assert scenario.event_list is not None

        demo_eventlist(scenario)
        demo_filesystem(scenario)
        print("\n演示结束。")
    finally:
        if run_dir is not None and run_dir.is_dir():
            shutil.rmtree(run_dir)
            print(f"已清理演示目录: {run_dir}")


if __name__ == "__main__":
    main()
