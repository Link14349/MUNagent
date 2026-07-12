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
                return '```json\n{"probability_tier": 70, "reasoning": "ok", "takes_effect_at": "2026-03-15T05:00:00Z", "visible_consequences": "ok"}\n```'
            return '```json\n{"narrative_full": "结果ok", "per_venue_visible": [{"venue": "cabinet", "text": "内阁收到结果"}], "author_private_result": "已执行", "suggest_broadcast": "immediate"}\n```'
        if task == "clock_decision":
            return '```json\n{"advance_to": "2026-03-15T02:30:00Z", "reason": "小步推进"}\n```'
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


class TestDocLines:
    """草案线模型(D16): 编号分配/修订/分叉/作废. 见06§2."""

    def _engine(self):
        scenario = load_scenario(str(SCENARIO_DIR))
        return Engine(scenario, _make_config(), master_seed=42, db_path=":memory:")

    def _draft(self, title="草案A", body="第一条 xxx", co_sponsors=None, revises=None):
        from munagent.agents.delegate import DirectiveDraft

        return DirectiveDraft(kind="directive", title=title, body=body,
                              co_sponsors=co_sponsors or [], revises=revises)

    def test_new_line_numbering(self) -> None:
        eng = self._engine()
        a1 = eng._assign_doc_number(self._draft(), "premier")
        a2 = eng._assign_doc_number(self._draft(title="草案B"), "foreign_minister")
        assert (a1["doc_line"], a1["version"]) == ("D1.1", 1)
        assert (a2["doc_line"], a2["version"]) == ("D1.2", 1)

    def test_sponsor_revision_same_line(self) -> None:
        eng = self._engine()
        a1 = eng._assign_doc_number(self._draft(co_sponsors=["foreign_minister"]), "premier")
        eng._register_doc_version(a1, {"directive_id": "D1.1-v1", "title": "草案A",
                                       "body": "第一条 xxx", "author": "premier",
                                       "co_sponsors": ["foreign_minister"]})
        # 联署人修订 → 同线 v2, parent 指向 v1
        a2 = eng._assign_doc_number(self._draft(body="第一条 yyy", revises="D1.1"), "foreign_minister")
        assert (a2["doc_line"], a2["version"], a2["parent"]) == ("D1.1", 2, "D1.1-v1")

    def test_outsider_revision_forks(self) -> None:
        eng = self._engine()
        a1 = eng._assign_doc_number(self._draft(), "premier")
        eng._register_doc_version(a1, {"directive_id": "D1.1-v1", "title": "草案A",
                                       "body": "第一条 xxx", "author": "premier",
                                       "co_sponsors": []})
        # 外人修订 → 分叉新线
        a2 = eng._assign_doc_number(self._draft(body="第一条 zzz", revises="D1.1"), "defense_minister")
        assert a2["doc_line"] == "D1.2"
        assert a2["forked_from"] == "D1.1-v1"
        assert a2["parent"] is None

    def test_revises_by_title_fallback(self) -> None:
        eng = self._engine()
        a1 = eng._assign_doc_number(self._draft(title="边境方案"), "premier")
        eng._register_doc_version(a1, {"directive_id": "D1.1-v1", "title": "边境方案",
                                       "body": "x", "author": "premier", "co_sponsors": []})
        a2 = eng._assign_doc_number(self._draft(revises="边境方案"), "premier")
        assert (a2["doc_line"], a2["version"]) == ("D1.1", 2)

    def test_diff_summary_deterministic(self) -> None:
        eng = self._engine()
        d1 = eng._diff_summary("第一条 甲\n第二条 乙", "第一条 甲\n第二条 丙")
        d2 = eng._diff_summary("第一条 甲\n第二条 乙", "第一条 甲\n第二条 丙")
        assert d1 == d2
        assert "-第二条 乙" in d1 and "+第二条 丙" in d1

    def test_rejected_line_revision_forks(self) -> None:
        eng = self._engine()
        a1 = eng._assign_doc_number(self._draft(), "premier")
        eng._register_doc_version(a1, {"directive_id": "D1.1-v1", "title": "草案A",
                                       "body": "x", "author": "premier", "co_sponsors": []})
        eng._doc_lines["D1.1"]["status"] = "rejected"
        # 线已关闭, 即使发起人本人也只能fork重开
        a2 = eng._assign_doc_number(self._draft(revises="D1.1"), "premier")
        assert a2["doc_line"] == "D1.2"
        assert a2["forked_from"] == "D1.1-v1"

    def test_agenda_no_increments_on_reenter_mod(self) -> None:
        eng = self._engine()
        eng._on_enter_moderated_caucus("Opening")
        a1 = eng._assign_doc_number(self._draft(), "premier")
        assert a1["doc_line"] == "D1.1"
        a2 = eng._assign_doc_number(self._draft(title="B"), "foreign_minister")
        assert a2["doc_line"] == "D1.2"
        eng._on_enter_moderated_caucus("UnmoderatedCaucus")
        assert eng._agenda_no == 2
        a3 = eng._assign_doc_number(self._draft(title="C"), "premier")
        assert a3["doc_line"] == "D2.1"

    def test_supersede_only_same_agenda_prefix(self) -> None:
        eng = self._engine()
        eng._doc_lines = {
            "D1.1": {"status": "active", "versions": [{"directive_id": "D1.1-v1"}]},
            "D2.1": {"status": "active", "versions": [{"directive_id": "D2.1-v1"}]},
            "D2.2": {"status": "active", "versions": [{"directive_id": "D2.2-v1"}]},
        }
        from munagent.core.bus import EventBus
        from munagent.core.state_machine import VenueStateMachine

        bus = EventBus(":memory:", eng.session_id)
        sm = VenueStateMachine("cabinet", ["premier"], "ModeratedCaucus", "2026-03-15T09:00:00+08:00")
        eng._supersede_other_lines(bus, sm, "D2.1")
        assert eng._doc_lines["D1.1"]["status"] == "active"
        assert eng._doc_lines["D2.2"]["status"] == "superseded"


