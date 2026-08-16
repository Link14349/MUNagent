"""无主持阶段的 Agent 行动冷却与公共对话防回声控制。"""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time

from agent.inbox import Observation, ObservationKind, ObservationPriority
from scenario.venue import SessionPhase


_PUBLIC_EVENT_TYPES = {"message", "chat"}
_PUBLIC_ACTION_TOOLS = {"send_message"}
_EVENT_ACTION_TOOLS = {
    "send_message",
    "pass_note",
    "submit_motion_switch",
    "submit_phase_switch",
    "submit_instruction",
    "submit_resolution",
    "set_current_agenda",
    "add_agenda",
}
_SUBSTANTIVE_ACTION_TOOLS = _EVENT_ACTION_TOOLS - _PUBLIC_ACTION_TOOLS


@dataclass(frozen=True)
class ActivationDecision:
    """一批观察是否触发 LLM，以及触发前还需等待多久。"""

    should_activate: bool
    delay_s: float = 0.0
    guidance: str = ""


class UnchairedActivityController:
    """限制同一公共讨论波次内的重复回应，并合并冷却期事件。"""

    def __init__(self, *, cooldown_s: float = 1.0) -> None:
        if cooldown_s < 0:
            raise ValueError(f"cooldown_s 须为非负数,实际为 {cooldown_s!r}")
        self.cooldown_s = cooldown_s
        self.__next_action_at = 0.0
        self.__public_response_used = False
        self.__lock = threading.RLock()

    def evaluate(
        self,
        phase: SessionPhase | None,
        observations: list[Observation],
    ) -> ActivationDecision:
        """根据阶段、紧急性、公共波次额度和冷却时间决定是否激活。"""
        actionable = [item for item in observations if item.activates_agent]
        if not actionable:
            return ActivationDecision(False)
        if phase != SessionPhase.UNCHAIRED_CORE:
            with self.__lock:
                self.__public_response_used = False
            return ActivationDecision(True)

        urgent = any(
            item.priority == ObservationPriority.URGENT for item in actionable
        )
        public_only = all(_is_public_observation(item) for item in actionable)
        with self.__lock:
            if not public_only:
                self.__public_response_used = False
            if public_only and self.__public_response_used and not urgent:
                return ActivationDecision(
                    False,
                    guidance=(
                        "同一公共讨论波次已经回应过，等待实质性新事件。"
                    ),
                )
            delay = 0.0 if urgent else max(
                0.0,
                self.__next_action_at - time.monotonic(),
            )
        return ActivationDecision(
            True,
            delay_s=delay,
            guidance=(
                "无主持阶段：本轮最多提交一次公开发言；若没有新增条件、"
                "承诺、问题或方案，应保持沉默。"
            ),
        )

    def record_tools(
        self,
        phase: SessionPhase | None,
        successful_tools: list[str],
    ) -> None:
        """工具成功后推进冷却并更新公共讨论波次额度。"""
        if phase != SessionPhase.UNCHAIRED_CORE:
            return
        with self.__lock:
            for tool_name in successful_tools:
                if tool_name in _SUBSTANTIVE_ACTION_TOOLS:
                    self.__public_response_used = False
                if tool_name in _PUBLIC_ACTION_TOOLS:
                    self.__public_response_used = True
                if tool_name in _EVENT_ACTION_TOOLS:
                    self.__next_action_at = max(
                        self.__next_action_at,
                        time.monotonic() + self.cooldown_s,
                    )


def _is_public_observation(observation: Observation) -> bool:
    return (
        observation.kind == ObservationKind.EVENT_CREATED
        and observation.event.event_type in _PUBLIC_EVENT_TYPES
    )
