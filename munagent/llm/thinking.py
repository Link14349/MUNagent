"""Thinking 模式按角色+task 解析. 见 docs/design/05-agent-harness.md §5."""

from __future__ import annotations

PRESIDIUM_ROLES = frozenset({"chair", "dm", "designer"})


def resolve_thinking(
    role: str,
    task: str,
    *,
    phase: str | None = None,
    scope: str | None = None,
) -> bool:
    """返回本次 LLM 调用是否开启 thinking."""
    if task == "write_directive":
        return True

    if role == "recorder":
        return False

    if role in PRESIDIUM_ROLES:
        return True

    if role == "delegate":
        if task in {"express_grouping", "quick_decide"}:
            return False
        if task == "turn" and phase == "UnmoderatedCaucus" and scope == "group":
            return False
        return True

    return False
