"""代表事件经 Venue 命令队列交给 VenueEngine，并验证故障回传。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

import pytest

from event.event import Event, EventType, MessageEvent
from engine.venue_engine import VenueEngine
from scenario.scenario import Scenario
from scenario.venue import (
    EventSubmission,
    SessionPhase,
    VenueCommandTimeoutError,
    VenueEngineReentryError,
    VenueEngineStoppedError,
)

TEMPLATE = Path(__file__).resolve().parent.parent / "scenario-template"

CHURCHILL = "winston_churchill"
EDEN = "anthony_eden"


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


def test_venue_submit_event_forwards_to_event_list(scenario: Scenario) -> None:
    venue = scenario.venues[0]
    event = MessageEvent("测试转发", CHURCHILL, venue.id, scenario)

    venue.submit_event(event)

    assert venue.event_list is not None
    assert event.id is not None
    assert event in venue.event_list.get_events(CHURCHILL)


def test_representative_events_are_submitted_through_venue(
    scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    venue = scenario.venues[0]
    churchill = scenario.reps[CHURCHILL]
    forwarded: list[Event] = []
    direct_forward = venue.submit_event

    def record_and_forward(event: Event) -> None:
        forwarded.append(event)
        direct_forward(event)

    monkeypatch.setattr(venue, "submit_event", record_and_forward)

    churchill.send_message("公开发言")
    churchill.pass_note("私下沟通", EDEN)
    churchill.submit_motion_switch("动议自由讨论", SessionPhase.FREE_DISCUSSION)

    instruction = churchill.create_file("instruction.md", "执行内容", "测试指示")
    churchill.submit_instruction("提交指示", {CHURCHILL, EDEN}, instruction)

    resolution = churchill.create_file("resolution.md", "决议内容", "测试决议")
    churchill.submit_resolution("提交决议", {CHURCHILL, EDEN}, resolution)

    assert [event.type for event in forwarded] == [
        EventType.MESSAGE,
        EventType.NOTE,
        EventType.MOTION_SWITCH,
        EventType.INSTRUCTION,
        EventType.RESOLUTION,
    ]
    assert all(event.id is not None for event in forwarded)


def test_concurrent_submissions_are_committed_once_in_venue_engine(
    scenario: Scenario,
) -> None:
    venue = scenario.venues[0]
    assert venue.event_list is not None
    commit_threads: list[str] = []
    venue.event_list.add_listener(
        EventType.MESSAGE,
        lambda event: commit_threads.append(threading.current_thread().name),
    )

    events = [
        MessageEvent(f"并发发言 {index}", CHURCHILL, venue.id, scenario)
        for index in range(100)
    ]
    with ThreadPoolExecutor(max_workers=8) as executor:
        committed = list(executor.map(venue.submit_event, events))

    assert committed == events
    assert sorted(event.id for event in events if event.id is not None) == list(
        range(100)
    )
    assert set(venue.event_list.events) == set(events)
    assert len(commit_threads) == 100
    assert set(commit_threads) == {f"test-venue:{venue.id}"}


def test_submission_error_returns_to_caller_and_engine_continues(
    scenario: Scenario,
) -> None:
    venue = scenario.venues[0]
    invalid = MessageEvent("预设编号", CHURCHILL, venue.id, scenario)
    invalid.id = 9

    with pytest.raises(ValueError, match="应由 EventList._commit_event 设定"):
        venue.submit_event(invalid)

    valid = MessageEvent("错误后继续", CHURCHILL, venue.id, scenario)
    assert venue.submit_event(valid) is valid
    assert valid.id == 0


def test_listener_cannot_synchronously_submit_to_same_venue(
    scenario: Scenario,
) -> None:
    venue = scenario.venues[0]
    assert venue.event_list is not None

    def reenter(event: Event) -> None:
        if event.content == "触发重入":
            venue.submit_event(
                MessageEvent("listener 内提交", CHURCHILL, venue.id, scenario)
            )

    venue.event_list.add_listener(EventType.MESSAGE, reenter)

    with pytest.raises(VenueEngineReentryError, match="不能同步提交"):
        venue.submit_event(
            MessageEvent("触发重入", CHURCHILL, venue.id, scenario)
        )

    followup = MessageEvent("重入错误后继续", CHURCHILL, venue.id, scenario)
    assert venue.submit_event(followup) is followup


def test_command_timeout_closes_venue_and_fails_future_commands(
    scenario: Scenario,
) -> None:
    venue = scenario.venues[0]
    assert venue.event_list is not None
    venue.command_timeout_s = 0.05
    entered = threading.Event()
    release = threading.Event()

    def block(event: Event) -> None:
        if event.content == "阻塞命令":
            entered.set()
            release.wait(timeout=2.0)

    venue.event_list.add_listener(EventType.MESSAGE, block)

    with pytest.raises(VenueCommandTimeoutError) as caught:
        venue.submit_event(
            MessageEvent("阻塞命令", CHURCHILL, venue.id, scenario)
        )
    assert entered.is_set()
    assert venue.event_failure is caught.value

    with pytest.raises(VenueEngineStoppedError) as stopped:
        venue.submit_event(
            MessageEvent("超时后提交", CHURCHILL, venue.id, scenario)
        )
    assert stopped.value.engine_failure is caught.value
    release.set()


def test_engine_failure_fails_current_and_queued_submissions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FatalVenueFailure(BaseException):
        pass

    loaded = Scenario()
    loaded.load(str(TEMPLATE))
    loaded.root_path = tmp_path
    (tmp_path / "simulation").mkdir()
    loaded.initialize()
    venue = loaded.venues[0]
    assert venue.event_list is not None

    entered_listener = threading.Event()
    release_listener = threading.Event()
    fatal = FatalVenueFailure("测试致命故障")

    def fail_listener(event: Event) -> None:
        if event.content != "触发故障":
            return
        entered_listener.set()
        if not release_listener.wait(timeout=2.0):
            raise TimeoutError("测试未能及时释放 listener")
        raise fatal

    venue.event_list.add_listener(EventType.MESSAGE, fail_listener)
    engine = VenueEngine(None, venue)  # type: ignore[arg-type]
    engine_failures: list[BaseException] = []

    def run_engine() -> None:
        try:
            engine.run()
        except BaseException as exc:
            engine_failures.append(exc)

    engine_thread = threading.Thread(target=run_engine, name="fatal-venue-test")
    engine_thread.start()
    assert engine.wait_until_started(timeout=2.0)

    first = MessageEvent("触发故障", CHURCHILL, venue.id, loaded)
    second = MessageEvent("排队等待", CHURCHILL, venue.id, loaded)
    second_queued = threading.Event()
    original_submit = venue._submit_command

    def record_submit(command) -> None:
        original_submit(command)
        if isinstance(command, EventSubmission) and command.event is second:
            second_queued.set()

    monkeypatch.setattr(venue, "_submit_command", record_submit)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_result = executor.submit(venue.submit_event, first)
        assert entered_listener.wait(timeout=2.0)
        second_result = executor.submit(venue.submit_event, second)
        assert second_queued.wait(timeout=2.0)
        release_listener.set()

        with pytest.raises(VenueEngineStoppedError) as first_error:
            first_result.result(timeout=2.0)
        with pytest.raises(VenueEngineStoppedError) as second_error:
            second_result.result(timeout=2.0)

    engine_thread.join(timeout=2.0)
    assert not engine_thread.is_alive()
    assert engine_failures == [fatal]
    assert first_error.value.engine_failure is fatal
    assert second_error.value.engine_failure is fatal

    after_failure = MessageEvent("故障后提交", CHURCHILL, venue.id, loaded)
    with pytest.raises(VenueEngineStoppedError) as stopped:
        venue.submit_event(after_failure)
    assert stopped.value.engine_failure is fatal
