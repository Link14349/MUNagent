"""引擎集成测试: mock LLM 跑通 P1 闭环."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from munagent.config.models import MunagentConfig, ProviderConfig, RoleConfig
from munagent.core.scenario import load_scenario
from munagent.llm.client import LLMClient, ChatRequest
from munagent.llm.usage import UsageRecord
from munagent.engine import Engine

SCENARIO_DIR = Path(__file__).parent.parent / "scenarios" / "cabinet-crisis"


def _make_config() -> MunagentConfig:
    return MunagentConfig(
        providers={"deepseek": ProviderConfig(base_url="https://x", api_key="sk-test")},
        roles={
            "delegate": RoleConfig(provider="deepseek", model="deepseek-v4-flash"),
            "chair": RoleConfig(provider="deepseek", model="deepseek-v4-pro"),
            "dm": RoleConfig(provider="deepseek", model="deepseek-v4-pro"),
        },
    )


class MockLLM(LLMClient):
    """直接返回 mock 响应, 不走 httpx."""

    def __init__(self, config, *, write_directive=False) -> None:
        super().__init__(config)
        self._write_directive = write_directive
        self.call_count = 0

    async def chat(self, request: ChatRequest) -> str:
        self.call_count += 1
        if request.task == "next_speaker":
            return '```json\n{"seat": "premier", "reason": "总理先发言"}\n```'
        if request.task == "phase_decision":
            return '```json\n{"action": "adjourn", "announcement": "会议结束"}\n```'
        if request.task == "adjudicate":
            last = request.messages[-1].content
            if "评估" in last:
                return '```json\n{"probability_tier": 70, "reasoning": "有一定把握", "takes_effect_at": "2026-03-15T10:00:00+08:00", "visible_consequences": "变化"}\n```'
            return '```json\n{"narrative_full": "指令执行", "per_venue_visible": [{"venue": "cabinet", "text": "内阁收到结果"}], "author_private_result": "已执行", "suggest_broadcast": "immediate"}\n```'
        # delegate turn
        if self._write_directive:
            return '```json\n{"action": "write_directive", "text": "", "inner_thought": "要动员", "directive": {"kind": "personal", "title": "边境动员", "body": "调动陆军", "uses_powers": ["调动陆军部队进行边境演习"]}}\n```'
        return '```json\n{"action": "speech", "text": "我认为应该优先外交途径", "inner_thought": "先稳住局面"}\n```'

    async def test_provider(self, name=None):
        return UsageRecord(role="delegate", task="test", model="m", provider="p", prompt_tokens=1, completion_tokens=1)


@pytest.mark.asyncio
async def test_engine_runs_full_loop() -> None:
    """P1 验收: 全 AI 跑 >=3 轮闭环."""
    sc = load_scenario(SCENARIO_DIR)
    config = _make_config()
    db = tempfile.mktemp(suffix=".db")

    engine = Engine(sc, config, master_seed=42, max_steps=5, db_path=db)
    engine._llm = MockLLM(config)
    result = await engine.run()

    assert result.total_steps >= 3
    types = {e.type for e in result.events}
    assert "phase_change" in types
    assert "speech" in types
    assert "clock_advance" in types


@pytest.mark.asyncio
async def test_engine_seed_reproducible() -> None:
    """P1 验收: 同一 master_seed 两次运行掷骰结果一致."""
    sc = load_scenario(SCENARIO_DIR)
    config = _make_config()

    db1 = tempfile.mktemp(suffix=".db")
    engine1 = Engine(sc, config, master_seed=123, max_steps=3, db_path=db1)
    engine1._llm = MockLLM(config, write_directive=True)
    r1 = await engine1.run()

    db2 = tempfile.mktemp(suffix=".db")
    engine2 = Engine(sc, config, master_seed=123, max_steps=3, db_path=db2)
    engine2._llm = MockLLM(config, write_directive=True)
    r2 = await engine2.run()

    rolls1 = [e.rng["rolls"] for e in r1.events if e.type == "adjudication" and e.rng]
    rolls2 = [e.rng["rolls"] for e in r2.events if e.type == "adjudication" and e.rng]
    assert rolls1 == rolls2


@pytest.mark.asyncio
async def test_replay_viewpoint_filter() -> None:
    """P1 验收: 回放按视角过滤正确."""
    from munagent.core.bus import EventBus

    sc = load_scenario(SCENARIO_DIR)
    config = _make_config()
    db = tempfile.mktemp(suffix=".db")

    engine = Engine(sc, config, master_seed=42, max_steps=3, db_path=db)
    engine._llm = MockLLM(config)
    result = await engine.run()
    sid = result.session_id

    bus = EventBus(db, sid)
    await bus.init_db()
    god_events = await bus.query("god")
    seat_events = await bus.query("seat:premier")

    assert len(god_events) >= len(seat_events)
    for e in seat_events:
        assert e.scope != "dm-only"
    for e in seat_events:
        if e.scope == "self":
            assert "seat:premier" in (e.visible_to or [])
    await bus.close()
