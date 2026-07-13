"""设计器 Agent 任务调度与 SSE 集成测试."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from munagent.llm import ChatMessage
from munagent.designer.agent import Agent, LoopResult
from munagent.designer.scenario import chats as chat_svc
from munagent.designer.scenario import package as scenario_svc
from munagent.designer.scenario.package import ScenarioCreate
from munagent.server.app import create_app
from munagent.server.design_task import design_tasks


@pytest.fixture()
def user_scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(scenario_svc, "user_scenarios_dir", lambda: tmp_path)
    scenario_svc.create_scenario(ScenarioCreate(id="task-test", title="任务测试"))
    return "task-test"


@pytest.fixture()
def chat_id(user_scenario: str) -> str:
    return chat_svc.create_chat(user_scenario, "测试对话").id


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(autouse=True)
def reset_design_tasks(user_scenario: str) -> None:
    design_tasks._runtimes.clear()


async def _fake_loop(self: Agent, user_prompt: str, *, max_steps: int = 50) -> LoopResult:
    self.add_message(
        ChatMessage(role="user", content=user_prompt),
        chat_record={"type": "user_message", "text": user_prompt},
    )
    self.event_sink.on_text_delta("你好")
    self.add_message(
        ChatMessage(role="assistant", content="你好"),
        chat_record={"type": "agent_text", "text": "你好"},
    )
    return LoopResult.DONE


@pytest.fixture()
def mock_agent_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Agent, "loop", _fake_loop)


def test_send_message_starts_task(
    client: TestClient,
    user_scenario: str,
    chat_id: str,
    mock_agent_loop: None,
) -> None:
    res = client.post(
        f"/api/scenarios/{user_scenario}/chats/{chat_id}/messages",
        json={"text": "帮我写 background"},
    )
    assert res.status_code == 202
    assert "task_id" in res.json()


def test_send_message_conflict_when_busy(
    client: TestClient,
    user_scenario: str,
    chat_id: str,
) -> None:
    from unittest.mock import MagicMock

    from munagent.server.design_schemas import ActiveTask

    rt = design_tasks._rt(user_scenario)
    rt.active = ActiveTask(task_id="busy", chat_id=chat_id, turn=1)
    mock_task = MagicMock()
    mock_task.done.return_value = False
    rt.task = mock_task

    second = client.post(
        f"/api/scenarios/{user_scenario}/chats/{chat_id}/messages",
        json={"text": "第二条"},
    )
    assert second.status_code == 409


def test_design_state_active_task(
    client: TestClient,
    user_scenario: str,
    chat_id: str,
) -> None:
    from munagent.server.design_schemas import ActiveTask

    design_tasks._rt(user_scenario).active = ActiveTask(task_id="t1", chat_id=chat_id, turn=2)
    state = client.get(f"/api/scenarios/{user_scenario}/design").json()
    assert state["active_task"]["chat_id"] == chat_id


@pytest.mark.asyncio
async def test_sse_replay(user_scenario: str, chat_id: str) -> None:
    design_tasks.emit(user_scenario, {"type": "task_started", "chat_id": chat_id, "task_id": "t", "turn": 1})
    design_tasks.emit(user_scenario, {"type": "task_finished", "chat_id": chat_id, "result": "done", "error": None})

    seen: list[str] = []
    async for ev in design_tasks.subscribe(user_scenario, after=0):
        seen.append(str(ev["type"]))
        if ev["type"] == "task_finished":
            break
    assert seen == ["task_started", "task_finished"]


def test_revert_file_edit(client: TestClient, user_scenario: str, chat_id: str) -> None:
    from munagent.designer.scenario import files as file_svc

    file_svc.put_file(user_scenario, "notes.md", "# 原始\n")
    diff = "--- a/notes.md\n+++ b/notes.md\n@@ -1 +1,2 @@\n # 原始\n+# 新增\n"
    rec = chat_svc.append_chat_record(
        user_scenario,
        chat_id,
        {"type": "file_edit", "path": "notes.md", "op": "modify", "diff": diff},
        turn=1,
    )
    file_svc.put_file(user_scenario, "notes.md", "# 原始\n# 新增\n")
    res = client.post(f"/api/scenarios/{user_scenario}/chats/{chat_id}/revert/{rec['seq']}")
    assert res.status_code == 200
    assert file_svc.get_file(user_scenario, "notes.md").content == "# 原始\n"


def test_revert_drift_returns_409(client: TestClient, user_scenario: str, chat_id: str) -> None:
    from munagent.designer.scenario import files as file_svc

    diff = "--- a/notes.md\n+++ b/notes.md\n@@ -0,0 +1,1 @@\n+# 新增\n"
    rec = chat_svc.append_chat_record(
        user_scenario,
        chat_id,
        {"type": "file_edit", "path": "notes.md", "op": "create", "diff": diff},
        turn=1,
    )
    file_svc.put_file(user_scenario, "notes.md", "# 已被改掉\n")
    res = client.post(f"/api/scenarios/{user_scenario}/chats/{chat_id}/revert/{rec['seq']}")
    assert res.status_code == 409
    body = res.json()
    assert body["detail"]["path"] == "notes.md"