class TestDocsDossier:
    """文件档案区: 只显示各线当前版本, 隐藏历史版; 私密指令仅本人可见."""

    def _engine_with_lines(self):
        eng = TestDocLines._engine(TestDocLines())
        d = TestDocLines._draft(TestDocLines(), title="原始草案", body="v1正文")
        a1 = eng._assign_doc_number(d, "premier")
        eng._register_doc_version(a1, {"directive_id": "D1.1-v1", "title": "原始草案",
                                       "body": "v1正文", "author": "premier",
                                       "co_sponsors": ["foreign_minister"]})
        # 联署人修订 → D1.1-v2(同线)
        a2 = eng._assign_doc_number(
            TestDocLines._draft(TestDocLines(), body="v2正文", revises="D1.1"), "foreign_minister")
        eng._register_doc_version(a2, {"directive_id": "D1.1-v2", "title": "原始草案(修订)",
                                       "body": "v2正文", "author": "foreign_minister",
                                       "co_sponsors": []})
        # 外人分叉 → D1.2-v1(对抗版)
        a3 = eng._assign_doc_number(
            TestDocLines._draft(TestDocLines(), title="对抗版", body="fork正文", revises="D1.1"),
            "defense_minister")
        eng._register_doc_version(a3, {"directive_id": "D1.2-v1", "title": "对抗版",
                                       "body": "fork正文", "author": "defense_minister",
                                       "co_sponsors": []})
        return eng

    def test_shows_current_versions_hides_history(self) -> None:
        eng = self._engine_with_lines()
        dossier = eng._docs_dossier("premier")
        # 两个"当前可用版本"并列可见
        assert "D1.1-v2" in dossier and "v2正文" in dossier
        assert "D1.2-v1" in dossier and "fork正文" in dossier
        # 历史版本(v1)隐藏
        assert "v1正文" not in dossier

    def test_superseded_line_hidden(self) -> None:
        eng = self._engine_with_lines()
        eng._doc_lines["D1.2"]["status"] = "superseded"
        dossier = eng._docs_dossier("premier")
        assert "fork正文" not in dossier

    def test_merged_line_in_effective_section(self) -> None:
        eng = self._engine_with_lines()
        eng._doc_lines["D1.1"]["status"] = "merged"
        dossier = eng._docs_dossier("premier")
        assert "已通过生效的文件" in dossier
        assert "v2正文" in dossier

    def test_private_directives_only_for_author(self) -> None:
        eng = self._engine_with_lines()
        eng._directive_index["d-x-1"] = {"directive_id": "d-x-1", "kind": "personal",
                                         "title": "秘密调兵", "body": "调动第1师",
                                         "author": "defense_minister", "co_sponsors": []}
        assert "秘密调兵" in eng._docs_dossier("defense_minister")
        assert "秘密调兵" not in eng._docs_dossier("premier")


