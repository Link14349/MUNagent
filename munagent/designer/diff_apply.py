"""unified diff 反向应用 — 供 file_edit 撤销使用."""

from __future__ import annotations


def apply_unified_diff(base: str, diff: str) -> str | None:
    """将 unified diff 应用到 base; 上下文不匹配时返回 None."""
    base_lines = base.split("\n")
    out: list[str] = []
    i = 0
    for raw in diff.split("\n"):
        if raw.startswith("@@") or raw.startswith("---") or raw.startswith("+++"):
            continue
        if raw.startswith("-"):
            if i >= len(base_lines) or base_lines[i] != raw[1:]:
                return None
            i += 1
        elif raw.startswith("+"):
            out.append(raw[1:])
        elif raw.startswith(" "):
            if i >= len(base_lines) or base_lines[i] != raw[1:]:
                return None
            out.append(base_lines[i])
            i += 1
    while i < len(base_lines):
        out.append(base_lines[i])
        i += 1
    return "\n".join(out)


def reverse_unified_diff(diff: str) -> str:
    lines: list[str] = []
    for line in diff.split("\n"):
        if line.startswith("+++"):
            lines.append(line.replace("+++", "---", 1))
        elif line.startswith("---"):
            lines.append(line.replace("---", "+++", 1))
        elif line.startswith("+") and not line.startswith("+++"):
            lines.append(f"-{line[1:]}")
        elif line.startswith("-") and not line.startswith("---"):
            lines.append(f"+{line[1:]}")
        else:
            lines.append(line)
    return "\n".join(lines)


def post_edit_content(before: str, diff: str) -> str | None:
    """由编辑前内容与 diff 推算编辑后内容."""
    return apply_unified_diff(before, diff)
