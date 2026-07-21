"""对话标题自动概括测试."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from munagent.config.models import AppConfig
from munagent.designer import chat_title as title_svc
from munagent.designer.scenario import chats as chat_svc
from munagent.designer.scenario import package as scenario_svc
from munagent.designer.scenario.chats import DEFAULT_CHAT_TITLE
from munagent.designer.scenario.package import ScenarioCreate


@pytest.fixture()
def user_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(scenario_svc, "user_scenarios_dir", lambda: tmp_path)
    scenario_svc.create_scenario(ScenarioCreate(id="title-test", title="标题测试"))
    return "title-test"


def _seed_turn_one(scenario_id: str, chat_id: str) -> None:
    chat_svc.append_chat_record(
        scenario_id,
        chat_id,
        {"type": "user_message", "text": "帮我完善法国1848年革命场景，重点检查 crisis_arcs 时间线"},
        turn=1,
    )
    chat_svc.append_chat_record(
        scenario_id,
        chat_id,
        {"type": "agent_text", "text": "好的，我先检查 manifest 与 crisis_arcs.yaml 的一致性。"},
        turn=1,
    )


def test_truncate_fallback() -> None:
    short = title_svc._truncate_fallback("完善法国1848场景")
    assert short == "完善法国1848场景"
    long = title_svc._truncate_fallback("a" * 40)
    assert long.endswith("…")
    assert len(long) == 31


def test_sanitize_llm_title() -> None:
    assert title_svc._sanitize_llm_title('「法国1848革命场景完善」') == "法国1848革命场景完善"
    assert title_svc._sanitize_llm_title(DEFAULT_CHAT_TITLE) is None


@pytest.mark.asyncio
async def test_autotitle_llm_success(user_root: str) -> None:
    chat = chat_svc.create_chat(user_root, DEFAULT_CHAT_TITLE)
    _seed_turn_one(user_root, chat.id)
    mock_llm = AsyncMock()
    mock_llm.chat = AsyncMock(return_value="法国1848革命场景完善")
    config = AppConfig()

    meta = await title_svc.maybe_autotitle_after_first_turn(
        user_root, chat.id, config, llm=mock_llm
    )
    assert meta is not None
    assert meta.title == "法国1848革命场景完善"
    assert chat_svc.list_chats(user_root)[0].title == "法国1848革命场景完善"


@pytest.mark.asyncio
async def test_autotitle_llm_fail_fallback(user_root: str) -> None:
    chat = chat_svc.create_chat(user_root, DEFAULT_CHAT_TITLE)
    user_msg = "帮我完善法国1848年革命场景"
    chat_svc.append_chat_record(
        user_root,
        chat.id,
        {"type": "user_message", "text": user_msg},
        turn=1,
    )
    mock_llm = AsyncMock()
    mock_llm.chat = AsyncMock(side_effect=RuntimeError("LLM down"))
    config = AppConfig()

    meta = await title_svc.maybe_autotitle_after_first_turn(
        user_root, chat.id, config, llm=mock_llm
    )
    assert meta is not None
    assert meta.title == user_msg


@pytest.mark.asyncio
async def test_autotitle_skips_custom_title(user_root: str) -> None:
    chat = chat_svc.create_chat(user_root, "已有标题")
    _seed_turn_one(user_root, chat.id)
    mock_llm = AsyncMock()
    mock_llm.chat = AsyncMock(return_value="不应写入")
    config = AppConfig()

    meta = await title_svc.maybe_autotitle_after_first_turn(
        user_root, chat.id, config, llm=mock_llm
    )
    assert meta is None
    mock_llm.chat.assert_not_called()
    assert chat_svc.list_chats(user_root)[0].title == "已有标题"
