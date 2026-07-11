"""Agent 基类: 上下文五段组装 + JSON 解析 + 修复重试 + fallback. 见 05§1-2."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from munagent.llm.client import ChatMessage, ChatRequest, LLMClient


@dataclass
class TaskSpec:
    """引擎交给 Agent 的任务说明, 对应 L4 任务段."""

    role: str  # delegate | chair | dm | recorder
    task: str  # turn | next_speaker | phase_decision | adjudicate ...
    phase: str | None = None
    scope: str | None = None
    instructions: str = ""  # 本次具体指令(阶段说明、要做的事)
    output_schema: str = ""  # JSON schema 文本, 嵌入 prompt
    venue_id: str | None = None
    seat_id: str | None = None  # 代表 Agent 扮演的席位


@dataclass
class AgentContext:
    """五段上下文. 见 05§2."""

    g_global: str = ""  # 全局共享段
    l1_seat: str = ""  # 席位固定段
    l2_summary: str = ""  # 纪元摘要段(P1 stub)
    l3_events: str = ""  # 追加事件段
    l4_task: str = ""  # 任务段

    def to_messages(self) -> list[ChatMessage]:
        """组装为 system + user 两条消息."""
        system = f"{self.g_global}\n{self.l1_seat}"
        user = (
            f"<此前局势(书记摘要)>\n{self.l2_summary}\n</此前局势>\n"
            f"<最近发生(原文)>\n{self.l3_events}\n</最近发生>\n"
            f"<当前任务>\n{self.l4_task}\n</当前任务>"
        )
        return [ChatMessage(role="system", content=system), ChatMessage(role="user", content=user)]


def parse_json_block(raw: str, schema_model: type[BaseModel] | None = None) -> tuple[Any | None, str | None]:
    """从 LLM 输出中提取 ```json ... ``` 块并按 schema 校验.

    返回 (parsed_action | None, error_message | None).
    """
    # 提取 ```json ... ``` 块
    match = re.search(r"```json\s*\n(.*?)\n```", raw, re.DOTALL)
    if match:
        json_str = match.group(1)
    else:
        # 没有代码块, 尝试整段当 JSON
        json_str = raw.strip()

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        return None, f"JSON 解析失败: {e}. 原文片段: {json_str[:200]}"

    if schema_model is not None:
        try:
            validated = schema_model.model_validate(data)
            return validated, None
        except ValidationError as e:
            return None, f"schema 校验失败: {e}"

    return data, None


class BaseAgent:
    """所有 Agent 共享的执行骨架. 见 05§1."""

    role: str = ""

    def __init__(
        self,
        llm: LLMClient,
        *,
        schema_model: type[BaseModel] | None = None,
        max_attempts: int = 3,
        max_tokens: int = 1024,
    ) -> None:
        self._llm = llm
        self._schema_model = schema_model
        self._max_attempts = max_attempts
        self._max_tokens = max_tokens

    async def act(self, task: TaskSpec, context: AgentContext) -> Any:
        """执行一次 Agent 循环: 组装 prompt → 调 LLM → 解析 → 修复重试 → fallback."""
        messages = context.to_messages()
        last_err: str | None = None

        for attempt in range(self._max_attempts):
            prompt_messages = list(messages)
            if last_err:
                # 修复提示回填
                prompt_messages.append(
                    ChatMessage(
                        role="user",
                        content=f"上次输出有误: {last_err}\n请修正后重新输出.",
                    )
                )

            request = ChatRequest(
                role=task.role,
                task=task.task,
                messages=prompt_messages,
                phase=task.phase,
                scope=task.scope,
                max_tokens=self._max_tokens,
            )
            raw = await self._llm.chat(request)
            parsed, err = parse_json_block(raw, self._schema_model)
            if parsed is not None:
                return parsed
            last_err = err

        return self.fallback(task)

    def fallback(self, task: TaskSpec) -> Any:
        """兜底, 按角色定义. 见 05§1 fallback 表."""
        # 默认: 返回 pass
        if self._schema_model is not None:
            try:
                return self._schema_model.model_validate({"action": "pass"})
            except Exception:
                pass
        return {"action": "pass"}

    def build_context(self, task: TaskSpec, *, g: str, l1: str, l2: str, l3: str, l4: str) -> AgentContext:
        """构造五段上下文."""
        return AgentContext(
            g_global=g,
            l1_seat=l1,
            l2_summary=l2,
            l3_events=l3,
            l4_task=l4,
        )
