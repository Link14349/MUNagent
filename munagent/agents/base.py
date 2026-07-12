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
    docs: str = ""  # 当前有效文件档案(该视角可见的指令/决议/公报原文, 仅当前版本)
    l3_events: str = ""  # 追加事件段
    l4_task: str = ""  # 任务段

    def to_messages(self) -> list[ChatMessage]:
        """组装为 system + user 两条消息."""
        system = f"{self.g_global}\n{self.l1_seat}"
        docs_part = (
            f"<当前有效文件(原文, 仅当前版本, 历史版本已隐藏)>\n{self.docs}\n</当前有效文件>\n"
            if self.docs
            else ""
        )
        user = (
            f"<此前局势(书记摘要)>\n{self.l2_summary}\n</此前局势>\n"
            f"{docs_part}"
            f"<最近发生(原文)>\n{self.l3_events}\n</最近发生>\n"
            f"<当前任务>\n{self.l4_task}\n</当前任务>"
        )
        return [ChatMessage(role="system", content=system), ChatMessage(role="user", content=user)]


def normalize_json_delimiter_quotes(json_str: str) -> str:
    """将模型误写在 JSON 结构边界上的弯引号/全角引号归一为 ASCII 双引号.

    只处理 delimiter 位置(键名两侧、值首尾), 不改动字符串内部的引述用引号.
    """
    s = json_str.strip()
    # 键名两侧: { "text": 或 , "action":
    s = re.sub(
        r'([\{,]\s*)[\u201c\u201d\uff02"]([a-zA-Z_][a-zA-Z0-9_]*)[\u201c\u201d\uff02"](\s*:)',
        r'\1"\2"\3',
        s,
    )
    # 字符串值起始: 冒号后第一个引号
    s = re.sub(
        r'(:\s*)[\u201c\uff02"](?=\S)',
        r'\1"',
        s,
    )
    # 字符串值结束: 弯引号后紧跟 , 或 }
    s = re.sub(
        r'[\u201d\uff02"](\s*[\},])',
        r'"\1',
        s,
    )
    # 整条对象末尾: ...内容"} 中错误的闭合引号
    s = re.sub(
        r'[\u201d\uff02"](\s*\})\s*$',
        r'"\1',
        s,
    )
    return s


def parse_json_block(raw: str, schema_model: type[BaseModel] | None = None) -> tuple[Any | None, str | None]:
    """从 LLM 输出中提取 ```json ... ``` 块并按 schema 校验.

    返回 (parsed_action | None, error_message | None).
    """
    # 提取 ```json ... ``` 块(允许单行块与围栏前后无换行)
    match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
    if match:
        json_str = match.group(1)
    else:
        # 没有代码块, 尝试整段当 JSON
        json_str = raw.strip()

    json_str = normalize_json_delimiter_quotes(json_str)

    try:
        # strict=False: 容忍字符串内的裸控制字符(模型写长发言时常忘转义换行)
        data = json.loads(json_str, strict=False)
    except json.JSONDecodeError as e:
        return None, (
            f"JSON 解析失败: {e}. 常见原因: 字符串内的换行要写成\\n; "
            f'JSON 的引号必须是半角双引号("), 不能用弯引号""作为闭合. 原文片段: {json_str[:200]}'
        )

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

    async def act(
        self,
        task: TaskSpec,
        context: AgentContext,
        *,
        schema_model: type[BaseModel] | None = None,
    ) -> Any:
        """执行一次 Agent 循环: 组装 prompt → 调 LLM → 解析 → 修复重试 → fallback.

        schema_model 参数临时覆盖 self._schema_model, 不修改实例属性.
        """
        effective_schema = schema_model or self._schema_model
        messages = context.to_messages()
        last_err: str | None = None
        last_raw: str = ""

        for attempt in range(self._max_attempts):
            prompt_messages = list(messages)
            if last_err:
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
            last_raw = raw
            parsed, err = parse_json_block(raw, effective_schema)
            if parsed is not None:
                return parsed
            last_err = err

        return self.fallback(task, schema_model=effective_schema, last_err=last_err, last_raw=last_raw)

    def fallback(
        self,
        task: TaskSpec,
        *,
        schema_model: type[BaseModel] | None = None,
        last_err: str | None = None,
        last_raw: str = "",
    ) -> Any:
        """兜底, 按角色定义. 见 05§1 fallback 表."""
        import sys

        effective_schema = schema_model or self._schema_model
        schema_info = ""
        if effective_schema is not None:
            schema_info = str(effective_schema.model_json_schema())
        print(
            f"[警告] Agent fallback: role={task.role} task={task.task}\n"
            f"  期望schema: {schema_info}\n"
            f"  错误: {last_err}\n"
            f"  LLM 原始输出:\n{last_raw}",
            file=sys.stderr,
        )
        if effective_schema is not None:
            # 尝试用 schema 的默认值构造一个合法对象
            try:
                return effective_schema.model_validate({"action": "pass"})
            except Exception:
                pass
            # 如果 schema 没有 action 字段, 尝试空构造
            try:
                return effective_schema.model_validate({})
            except Exception:
                pass
        return {"action": "pass"}

    def build_context(
        self, task: TaskSpec, *, g: str, l1: str, l2: str, l3: str, l4: str, docs: str = ""
    ) -> AgentContext:
        """构造上下文(五段 + 可选文件档案区)."""
        return AgentContext(
            g_global=g,
            l1_seat=l1,
            l2_summary=l2,
            docs=docs,
            l3_events=l3,
            l4_task=l4,
        )
