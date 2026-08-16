from __future__ import annotations

from concurrent.futures import Future, InvalidStateError
import threading
from typing import TYPE_CHECKING

from agent.inbox import ObservationKind
from scenario.venue import (
    AgendaAddition,
    AgendaSwitch,
    EventEdit,
    EventStatusUpdate,
    EventSubmission,
    VenueCommand,
    _StopEventProcessing,
)

if TYPE_CHECKING:
    from engine.simulator import Simulator
    from event.event import Event
    from scenario.venue import Venue


class VenueEngine:
    """单个会场的推进循环;由 ``Simulator`` 在独立线程中调用 ``run``."""

    simulator: Simulator
    venue: Venue
    __started: threading.Event

    def __init__(self, simulator: Simulator, venue: Venue) -> None:
        self.simulator = simulator
        self.venue = venue
        self.__started = threading.Event()

    def wait_until_started(self, timeout: float | None = None) -> bool:
        """等待事件消费循环完成启动."""
        return self.__started.wait(timeout)

    def stop(self) -> None:
        """处理完已经入队的事件后停止会场循环."""
        self.venue._stop_event_processing()

    def run(self) -> None:
        """顺序处理本会场的命令队列，直到收到停止命令."""
        failure: BaseException | None = None
        try:
            self.venue._start_event_processing()
            self.__started.set()
            while True:
                command = self.venue._take_command()
                try:
                    if isinstance(command, _StopEventProcessing):
                        return
                    self._process_command(command)
                finally:
                    self.venue._command_done()
        except BaseException as exc:
            failure = exc
            raise
        finally:
            self.venue._finish_event_processing(failure)

    def _process_command(self, command: VenueCommand) -> None:
        if isinstance(command, EventSubmission):
            self._process_event_submission(command)
        elif isinstance(command, EventStatusUpdate):
            self._process_event_status(command)
        elif isinstance(command, EventEdit):
            self._process_event_edit(command)
        elif isinstance(command, AgendaSwitch):
            self._process_agenda_switch(command)
        elif isinstance(command, AgendaAddition):
            self._process_agenda_addition(command)
        else:
            raise TypeError(f"VenueEngine 收到未知命令: {type(command).__name__}")

    def _process_event_submission(self, submission: EventSubmission) -> None:
        if not self._start_result(submission.result):
            return
        try:
            self.venue._commit_event(submission)
        except Exception as exc:
            self._set_exception(submission.result, exc)
        else:
            self._publish_event(
                submission.event,
                ObservationKind.EVENT_CREATED,
                actor_id=submission.actor_id,
            )
            self._set_result(submission.result, submission.event)

    def _process_event_status(self, update: EventStatusUpdate) -> None:
        if not self._start_result(update.result):
            return
        try:
            status = self.venue._commit_event_status(update)
        except Exception as exc:
            self._set_exception(update.result, exc)
        else:
            self._publish_event(
                update.event,
                ObservationKind.EVENT_STATUS_CHANGED,
                actor_id=update.actor_id,
            )
            self._set_result(update.result, status)

    def _process_event_edit(self, edit: EventEdit) -> None:
        if not self._start_result(edit.result):
            return
        previous_scope = edit.event.scope
        try:
            self.venue._commit_event_edit(edit)
        except Exception as exc:
            self._set_exception(edit.result, exc)
        else:
            self._publish_event(
                edit.event,
                ObservationKind.EVENT_EDITED,
                recipients=previous_scope | edit.event.scope,
                changed_field=edit.field,
            )
            self._set_result(edit.result, None)

    def _process_agenda_switch(self, command: AgendaSwitch) -> None:
        if not self._start_result(command.result):
            return
        try:
            event = self.venue._commit_agenda_switch(command)
        except Exception as exc:
            self._set_exception(command.result, exc)
        else:
            if event is not None:
                self._publish_event(
                    event,
                    ObservationKind.EVENT_CREATED,
                    actor_id=command.rep_id,
                )
            self._set_result(command.result, None)

    def _process_agenda_addition(self, command: AgendaAddition) -> None:
        if not self._start_result(command.result):
            return
        try:
            event = self.venue._commit_agenda_addition(command)
        except Exception as exc:
            self._set_exception(command.result, exc)
        else:
            self._publish_event(
                event,
                ObservationKind.EVENT_CREATED,
                actor_id=command.rep_id,
            )
            self._set_result(command.result, None)

    def _publish_event(
        self,
        event: Event,
        kind: ObservationKind,
        *,
        actor_id: str | None = None,
        recipients: set[str] | None = None,
        changed_field: str | None = None,
    ) -> None:
        """通知 Simulator；独立 VenueEngine 单元测试可不绑定 Simulator。"""
        if self.simulator is None:
            return
        self.simulator._publish_event_observation(
            event,
            kind,
            actor_id=actor_id,
            recipients=recipients,
            changed_field=changed_field,
        )

    @staticmethod
    def _start_result(result: Future[object]) -> bool:
        if result.done():
            return False
        try:
            return result.set_running_or_notify_cancel()
        except RuntimeError:
            if result.done():
                return False
            raise

    @staticmethod
    def _set_result(result: Future[object], value: object) -> None:
        try:
            result.set_result(value)
        except InvalidStateError:
            pass

    @staticmethod
    def _set_exception(result: Future[object], exc: Exception) -> None:
        try:
            result.set_exception(exc)
        except InvalidStateError:
            pass
