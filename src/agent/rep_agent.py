"""单个代表的 Agent:维护对话记录,并在每轮 step 中执行 LLM + 工具循环."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from agent.rep_agent_tools import RepresentativeToolExecutor
from agent.rep_prompt import build_representative_system_prompt
from llm import ChatMessage, LLMCancelledError, TextDelta, ToolCallsDelta
from scenario.representative import Representative

if TYPE_CHECKING:
    from llm import LLM


class AgentStoppedError(RuntimeError):
    """Simulator 已请求 Agent 协作停止当前工作."""


class RepresentativeAgent:
    """单个代表的 Agent;由 ``Simulator`` 在独立线程中调用 ``run``.

    对话上下文为 ``messages: list[ChatMessage]``.对外入口:
    - ``step(user_content)``:追加一条 user 消息,然后循环调用 LLM / 执行工具,
      直到本轮不再产生 tool_calls(或达到 ``max_tool_rounds``);
    - ``run()``:仿真器线程入口,当前仍为空实现.
    """

    rep: Representative
    tools: RepresentativeToolExecutor
    llm: LLM | None
    messages: list[ChatMessage]

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
        self.messages = [
            ChatMessage(
                role="system",
                content=build_representative_system_prompt(rep),
            )
        ]

    def run(self) -> None:
        """代表 Agent 主循环(仿真器入口;调度逻辑由后续里程碑填充)."""
        return

    @property
    def stop_requested(self) -> bool:
        return self.__stop_event.is_set()

    def wait_until_stopped(self, timeout: float | None = None) -> bool:
        """供主循环阻塞等待全局停止信号."""
        return self.__stop_event.wait(timeout)

    def stop(self) -> None:
        """请求 Agent 协作退出，并取消正在进行的 LLM 流."""
        self.__stop_event.set()
        if self.llm is not None:
            self.llm.stop()

    def _require_running(self) -> None:
        if self.stop_requested:
            raise AgentStoppedError(f"代表 {self.rep.id} 的 Agent 已收到停止请求")

    async def step(
        self,
        user_content: str,
        *,
        max_tool_rounds: int = 8,
    ) -> str:
        """处理一条 user 输入,跑完本轮 LLM↔工具循环,返回最后一轮正文."""
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

        try:
            self.messages.append(ChatMessage(role="user", content=content))
            final_text = ""

            for _ in range(max_tool_rounds):
                self._require_running()
                text_parts: list[str] = []
                tool_calls = None
                try:
                    async for delta in self.llm.stream(
                        self.messages,
                        tools=self.tools.tool_specs,
                        tool_choice="auto",
                    ):
                        self._require_running()
                        if isinstance(delta, TextDelta):
                            text_parts.append(delta.text)
                        elif isinstance(delta, ToolCallsDelta):
                            tool_calls = delta.calls
                except LLMCancelledError as exc:
                    if self.stop_requested:
                        raise AgentStoppedError(
                            f"代表 {self.rep.id} 的 LLM 已随模拟停止"
                        ) from exc
                    raise

                final_text = "".join(text_parts)
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
                    self._require_running()
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
            self.__step_lock.release()
