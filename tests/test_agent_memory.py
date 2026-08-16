"""代表长期记忆、历史摘要、相关性检索与无主持活动控制。"""

from __future__ import annotations

import json
from pathlib import Path
import threading
import time

import pytest

from agent.activity import UnchairedActivityController
from agent.inbox import (
    EventSnapshot,
    Observation,
    ObservationKind,
    ObservationPriority,
)
from agent.memory import AgentMemory, EventHistory, MemoryStatus
from agent.rep_agent import RepresentativeAgent
from agent.rep_agent_tools import RepresentativeToolExecutor
from agent.rep_context import build_activation_prompt
from llm import TextDelta, ToolCall, ToolCallsDelta
from scenario.scenario import Scenario
from scenario.venue import SessionPhase

TEMPLATE = Path(__file__).resolve().parent.parent / "scenario-template"
CHURCHILL = "winston_churchill"


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


def _snapshot(
    event_id: int,
    content: str,
    *,
    event_type: str = "message",
    status: str = "completed",
) -> EventSnapshot:
    return EventSnapshot(
        id=event_id,
        venue_id="main",
        event_type=event_type,
        content=content,
        status=status,
        time=f"1944-10-09T22:{event_id % 60:02d}:00+03:00",
        scope=(CHURCHILL,),
    )


def _observation(
    event_id: int,
    content: str,
    *,
    event_type: str = "message",
    priority: ObservationPriority = ObservationPriority.NORMAL,
    activates_agent: bool = True,
) -> Observation:
    return Observation(
        sequence=event_id + 1,
        kind=ObservationKind.EVENT_CREATED,
        priority=priority,
        activates_agent=activates_agent,
        event=_snapshot(event_id, content, event_type=event_type),
        actor_id="joseph_stalin",
    )


def _call(name: str, **args) -> ToolCall:
    return ToolCall(
        id=f"call_{name}",
        name=name,
        arguments=json.dumps(args, ensure_ascii=False),
    )


def test_agent_memory_merges_revises_and_retains_audit_status() -> None:
    memory = AgentMemory()
    memory.note_sequence(7)
    first = memory.remember(
        "commitment",
        "向苏方承诺不单方面改变希腊安排",
        importance=4,
        source_event_ids=[2],
    )
    merged = memory.remember(
        "commitment",
        "向苏方承诺不单方面改变希腊安排",
        importance=5,
        source_event_ids=[2, 6],
    )

    assert first.id == "m1"
    assert merged.id == "m1"
    assert merged.importance == 5
    assert merged.source_event_ids == (2, 6)

    memory.note_sequence(11)
    resolved = memory.revise("m1", status=MemoryStatus.RESOLVED)
    assert resolved.updated_sequence == 11
    assert memory.list_entries(status="active") == []
    assert memory.list_entries(status="resolved") == [resolved]


def test_memory_tools_validate_event_visibility_and_action_budget(
    scenario: Scenario,
) -> None:
    rep = scenario.reps[CHURCHILL]
    event = rep.send_message("希腊安排必须保持稳定")
    assert event.id is not None
    memory = AgentMemory()
    executor = RepresentativeToolExecutor(rep, memory=memory)

    remembered = json.loads(
        executor.execute(
            _call(
                "remember",
                category="belief",
                content="苏方把希腊视为可交换筹码",
                importance=4,
                source_event_ids=[event.id],
            )
        )
    )
    assert remembered["ok"] is True
    assert remembered["result"]["id"] == "m1"

    hidden = json.loads(
        executor.execute(
            _call(
                "remember",
                category="fact",
                content="不可验证信息",
                importance=2,
                source_event_ids=[999],
            )
        )
    )
    assert hidden["ok"] is False
    assert "不可见" in hidden["error"]

    executor.begin_turn(public_message_limit=1, event_action_limit=3)
    first = json.loads(executor.execute(_call("send_message", content="第一句话")))
    second = json.loads(executor.execute(_call("send_message", content="重复发言")))
    assert first["ok"] is True
    assert second["ok"] is False
    assert "额度已用尽" in second["error"]


