"""Thinking 开关单元测试."""

from munagent.llm.thinking import resolve_thinking


def test_delegate_unmod_group_off() -> None:
    assert (
        resolve_thinking(
            "delegate",
            "turn",
            phase="UnmoderatedCaucus",
            scope="group",
        )
        is False
    )


def test_delegate_mod_on() -> None:
    assert resolve_thinking("delegate", "turn", phase="ModeratedCaucus", scope="venue") is True


def test_write_directive_always_on() -> None:
    assert (
        resolve_thinking(
            "delegate",
            "write_directive",
            phase="UnmoderatedCaucus",
            scope="group",
        )
        is True
    )


def test_express_grouping_off() -> None:
    assert resolve_thinking("delegate", "express_grouping") is False


def test_recorder_off() -> None:
    assert resolve_thinking("recorder", "summarize") is False


def test_chair_on() -> None:
    assert resolve_thinking("chair", "phase_decision") is True
