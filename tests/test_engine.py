"""引擎集成测试: mock LLM 跑通 P2 会议机制."""

from __future__ import annotations

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
    """Mock LLM: 根据请求内容返回预设响应."""

    def __init__(self, config, *, delegate_action="speech", motion_type="") -> None:
        super().__init__(config)
        self._delegate_action = delegate_action
        self._motion_type = motion_type

    async def chat(self, request: ChatRequest) -> str:
        task = request.task

        if task == "next_speaker":
            return '```json\n{"seat": "premier", "reason": "总理先发言", "inner_thought": ""}\n```'
        if task == "phase_decision":
            return '```json\n{"action": "adjourn", "announcement": "会议结束"}\n```'
        if task == "adjudicate":
            last = request.messages[-1].content
            if "评估" in last:
                return '```json\n{"probability_tier": 70, "reasoning": "ok", "takes_effect_at": "2026-03-15T10:00:00+08:00", "visible_consequences": "ok"}\n```'
            return '```json\n{"narrative_full": "结果ok", "per_venue_visible": [{"venue": "cabinet", "text": "内阁收到结果"}], "author_private_result": "已执行", "suggest_broadcast": "immediate"}\n```'
        if task == "vote":
            return '```json\n{"choice": "aye", "inner_thought": "支持"}\n```'
        if task == "motion_ruling":
            return '```json\n{"ruling": "accept", "reason": "合理", "inner_thought": ""}\n```'
        if task == "appeal_ruling":
            return '```json\n{"ruling": "overrule", "reason": "主持不公"}\n```'
        if task == "caucus_switch":
            return '```json\n{"action": "switch", "to_phase": "UnmoderatedCaucus", "announcement": "进入磋商", "inner_thought": ""}\n```'

        # delegate turn
        if self._delegate_action == "speech":
            return '```json\n{"action": "speech", "text": "我支持外交途径", "inner_thought": "先稳住", "motion_type": "", "motion_target": ""}\n```'
        if self._delegate_action == "motion":
            mt = self._motion_type or "caucus_switch"
            return f'```json\n{{"action": "motion", "text": "提议进入磋商", "inner_thought": "想私下谈", "motion_type": "{mt}", "motion_target": ""}}\n```'
        if self._delegate_action == "write_directive":
            return '```json\n{"action": "write_directive", "text": "", "inner_thought": "要动员", "directive": {"kind": "personal", "title": "边境动员", "body": "调动陆军", "uses_powers": ["调动陆军部队进行边境演习"]}}\n```'
        return '```json\n{"action": "pass", "text": "", "inner_thought": ""}\n```'

    async def test_provider(self, name=None):
        return UsageRecord(role="delegate", task="test", model="m", provider="p", prompt_tokens=1, completion_tokens=1)


@pytest.mark.asyncio
async def test_engine_mod_speech_loop() -> None:
    """基本 ModCaucus 发言循环."""
    sc = load_scenario(SCENARIO_DIR)
    config = _make_config()
    db = tempfile.mktemp(suffix=".db")

    engine = Engine(sc, config, master_seed=42, max_steps=3, db_path=db)
    engine._llm = MockLLM(config)
    result = await engine.run()

    assert result.total_steps >= 3
    types = {e.type for e in result.events}
    assert "speech" in types
    assert "phase_change" in types


@pytest.mark.asyncio
async def test_engine_motion_triggers_phase_switch() -> None:
    """动议 caucus_switch 触发 Mod→Unmod 切换."""
    sc = load_scenario(SCENARIO_DIR)
    config = _make_config()
    db = tempfile.mktemp(suffix=".db")

    engine = Engine(sc, config, master_seed=42, max_steps=5, db_path=db)
    engine._llm = MockLLM(config, delegate_action="motion", motion_type="caucus_switch")
    result = await engine.run()

    types = {e.type for e in result.events}
    assert "motion" in types
    assert "motion_ruling" in types


@pytest.mark.asyncio
async def test_engine_directive_adjudication() -> None:
    """写指令 → DM 判定 → crisis_update."""
    sc = load_scenario(SCENARIO_DIR)
    config = _make_config()
    db = tempfile.mktemp(suffix=".db")

    engine = Engine(sc, config, master_seed=42, max_steps=3, db_path=db)
    engine._llm = MockLLM(config, delegate_action="write_directive")
    result = await engine.run()

    types = {e.type for e in result.events}
    assert "directive_submitted" in types
    assert "adjudication" in types
    assert "crisis_update" in types


@pytest.mark.asyncio
async def test_engine_seed_reproducible() -> None:
    """同一 seed 两次运行掷骰一致."""
    sc = load_scenario(SCENARIO_DIR)
    config = _make_config()

    db1 = tempfile.mktemp(suffix=".db")
    e1 = Engine(sc, config, master_seed=123, max_steps=3, db_path=db1)
    e1._llm = MockLLM(config, delegate_action="write_directive")
    r1 = await e1.run()

    db2 = tempfile.mktemp(suffix=".db")
    e2 = Engine(sc, config, master_seed=123, max_steps=3, db_path=db2)
    e2._llm = MockLLM(config, delegate_action="write_directive")
    r2 = await e2.run()

    rolls1 = [e.rng["rolls"] for e in r1.events if e.type == "adjudication" and e.rng]
    rolls2 = [e.rng["rolls"] for e in r2.events if e.type == "adjudication" and e.rng]
    assert rolls1 == rolls2


@pytest.mark.asyncio
async def test_replay_viewpoint_filter() -> None:
    """回放按视角过滤."""
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
    await bus.close()
