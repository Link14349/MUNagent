"""代表 Agent Inbox、观察合并和轮次中断。"""

from __future__ import annotations

import asyncio
from pathlib import Path
import threading
import time

import pytest

from agent.inbox import (
    AgentInbox,
    EventSnapshot,
    Observation,
    ObservationKind,
    ObservationPriority,
)
from agent.rep_agent import AgentTurnInterrupted, RepresentativeAgent
from llm import LLMCancelledError, TextDelta
from scenario.scenario import Scenario

TEMPLATE = Path(__file__).resolve().parent.parent / "scenario-template"


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


def _observation(
    sequence: int,
    *,
    priority: ObservationPriority = ObservationPriority.NORMAL,
    activates_agent: bool = True,
) -> Observation:
    return Observation(
        sequence=sequence,
        kind=ObservationKind.EVENT_CREATED,
        priority=priority,
        activates_agent=activates_agent,
        event=EventSnapshot(
            id=sequence,
            venue_id="main",
            event_type="message",
            content=f"观察 {sequence}",
            status="completed",
            time="1944-10-09T22:00:00+03:00",
            scope=("winston_churchill",),
        ),
    )


def test_inbox_coalesces_normal_observations_in_fixed_window() -> None:
    inbox = AgentInbox()
    result: list[list[Observation] | None] = []
    started = threading.Event()

    def consume() -> None:
        started.set()
        result.append(inbox.take_batch(coalesce_s=0.08))

    thread = threading.Thread(target=consume)
    thread.start()
    assert started.wait(timeout=1.0)

    inbox.put(_observation(1))
    time.sleep(0.02)
    assert thread.is_alive()
    inbox.put(_observation(2))

    thread.join(timeout=1.0)
    assert not thread.is_alive()
    assert result[0] is not None
    assert [item.sequence for item in result[0]] == [1, 2]


def test_inbox_urgent_observation_skips_remaining_window() -> None:
    inbox = AgentInbox()
    result: list[list[Observation] | None] = []
    thread = threading.Thread(
        target=lambda: result.append(inbox.take_batch(coalesce_s=1.0))
    )
    thread.start()

    inbox.put(_observation(1, priority=ObservationPriority.URGENT))
    thread.join(timeout=0.2)

    assert not thread.is_alive()
    assert result[0] is not None
    assert [item.sequence for item in result[0]] == [1]


def test_inbox_close_wakes_waiting_consumer() -> None:
    inbox = AgentInbox()
    result: list[list[Observation] | None] = []
    thread = threading.Thread(target=lambda: result.append(inbox.take_batch()))
    thread.start()

    inbox.close()
    thread.join(timeout=1.0)

    assert result == [None]


def test_agent_run_batches_observations_into_one_local_context(
    scenario: Scenario,
) -> None:
    class RecordingLLM:
        def __init__(self) -> None:
            self.requests = []
            self.called = threading.Event()

        def stop(self) -> None:
            pass

        async def stream(self, messages, **kwargs):
            self.requests.append(list(messages))
            self.called.set()
            yield TextDelta("本轮无需行动。")

    llm = RecordingLLM()
    agent = RepresentativeAgent(
        scenario.reps["winston_churchill"],
        llm=llm,  # type: ignore[arg-type]
    )
    agent.coalesce_s = 0.08
    thread = threading.Thread(target=agent.run)
    thread.start()

    agent.notify(_observation(1))
    time.sleep(0.02)
    agent.notify(_observation(2))

    assert llm.called.wait(timeout=1.0)
    agent.stop()
    thread.join(timeout=1.0)

    assert len(llm.requests) == 1
    assert len(llm.requests[0]) == 2
    prompt = llm.requests[0][1].content
    assert "观察序号 1" in prompt
    assert "观察序号 2" in prompt


@pytest.mark.asyncio
async def test_urgent_observation_interrupts_active_llm_turn(
    scenario: Scenario,
) -> None:
    class BlockingLLM:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

        async def stream(self, messages, **kwargs):
            self.started.set()
            while not self.stopped:
                await asyncio.sleep(0.01)
            raise LLMCancelledError("测试紧急中断")
            yield  # pragma: no cover

    llm = BlockingLLM()
    agent = RepresentativeAgent(
        scenario.reps["winston_churchill"],
        llm=llm,  # type: ignore[arg-type]
    )
    turn = asyncio.create_task(agent.step("根据当前会场状态制定行动。"))
    await asyncio.wait_for(llm.started.wait(), timeout=1.0)

    agent.notify(_observation(1, priority=ObservationPriority.URGENT))

    with pytest.raises(AgentTurnInterrupted, match="紧急观察"):
        await turn
    assert agent.inbox.take_ready()[0].sequence == 1


@pytest.mark.asyncio
async def test_step_replaces_previous_local_context(scenario: Scenario) -> None:
    class RecordingLLM:
        def __init__(self) -> None:
            self.requests = []

        def stop(self) -> None:
            pass

        async def stream(self, messages, **kwargs):
            self.requests.append(list(messages))
            yield TextDelta("完成。")

    llm = RecordingLLM()
    agent = RepresentativeAgent(
        scenario.reps["winston_churchill"],
        llm=llm,  # type: ignore[arg-type]
    )

    await agent.step("仅属于第一轮的临时内容")
    await agent.step("第二轮输入")

    assert len(llm.requests) == 2
    assert len(llm.requests[1]) == 2
    assert "仅属于第一轮" not in llm.requests[1][1].content
    assert agent.messages[1].content == "第二轮输入"
