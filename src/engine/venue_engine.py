from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from scenario.venue import EventSubmission, _StopEventProcessing

if TYPE_CHECKING:
    from engine.simulator import Simulator
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
        """顺序处理本会场的事件提交队列，直到收到停止命令."""
        self.venue._start_event_processing()
        self.__started.set()
        while True:
            submission = self.venue._take_event_submission()
            try:
                if isinstance(submission, _StopEventProcessing):
                    return
                self._process_submission(submission)
            finally:
                self.venue._event_submission_done()

    def _process_submission(self, submission: EventSubmission) -> None:
        if not submission.result.set_running_or_notify_cancel():
            return
        try:
            self.venue._commit_event(submission)
        except Exception as exc:
            submission.result.set_exception(exc)
        else:
            submission.result.set_result(submission.event)
