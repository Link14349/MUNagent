"""设计 Agent loop 回归 — 历史 replay 与伪工具检测."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from munagent.config.models import AppConfig
from munagent.designer.agent import (
    _args_summary,
    _record_to_chat_messages,
    _todo_has_pending,
    looks_like_pseudo_tools,
    strip_pseudo_tool_lines,
)
from munagent.llm.stream import ToolCallDelta
from munagent.designer import prompt as prompt_seg
from munagent.designer.scenario import chats as chat_svc
from munagent.designer.scenario import package as scenario_svc
from munagent.designer.scenario.package import ScenarioCreate
from munagent.designer.tools import ToolContext, execute_tool


def test_tool_call_replay_clips_huge_args_summary() -> None:
    huge = "content=" + "x" * 5000
    msgs = _record_to_chat_messages(
        {
            "type": "tool_call",
            "tool": "write_file",
            "args_summary": huge,
            "status": "ok",
            "result_summary": "ok",
        }
    )
    assert len(msgs[0].content) <= 250


def test_tool_call_replay_uses_user_role_not_assistant_brackets() -> None:
    msgs = _record_to_chat_messages(
        {
            "type": "tool_call",
            "tool": "read_file",
            "args_summary": "path='background.md'",
            "status": "ok",
            "result_summary": "读取 background.md, 1200 字符",
        }
    )
    assert len(msgs) == 1
    assert msgs[0].role == "user"
    assert "(历史工具记录" in msgs[0].content
    assert "[工具" not in msgs[0].content


def test_file_edit_and_todo_replay_use_user_role() -> None:
    edit = _record_to_chat_messages(
        {"type": "file_edit", "path": "seats/a.yaml", "op": "create", "diff": ""}
    )
    todo = _record_to_chat_messages({"type": "todo", "text": "[ ] 写 background"})
    assert edit[0].role == "user"
    assert "(历史文件编辑)" in edit[0].content
    assert todo[0].role == "user"
    assert "(历史计划清单)" in todo[0].content


def test_agent_text_with_pseudo_tools_sanitized() -> None:
    bad = "好的, 开始读取.\n[工具 read_file] path='a.md' → ok\n其余规划…" + ("x" * 100)
    msgs = _record_to_chat_messages({"type": "agent_text", "text": bad})
    assert len(msgs) == 1
    assert msgs[0].role == "assistant"
    assert "[工具" not in msgs[0].content
    assert "其余规划" in msgs[0].content


def test_agent_text_only_pseudo_tools_becomes_user_warning() -> None:
    bad = "[工具 write_file] path='a.md' → 写入"
    msgs = _record_to_chat_messages({"type": "agent_text", "text": bad})
    assert msgs[0].role == "user"
    assert "勿模仿" in msgs[0].content


def test_looks_like_pseudo_tools() -> None:
    assert looks_like_pseudo_tools("[工具 read_file] path='x'")
    assert looks_like_pseudo_tools("先读文件\n[文件编辑 modify] seats/a.yaml")
    assert not looks_like_pseudo_tools("我会用 read_file 读取 manifest.")


def test_strip_pseudo_tool_lines() -> None:
    text = "计划如下:\n[工具 edit_todo] todo='...'\n继续写 background."
    assert "[工具" not in strip_pseudo_tool_lines(text)
    assert "继续写 background" in strip_pseudo_tool_lines(text)


@pytest.fixture()
def user_scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(scenario_svc, "user_scenarios_dir", lambda: tmp_path)
    scenario_svc.create_scenario(ScenarioCreate(id="agent-test", title="Agent 测试"))
    return "agent-test"


@pytest.mark.asyncio
async def test_build_L_includes_todo(user_scenario: str, sample_config: AppConfig) -> None:
    chat = chat_svc.create_chat(user_scenario, "todo")
    ctx = ToolContext(
        scenario_id=user_scenario,
        config=sample_config,
        chat_id=chat.id,
        turn=1,
    )
    await execute_tool(
        ctx,
        "edit_todo",
        {"todo": "[x] 检索资料\n[ ] 写 background.md"},
    )
    l = prompt_seg.build_L(user_scenario, chat_id=chat.id)
    assert "## 当前计划清单" in l
    assert "进度 1/2" in l
    assert "[ ] 写 background.md" in l


def test_todo_has_pending(user_scenario: str) -> None:
    chat = chat_svc.create_chat(user_scenario, "todo")
    assert not _todo_has_pending(user_scenario, chat.id)
    chat_svc.append_chat_record(
        user_scenario,
        chat.id,
        {"type": "todo", "text": "[x] a\n[ ] b"},
    )
    assert _todo_has_pending(user_scenario, chat.id)
    chat_svc.append_chat_record(
        user_scenario,
        chat.id,
        {"type": "todo", "text": "[x] a\n[x] b"},
    )
    assert not _todo_has_pending(user_scenario, chat.id)


def test_args_summary_write_file_omits_content() -> None:
    body = "# " + "x" * 500
    call = ToolCallDelta(
        id="c1",
        name="write_file",
        arguments=json.dumps({"path": "background.md", "content": body}),
    )
    summary = _args_summary(call)
    assert "content=" not in summary
    assert "background.md" in summary
    assert "503" in summary or "502" in summary  # 字符数
    assert len(summary) <= 200


def test_args_summary_edit_todo_omits_body() -> None:
    todo = "\n".join(f"[ ] 任务{i}" for i in range(20))
    call = ToolCallDelta(
        id="c2",
        name="edit_todo",
        arguments=json.dumps({"todo": todo}),
    )
    summary = _args_summary(call)
    assert "任务" not in summary
    assert "计划" in summary
    assert "0/20" in summary


def test_args_summary_append_and_insert() -> None:
    append = ToolCallDelta(
        id="c3",
        name="append_file",
        arguments=json.dumps({"path": "background.md", "content": "## 新章\n\n" + "x" * 400}),
    )
    assert "+407" in _args_summary(append)
    insert = ToolCallDelta(
        id="c4",
        name="insert_file",
        arguments=json.dumps(
            {
                "path": "background.md",
                "anchor": "## 四、标题",
                "position": "after",
                "content": "段落\n",
            }
        ),
    )
    s = _args_summary(insert)
    assert "after" in s
    assert "## 四" in s
    assert len(s) <= 200
