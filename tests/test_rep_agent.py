"""RepresentativeAgent 最简 LLM + 工具循环."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent.rep_agent import RepresentativeAgent
from config.models import AppConfig, ProviderConfig
from llm import ChatMessage, LLM
from scenario.scenario import Scenario

TEMPLATE = Path(__file__).resolve().parent.parent / "scenario-template"


@pytest.fixture
def sample_config() -> AppConfig:
    return AppConfig(
        providers={
            "deepseek": ProviderConfig(
                base_url="https://api.deepseek.com",
                api_key="test-key",
            ),
        },
        default_provider="deepseek",
        default_model="deepseek-v4-flash",
    )


@pytest.fixture
def scenario(tmp_path: Path, venue_engine_runner) -> Scenario:
    loaded = Scenario()
    loaded.load(str(TEMPLATE))
    loaded.root_path = tmp_path
    (tmp_path / "simulation").mkdir()
    loaded.initialize()
    for venue in loaded.venues:
        venue_engine_runner.start(venue)
    return loaded


def _sse_body(*chunks: dict[str, Any]) -> bytes:
    lines = [f"data: {json.dumps(c)}\n\n" for c in chunks]
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


def _tool_call_sse(call_id: str, name: str, arguments: str) -> bytes:
    return _sse_body(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": call_id,
                                "type": "function",
                                "function": {
                                    "name": name,
                                    "arguments": arguments,
                                },
                            }
                        ]
                    }
                }
            ]
        },
        {"choices": [{"finish_reason": "tool_calls"}]},
    )


def _text_sse(text: str) -> bytes:
    return _sse_body(
        {"choices": [{"delta": {"content": text}}]},
        {"choices": [{"finish_reason": "stop"}]},
    )


@pytest.mark.asyncio
async def test_step_runs_tool_loop_then_final_text(
    scenario: Scenario, sample_config: AppConfig
) -> None:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        requests.append(payload)
        if len(requests) == 1:
            body = _tool_call_sse(
                "call_1",
                "send_message",
                json.dumps({"content": "诸位,我们先厘清百分比的含义。"}, ensure_ascii=False),
            )
        else:
            body = _text_sse("已完成公开发言。")
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/event-stream"},
        )

    llm = LLM(
        config=sample_config,
        thinking=False,
        transport=httpx.MockTransport(handler),
    )
    agent = RepresentativeAgent(scenario.reps["winston_churchill"], llm=llm)

    text = await agent.step("请先做一句公开发言,再简短确认。")

    assert text == "已完成公开发言。"
    assert len(requests) == 2
    assert requests[0]["tools"]
    assert agent.messages[0].role == "system"
    assert agent.messages[1] == ChatMessage(
        role="user", content="请先做一句公开发言,再简短确认。"
    )
    assert agent.messages[2].role == "assistant"
    assert agent.messages[2].tool_calls is not None
    assert agent.messages[3].role == "tool"
    assert agent.messages[3].tool_call_id == "call_1"
    tool_payload = json.loads(agent.messages[3].content)
    assert tool_payload["ok"] is True
    assert agent.messages[4] == ChatMessage(
        role="assistant", content="已完成公开发言。"
    )
    event_list = scenario.venues[0].event_list
    assert event_list is not None
    events = event_list.get_events("winston_churchill")
    assert any(
        getattr(event, "from_rep", None) == "winston_churchill"
        for event in events
    )


@pytest.mark.asyncio
async def test_step_requires_llm(scenario: Scenario) -> None:
    agent = RepresentativeAgent(scenario.reps["winston_churchill"])
    with pytest.raises(RuntimeError, match="未绑定 LLM"):
        await agent.step("hello")


def test_run_is_noop_for_simulator(scenario: Scenario) -> None:
    agent = RepresentativeAgent(scenario.reps["winston_churchill"])
    agent.run()
    assert len(agent.messages) == 1
    assert agent.messages[0].role == "system"
