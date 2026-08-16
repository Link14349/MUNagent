"""主席与 DM 共用的事件驱动 LLM↔工具轮次。"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, Protocol

from agent.inbox import AgentInbox, Observation, ObservationPriority
from llm import ChatMessage, LLMCancelledError, TextDelta, ToolCallsDelta

if TYPE_CHECKING:
    from llm import LLM, ToolCall, ToolSpec


class SystemAgentStoppedError(RuntimeError):
    """系统 Agent 已收到 Simulator 的协作停止请求。"""


class SystemAgentTurnInterrupted(RuntimeError):
    """系统 Agent 当前轮次被更新的权威状态取代。"""


class ToolExecutor(Protocol):
    @property
    def tool_specs(self) -> list[ToolSpec]: ...

    def execute(self, call: ToolCall) -> str: ...


class EventDrivenSystemAgent:
    """供系统角色复用的局部上下文事件循环。

    子类只负责决定哪些观察要处理，以及如何把一批观察构造成提示。每次
    ``step`` 都从固定系统提示重新开始，模型临时输出不会跨轮无限增长。
    """

    def __init__(
        self,
        *,
        identity: str,
        system_prompt: str,
        tools: ToolExecutor,
        llm: LLM | None,
        stop_event: threading.Event | None,
        interrupt_on_urgent: bool,
    ) -> None:
        self.identity = identity
        self.tools = tools
        self.llm = llm
        self.inbox = AgentInbox()
        self.coalesce_s = 0.3
        self.messages = [ChatMessage(role="system", content=system_prompt)]
        self.__system_message = self.messages[0]
        self.__stop_event = stop_event or threading.Event()
        self.__interrupt_on_urgent = interrupt_on_urgent
        self.__step_lock = threading.Lock()
        self.__turn_state_lock = threading.Lock()
        self.__turn_active = False
        self.__turn_interrupted = threading.Event()

    def initial_prompt(self) -> str | None:
        return None

    def build_prompt(self, observations: list[Observation]) -> str:
        raise NotImplementedError

    def activation_batches(
        self,
        observations: list[Observation],
    ) -> list[list[Observation]]:
        """把 Inbox 合并批次切成 LLM 激活单元。"""
        return [observations]

    def before_step(self, observations: list[Observation]) -> None:
        """子类可在一次观察轮开始前绑定权威任务。"""

    def after_step(
        self,
        observations: list[Observation],
        *,
        completed: bool,
        final_text: str,
    ) -> None:
        """子类可记录处理结果；被中断的轮次 ``completed=False``。"""

    def run(self) -> None:
        if self.llm is None:
            return

        kickoff = self.initial_prompt()
        if kickoff is not None and not self.stop_requested:
            try:
                asyncio.run(self.step(kickoff))
            except SystemAgentTurnInterrupted:
                pass

        while not self.stop_requested:
            batch = self.inbox.take_batch(coalesce_s=self.coalesce_s)
            if batch is None:
                return
            while batch and not self.stop_requested:
                for activation in self.activation_batches(batch):
                    if self.stop_requested:
                        return
                    self.before_step(activation)
                    completed = False
                    final_text = ""
                    try:
                        final_text = asyncio.run(
                            self.step(self.build_prompt(activation))
                        )
                        completed = True
                    except SystemAgentTurnInterrupted:
                        pass
                    finally:
                        self.after_step(
                            activation,
                            completed=completed,
                            final_text=final_text,
                        )
                batch = self.inbox.take_ready()

    def notify(self, observation: Observation) -> bool:
        accepted = self.inbox.put(observation)
        if not accepted:
            return False
        if (
            not self.__interrupt_on_urgent
            or observation.priority != ObservationPriority.URGENT
            or not observation.activates_agent
        ):
            return True
        cancel_llm = False
        with self.__turn_state_lock:
            if self.__turn_active:
                self.__turn_interrupted.set()
                cancel_llm = True
        if cancel_llm and self.llm is not None:
            self.llm.stop()
        return True

    @property
    def stop_requested(self) -> bool:
        return self.__stop_event.is_set()

    def stop(self) -> None:
        self.__stop_event.set()
        self.inbox.close()
        if self.llm is not None:
            self.llm.stop()

    def _require_current_turn(self) -> None:
        if self.stop_requested:
            raise SystemAgentStoppedError(
                f"系统 Agent {self.identity!r} 已收到停止请求"
            )
        if self.__turn_interrupted.is_set():
            raise SystemAgentTurnInterrupted(
                f"系统 Agent {self.identity!r} 当前轮次已被紧急观察中断"
            )

    async def step(self, user_content: str, *, max_tool_rounds: int = 8) -> str:
        if self.llm is None:
            raise RuntimeError(
                f"系统 Agent {self.identity!r} 未绑定 LLM，无法 step"
            )
        content = user_content.strip()
        if not content:
            raise ValueError("user_content 不能为空")
        self._require_current_turn()
        if not self.__step_lock.acquire(blocking=False):
            raise RuntimeError(
                f"系统 Agent {self.identity!r} 同一时间只能执行一个 step"
            )

        with self.__turn_state_lock:
            self.__turn_interrupted.clear()
            self.__turn_active = True

        try:
            self.messages = [
                self.__system_message,
                ChatMessage(role="user", content=content),
            ]
            final_text = ""
            for _ in range(max_tool_rounds):
                self._require_current_turn()
                text_parts: list[str] = []
                tool_calls = None
                try:
                    async for delta in self.llm.stream(
                        self.messages,
                        tools=self.tools.tool_specs,
                        tool_choice="auto",
                    ):
                        self._require_current_turn()
                        if isinstance(delta, TextDelta):
                            text_parts.append(delta.text)
                        elif isinstance(delta, ToolCallsDelta):
                            tool_calls = delta.calls
                except LLMCancelledError as exc:
                    if self.stop_requested:
                        raise SystemAgentStoppedError(
                            f"系统 Agent {self.identity!r} 的 LLM 已随模拟停止"
                        ) from exc
                    if self.__turn_interrupted.is_set():
                        raise SystemAgentTurnInterrupted(
                            f"系统 Agent {self.identity!r} 的 LLM 已因紧急观察取消"
                        ) from exc
                    raise

                final_text = "".join(text_parts)
                self._require_current_turn()
                if not tool_calls:
                    if final_text:
                        self.messages.append(
                            ChatMessage(role="assistant", content=final_text)
                        )
                    break

                self.messages.append(
                    ChatMessage(
                        role="assistant",
                        content=final_text,
                        tool_calls=list(tool_calls),
                    )
                )
                for call in tool_calls:
                    self._require_current_turn()
                    self.messages.append(
                        ChatMessage(
                            role="tool",
                            content=self.tools.execute(call),
                            tool_call_id=call.id,
                            name=call.name,
                        )
                    )
            return final_text
        finally:
            with self.__turn_state_lock:
                self.__turn_active = False
            self.__step_lock.release()
