"""Agent 循环与最小版 Agent 测试(mock LLM)."""

from __future__ import annotations

import httpx
import pytest

from munagent.agents.base import AgentContext, TaskSpec, parse_json_block
from munagent.agents.delegate import DelegateAgent, DelegateTurnAction
from munagent.agents.dm import DMAgent, outcome_tier, roll_directive
from munagent.config.models import MunagentConfig, ProviderConfig, RoleConfig
from munagent.core.scenario import SeatSpec
from munagent.llm.client import LLMClient


@pytest.fixture
def config() -> MunagentConfig:
    return MunagentConfig(
        providers={"deepseek": ProviderConfig(base_url="https://x", api_key="sk-test")},
        roles={"delegate": RoleConfig(provider="deepseek", model="deepseek-v4-flash")},
    )


def _json_response(content: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
    return httpx.MockTransport(handler)


def test_parse_json_block_ok() -> None:
    raw = 'some text\n```json\n{"action": "speech", "text": "hi"}\n```'
    data, err = parse_json_block(raw, DelegateTurnAction)
    assert err is None
    assert data.action == "speech"


def test_parse_json_block_invalid() -> None:
    raw = "no json here"
    data, err = parse_json_block(raw)
    assert data is None
    assert err is not None


def test_roll_deterministic() -> None:
    """同一 master_seed + directive_id → 同一 roll. 见 P1 验收."""
    s1, r1, _ = roll_directive(42, "d1")
    s2, r2, _ = roll_directive(42, "d1")
    assert s1 == s2
    assert r1 == r2
    # 不同 seed 或不同 id → 不同 roll(大概率)
    s3, r3, _ = roll_directive(99, "d1")
    assert s3 != s1


def test_outcome_tiers() -> None:
    assert outcome_tier(50) == "大成功"
    assert outcome_tier(40) == "大成功"
    assert outcome_tier(15) == "成功"
    assert outcome_tier(5) == "部分成功"
    assert outcome_tier(-5) == "失败"
    assert outcome_tier(-25) == "灾难性失败"


@pytest.mark.asyncio
async def test_delegate_agent_parses_speech(config: MunagentConfig) -> None:
    transport = _json_response(
        '```json\n{"action": "speech", "text": "我支持外交途径", "inner_thought": "先稳住局面"}\n```'
    )
    llm = LLMClient(config, transport=transport)
    seat = SeatSpec(
        id="premier",
        name="总理",
        venue="cabinet",
    )
    agent = DelegateAgent(llm, seat, background_summary="危机背景")
    task = TaskSpec(role="delegate", task="turn", phase="ModeratedCaucus")
    ctx = agent.build_turn_context(task, [], "ModeratedCaucus", "2026-03-15T09:00:00+08:00")
    action = await agent.act(task, ctx)
    assert isinstance(action, DelegateTurnAction)
    assert action.action == "speech"
    assert "外交" in action.text


@pytest.mark.asyncio
async def test_delegate_agent_fallback_on_garbage(config: MunagentConfig) -> None:
    transport = _json_response("这不是JSON")
    llm = LLMClient(config, transport=transport)
    seat = SeatSpec(id="premier", name="总理", venue="cabinet")
    agent = DelegateAgent(llm, seat, background_summary="背景")
    task = TaskSpec(role="delegate", task="turn", phase="ModeratedCaucus")
    ctx = agent.build_turn_context(task, [], "ModeratedCaucus", "2026-03-15T09:00:00+08:00")
    action = await agent.act(task, ctx)
    # 3 次都失败 → fallback pass
    assert isinstance(action, DelegateTurnAction)
    assert action.action == "pass"
