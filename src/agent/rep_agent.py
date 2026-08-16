"""单个代表的 Agent:按观察激活,并在单轮内执行 LLM + 工具循环."""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

from agent.inbox import AgentInbox, Observation, ObservationPriority
from agent.rep_context import build_activation_prompt
from agent.rep_agent_tools import RepresentativeToolExecutor
from agent.rep_prompt import build_representative_system_prompt
from llm import ChatMessage, LLMCancelledError, TextDelta, ToolCallsDelta
from scenario.representative import Representative

if TYPE_CHECKING:
    from llm import LLM


class AgentStoppedError(RuntimeError):
    """Simulator 已请求 Agent 协作停止当前工作."""


class AgentTurnInterrupted(RuntimeError):
    """当前轮次所依据的会场状态已失效,应使用新观察重新开始."""


class RepresentativeAgent:
    """单个代表的 Agent;由 ``Simulator`` 在独立线程中调用 ``run``.

    ``messages`` 只保存最近一次 step 的局部上下文,不会跨激活无限追加.
    对外入口:
    - ``notify(observation)``:由 Simulator 向线程安全 Inbox 投递会场变化;
    - ``step(user_content)``:以新的局部上下文循环调用 LLM / 执行工具;
    - ``run()``:等待并合并观察,再触发一轮 ``step``.
    """

    rep: Representative
    tools: RepresentativeToolExecutor
    llm: LLM | None
    messages: list[ChatMessage]
    inbox: AgentInbox

    def __init__(
        self,
        rep: Representative,
        *,
        llm: LLM | None = None,
        stop_event: threading.Event | None = None,
    ) -> None:
        self.rep = rep
        self.tools = RepresentativeToolExecutor(rep)
        self.llm = llm
        self.__stop_event = stop_event or threading.Event()
        self.__step_lock = threading.Lock()
        self.__turn_state_lock = threading.Lock()
        self.__turn_active = False
        self.__turn_interrupted = threading.Event()
        self.inbox = AgentInbox()
        self.coalesce_s = 0.3
        self.__system_message = ChatMessage(
            role="system",
            content=build_representative_system_prompt(rep),
        )
        self.messages = [self.__system_message]

    def run(self) -> None:
        """等待新观察；普通观察固定窗口合并,紧急观察立即开始新轮次."""
        if self.llm is None:
            return

        while not self.stop_requested:
            batch = self.inbox.take_batch(coalesce_s=self.coalesce_s)
            if batch is None:
                return

            while batch and not self.stop_requested:
                if any(item.activates_agent for item in batch):
                    prompt = build_activation_prompt(self.rep, batch)
                    try:
                        asyncio.run(self.step(prompt))
                    except AgentTurnInterrupted:
                        pass
                batch = self.inbox.take_ready()

    def notify(self, observation: Observation) -> bool:
        """投递观察；紧急且可激活的观察会取消正在进行的 LLM 轮次."""
        accepted = self.inbox.put(observation)
        if not accepted:
            return False
        if (
            observation.priority != ObservationPriority.URGENT
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

    def wait_until_stopped(self, timeout: float | None = None) -> bool:
        """供主循环阻塞等待全局停止信号."""
        return self.__stop_event.wait(timeout)

    def stop(self) -> None:
        """请求 Agent 协作退出，并取消正在进行的 LLM 流."""
        self.__stop_event.set()
        self.inbox.close()
        if self.llm is not None:
            self.llm.stop()

    def _require_running(self) -> None:
        if self.stop_requested:
            raise AgentStoppedError(f"代表 {self.rep.id} 的 Agent 已收到停止请求")

    def _require_current_turn(self) -> None:
        self._require_running()
        if self.__turn_interrupted.is_set():
            raise AgentTurnInterrupted(
                f"代表 {self.rep.id} 的当前轮次已被紧急观察中断"
            )

    async def step(
        self,
        user_content: str,
        *,
        max_tool_rounds: int = 8,
    ) -> str:
        """用独立局部上下文处理输入,跑完本轮 LLM↔工具循环."""
        if self.llm is None:
            raise RuntimeError(
                f"代表 {self.rep.id} 的 Agent 未绑定 LLM,无法 step"
            )
        content = user_content.strip()
        if not content:
            raise ValueError("user_content 不能为空")
        self._require_running()
        if not self.__step_lock.acquire(blocking=False):
            raise RuntimeError(
                f"代表 {self.rep.id} 的 Agent 同一时间只能执行一个 step"
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
                        raise AgentStoppedError(
                            f"代表 {self.rep.id} 的 LLM 已随模拟停止"
                        ) from exc
                    if self.__turn_interrupted.is_set():
                        raise AgentTurnInterrupted(
                            f"代表 {self.rep.id} 的 LLM 已因紧急观察取消"
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