class TestCrisisNoteVisibility:
    """危机笔记: 送达后收件人能读到内容; 截获时收件人一无所知."""

    def test_delivered_note_in_recipient_dossier(self) -> None:
        eng = TestDocLines._engine(TestDocLines())
        eng._directive_index["d-x-1"] = {
            "directive_id": "d-x-1", "kind": "crisis_note", "title": "密约",
            "body": "支持我我给你军费", "author": "defense_minister",
            "co_sponsors": [], "recipient": "foreign_minister", "delivered": True,
        }
        d = eng._docs_dossier("foreign_minister")
        assert "你收到的危机笔记" in d and "支持我我给你军费" in d
        assert "来自 defense_minister" in d
        # 无关第三方看不到
        assert "密约" not in eng._docs_dossier("premier")

    def test_intercepted_note_not_in_recipient_dossier(self) -> None:
        eng = TestDocLines._engine(TestDocLines())
        eng._directive_index["d-x-2"] = {
            "directive_id": "d-x-2", "kind": "crisis_note", "title": "密约",
            "body": "x", "author": "defense_minister",
            "co_sponsors": [], "recipient": "foreign_minister", "delivered": False,
        }
        assert "密约" not in eng._docs_dossier("foreign_minister")
        # 作者自己仍看得到自己递过的笔记(不知道是否被截获)
        assert "密约" in eng._docs_dossier("defense_minister")

    def test_note_delivered_render_includes_body(self) -> None:
        from munagent.core.events import Event
        from munagent.core.render import render

        e = Event(session_id="s", type="note_delivered", actor="system", venue_id="v",
                  scope="private", visible_to=["seat:a", "seat:b"],
                  payload={"directive_id": "d-1", "recipient": "b", "from": "a",
                           "title": "密信", "body": "今夜行动"},
                  story_time="2026-03-15T01:00:00Z")
        out = render(e)
        assert "来自 a" in out and "《密信》" in out and "今夜行动" in out


