"""单个代表的 Agent:维护对话记录,并在每轮 step 中执行 LLM + 工具循环."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent.rep_agent_tools import RepresentativeToolExecutor
from agent.rep_prompt import build_representative_system_prompt
from llm import ChatMessage, TextDelta, ToolCallsDelta
from scenario.representative import Representative

if TYPE_CHECKING:
    from llm import LLM


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

    def __init__(self, rep: Representative, *, llm: LLM | None = None) -> None:
        self.rep = rep
        self.tools = RepresentativeToolExecutor(rep)
        self.llm = llm
        self.messages = [
            ChatMessage(
                role="system",
                content=build_representative_system_prompt(rep),
            )
        ]

    def run(self) -> None:
        """代表 Agent 主循环(仿真器入口;调度逻辑由后续里程碑填充)."""
        return

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

        self.messages.append(ChatMessage(role="user", content=content))
        final_text = ""

        for _ in range(max_tool_rounds):
            text_parts: list[str] = []
            tool_calls = None
            async for delta in self.llm.stream(
                self.messages,
                tools=self.tools.tool_specs,
                tool_choice="auto",
            ):
                if isinstance(delta, TextDelta):
                    text_parts.append(delta.text)
                elif isinstance(delta, ToolCallsDelta):
                    tool_calls = delta.calls

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
                self.messages.append(
                    ChatMessage(
                        role="tool",
                        content=self.tools.execute(call),
                        tool_call_id=call.id,
                        name=call.name,
                    )
                )

        return final_text