def test_history_retrieves_old_relevant_event_and_summarizes_remainder() -> None:
    history = EventHistory()
    for event_id in range(15):
        content = f"一般程序发言 {event_id}"
        if event_id == 1:
            content = "苏方提出罗马尼亚百分比必须保持九十"
        history.record(_observation(event_id, content))

    related = history.retrieve(
        "罗马尼亚百分比方案",
        exclude_event_ids=set(range(9, 15)),
        limit=2,
    )
    assert related[0].id == 1

    summaries = history.summarize(
        "早期程序",
        exclude_event_ids={event.id for event in related} | set(range(9, 15)),
        segment_size=3,
        limit=3,
    )
    assert summaries
    assert all(summary.event_ids for summary in summaries)
    assert any("一般程序发言" in summary.text for summary in summaries)


def test_activation_prompt_contains_memory_retrieval_and_history_summary(
    scenario: Scenario,
) -> None:
    rep = scenario.reps[CHURCHILL]
    memory = AgentMemory()
    memory.remember(
        "strategy",
        "用希腊安排交换苏方在罗马尼亚的让步",
        importance=5,
        source_event_ids=[1],
    )
    history = EventHistory()
    for event_id in range(12):
        content = f"旧谈判记录 {event_id}"
        if event_id == 1:
            content = "双方讨论希腊与罗马尼亚的交换关系"
        history.record(_observation(event_id, content))

    prompt = build_activation_prompt(
        rep,
        [_observation(20, "请重新评估罗马尼亚条件")],
        memory=memory,
        history=history,
        activity_guidance="测试行动限制",
    )

    assert "私有长期记忆" in prompt
    assert "用希腊安排交换" in prompt
    assert "相关旧事件" in prompt
    assert "双方讨论希腊" in prompt
    assert "更早历史摘要" in prompt
    assert "测试行动限制" in prompt


def test_unchaired_controller_stops_public_echo_until_substantive_event() -> None:
    controller = UnchairedActivityController(cooldown_s=0.5)
    first_public = [_observation(1, "第一轮公开发言")]
    assert controller.evaluate(
        SessionPhase.UNCHAIRED_CORE,
        first_public,
    ).should_activate

    controller.record_tools(SessionPhase.UNCHAIRED_CORE, ["send_message"])
    repeated = controller.evaluate(
        SessionPhase.UNCHAIRED_CORE,
        [_observation(2, "另一名代表跟进发言")],
    )
    assert repeated.should_activate is False

    substantive = controller.evaluate(
        SessionPhase.UNCHAIRED_CORE,
        [_observation(3, "新的私下条件", event_type="note")],
    )
    assert substantive.should_activate is True
    assert substantive.delay_s > 0

    urgent = controller.evaluate(
        SessionPhase.UNCHAIRED_CORE,
        [
            _observation(
                4,
                "紧急外部事件",
                event_type="system",
                priority=ObservationPriority.URGENT,
            )
        ],
    )
    assert urgent.should_activate is True
    assert urgent.delay_s == 0


def test_agent_run_suppresses_second_public_reaction_in_same_wave(
    scenario: Scenario,
) -> None:
    class SpeakingLLM:
        def __init__(self) -> None:
            self.calls = 0
            self.first_finished = threading.Event()
            self.substantive_called = threading.Event()

        def stop(self) -> None:
            pass

        async def stream(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                yield ToolCallsDelta(
                    calls=(
                        ToolCall(
                            id="call_speak",
                            name="send_message",
                            arguments=json.dumps(
                                {"content": "我提出一个明确交换条件"},
                                ensure_ascii=False,
                            ),
                        ),
                    )
                )
                return
            if self.calls == 2:
                self.first_finished.set()
            else:
                self.substantive_called.set()
            yield TextDelta("本轮结束。")

    venue = scenario.venues[0]
    venue.switch_phase(SessionPhase.UNCHAIRED_CORE)
    llm = SpeakingLLM()
    agent = RepresentativeAgent(
        scenario.reps[CHURCHILL],
        llm=llm,  # type: ignore[arg-type]
    )
    agent.coalesce_s = 0.02
    agent.activity.cooldown_s = 0.0
    thread = threading.Thread(target=agent.run)
    thread.start()

    agent.notify(_observation(30, "苏方提出初步条件"))
    assert llm.first_finished.wait(timeout=1.0)

    agent.notify(_observation(31, "苏方重复追问"))
    time.sleep(0.08)
    assert llm.calls == 2

    agent.notify(
        _observation(
            32,
            "苏方通过纸条给出新让步",
            event_type="note",
            priority=ObservationPriority.URGENT,
        )
    )
    assert llm.substantive_called.wait(timeout=1.0)

    agent.stop()
    thread.join(timeout=1.0)
    assert not thread.is_alive()