class TestClockAdvanceValidation:
    """主席跳时校验: 只许向前、限最大步长、拒绝非法输入、不得越过在途生效点."""

    def test_valid_forward_jump(self) -> None:
        out = Engine._validate_clock_advance(
            "2026-03-15T01:00:00Z", "2026-03-15T05:00:00Z")
        assert out == "2026-03-15T05:00:00Z"

    def test_rejects_backward_and_same(self) -> None:
        assert Engine._validate_clock_advance(
            "2026-03-15T01:00:00Z", "2026-03-15T00:00:00Z") is None
        assert Engine._validate_clock_advance(
            "2026-03-15T01:00:00Z", "2026-03-15T01:00:00Z") is None

    def test_rejects_oversized_jump_and_garbage(self) -> None:
        assert Engine._validate_clock_advance(
            "2026-03-15T01:00:00Z", "2026-03-18T01:00:00Z") is None
        assert Engine._validate_clock_advance(
            "2026-03-15T01:00:00Z", "尽快") is None
        assert Engine._validate_clock_advance(
            "2026-03-15T01:00:00Z", "2026-03-15T05:00:00") is None  # 无时区

    def test_rejects_jump_past_pending_effect(self) -> None:
        assert Engine._validate_clock_advance(
            "2026-03-15T01:00:00Z",
            "2026-03-15T06:00:00Z",
            pending_effect_times=["2026-03-15T05:00:00Z"],
        ) is None

    def test_allows_jump_to_pending_effect(self) -> None:
        out = Engine._validate_clock_advance(
            "2026-03-15T01:00:00Z",
            "2026-03-15T05:00:00Z",
            pending_effect_times=["2026-03-15T05:00:00Z"],
        )
        assert out == "2026-03-15T05:00:00Z"


def test_presidium_g_includes_timeline_and_story_design() -> None:
    """时间线与剧情设计进 DM/主席 G 段(主席团专用, 代表G段不含)."""
    from munagent.agents.chair import build_chair_g
    from munagent.agents.dm import build_dm_g
    from munagent.agents.delegate import build_delegate_g_global

    sc = load_scenario(SCENARIO_DIR)
    for g in (build_dm_g(sc), build_chair_g(sc)):
        assert "时间线关键节点" in g
        assert "剧情走向与时间线设计" in g
        assert "邻国内阁会议" in g  # 具体节点
    delegate_g = build_delegate_g_global(sc, sc.venues[0].id)
    assert "剧情走向与时间线设计" not in delegate_g  # 代表不可见


@pytest.mark.asyncio
async def test_adjudication_persists_takes_effect_at() -> None:
    sc = load_scenario(SCENARIO_DIR)
    config = _make_config()
    db = tempfile.mktemp(suffix=".db")

    engine = Engine(sc, config, master_seed=42, max_steps=3, db_path=db)
    engine._llm = MockLLM(config, delegate_action="write_directive")
    result = await engine.run()

    adj = [e for e in result.events if e.type == "adjudication"]
    assert adj
    assert adj[0].payload.get("takes_effect_at") == "2026-03-15T05:00:00Z"


@pytest.mark.asyncio
async def test_resume_skips_opening_and_restores_clock() -> None:
    """续推不重复 Opening phase_change, 且故事时间从 clock_advance 恢复."""
    sc = load_scenario(SCENARIO_DIR)
    config = _make_config()
    db = tempfile.mktemp(suffix=".db")

    engine = Engine(sc, config, master_seed=42, max_steps=3, db_path=db)
    engine._llm = MockLLM(config, delegate_action="write_directive")
    first = await engine.run()
    session_id = first.session_id

    resume = Engine(sc, config, master_seed=42, max_steps=2, db_path=db)
    resume.session_id = session_id
    resume._llm = MockLLM(config)
    second = await resume.run()

    from munagent.core.bus import EventBus
    from munagent.core.reducer import reduce

    bus = EventBus(db, session_id)
    await bus.init_db()
    all_events = await bus.query("god")
    await bus.close()

    opening_changes = [
        e for e in all_events
        if e.type == "phase_change" and e.payload.get("from") == "Opening"
    ]
    assert len(opening_changes) == 1

    chair_clocks = [
        e for e in all_events
        if e.type == "clock_advance" and e.actor == "chair"
    ]
    assert chair_clocks
    assert chair_clocks[-1].payload.get("to") == "2026-03-15T02:30:00Z"

    state = reduce(all_events, session_id)
    # 续推后至少恢复到主席跳时; 续推步内发言还会按 clock_rate 累加
    assert state.venues["cabinet"].story_time >= "2026-03-15T02:30:00Z"
    assert second.total_steps >= 1
