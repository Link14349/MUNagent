"""file_edit 撤销 — 见 design/designer/01-data-chats.md §3."""

from __future__ import annotations

from dataclasses import dataclass

from munagent.designer.diff_apply import apply_unified_diff, post_edit_content, reverse_unified_diff
from munagent.designer.scenario import chats as chat_svc
from munagent.designer.scenario import files as file_svc


@dataclass(frozen=True)
class RevertDriftError(Exception):
    """当前文件与 file_edit 的编辑后内容不一致, 无法直接撤销."""

    path: str
    current_content: str
    expected_content: str
    original_content: str

    @property
    def message(self) -> str:
        return "内容已漂移, 无法自动撤销"


def revert_file_edit(scenario_id: str, chat_id: str, seq: int) -> dict:
    """撤销指定 seq 的 file_edit; 成功时追加 system/revert 并返回新记录."""
    records = chat_svc.get_chat_records(scenario_id, chat_id)
    record = next((r for r in records if r.get("seq") == seq and r.get("type") == "file_edit"), None)
    if record is None:
        raise FileNotFoundError(f"file_edit 记录不存在: seq={seq}")

    path = str(record["path"])
    op = str(record.get("op", "modify"))
    diff = str(record.get("diff", ""))

    try:
        current = file_svc.get_file(scenario_id, path).content
    except FileNotFoundError:
        current = ""

    reversed_diff = reverse_unified_diff(diff)
    next_content = apply_unified_diff(current, reversed_diff)
    if next_content is None:
        original, expected = _edit_before_after(records, seq, path, diff)
        raise RevertDriftError(
            path=path,
            current_content=current,
            expected_content=expected,
            original_content=original,
        )

    if op == "create" and next_content == "":
        file_svc.delete_file(scenario_id, path)
    elif op == "delete" and next_content != "":
        file_svc.put_file(scenario_id, path, next_content)
    else:
        file_svc.put_file(scenario_id, path, next_content)

    return chat_svc.append_chat_record(
        scenario_id,
        chat_id,
        {
            "type": "system",
            "kind": "revert",
            "text": f"已撤销 seq={seq} 对 {path} 的编辑",
        },
    )


def _edit_before_after(records: list[dict], seq: int, path: str, diff: str) -> tuple[str, str]:
    """按 file_edit 顺序重建该次编辑前后的文件内容."""
    before = ""
    for row in records:
        if row.get("seq") == seq:
            break
        if row.get("type") != "file_edit" or row.get("path") != path:
            continue
        after = post_edit_content(before, str(row.get("diff", "")))
        if after is not None:
            before = after
    expected = post_edit_content(before, diff)
    return before, expected if expected is not None else before
