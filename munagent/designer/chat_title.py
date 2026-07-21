"""首轮结束后自动概括对话标题 — 见 design/designer/01-data-chats.md §2.1."""

from __future__ import annotations

import re
from typing import Any

from munagent.config.models import AppConfig
from munagent.designer.scenario import chats as chat_svc
from munagent.designer.scenario.chats import ChatMeta
from munagent.llm import ChatMessage, LLMClient

_TITLE_MAX_LEN = 32
_TRUNCATE_FALLBACK_LEN = 30
_LLM_ROLE = "designer"
_LLM_MAX_TOKENS = 64

_TITLE_STRIP_RE = re.compile(r'^[\s「『"\'《【]+|[\s」』"\'》】]+$')


def _extract_turn_context(records: list[dict[str, Any]], *, turn: int) -> tuple[str | None, str | None]:
    user_text: str | None = None
    agent_parts: list[str] = []
    for row in records:
        if row.get("type") == "meta":
            continue
        if row.get("turn") != turn:
            continue
        if row.get("type") == "user_message" and user_text is None:
            text = row.get("text")
            user_text = text if isinstance(text, str) and text.strip() else None
        elif row.get("type") == "agent_text":
            text = row.get("text")
            if isinstance(text, str) and text.strip():
                agent_parts.append(text.strip())
    agent_text = "\n".join(agent_parts) if agent_parts else None
    return user_text, agent_text


def _truncate_fallback(user_text: str) -> str:
    text = re.sub(r"\s+", " ", user_text.strip())
    if len(text) <= _TRUNCATE_FALLBACK_LEN:
        return text
    return text[:_TRUNCATE_FALLBACK_LEN].rstrip() + "…"


def _sanitize_llm_title(raw: str) -> str | None:
    text = _TITLE_STRIP_RE.sub("", raw.strip())
    text = re.sub(r"\s+", " ", text)
    if not text:
        return None
    if len(text) > _TITLE_MAX_LEN:
        text = text[:_TITLE_MAX_LEN].rstrip()
    if chat_svc.is_default_chat_title(text):
        return None
    return text


def _build_title_prompt(user_text: str, agent_text: str | None) -> str:
    parts = [f"用户：{user_text.strip()}"]
    if agent_text:
        snippet = agent_text.strip()
        if len(snippet) > 800:
            snippet = snippet[:800].rstrip() + "…"
        parts.append(f"助手：{snippet}")
    body = "\n\n".join(parts)
    return (
        "根据以下对话首轮内容，用 8～16 个中文字概括主题，作为侧边栏对话标题。\n"
        "只输出标题本身，不要引号、标点或解释。\n\n"
        f"{body}"
    )


async def _generate_title_llm(
    user_text: str,
    agent_text: str | None,
    config: AppConfig,
    *,
    llm: LLMClient | None = None,
) -> str | None:
    client = llm or LLMClient(config)
    prompt = _build_title_prompt(user_text, agent_text)
    raw = await client.chat(
        _LLM_ROLE,
        [
            ChatMessage(
                role="system",
                content="你是标题生成器，只输出简短中文标题。",
            ),
            ChatMessage(role="user", content=prompt),
        ],
        max_tokens=_LLM_MAX_TOKENS,
        thinking_enabled=False,
    )
    return _sanitize_llm_title(raw)


async def maybe_autotitle_after_first_turn(
    scenario_id: str,
    chat_id: str,
    config: AppConfig,
    *,
    llm: LLMClient | None = None,
) -> ChatMeta | None:
    """首轮任务结束后：默认标题的对话尝试 LLM 概括，失败则截断用户首条消息."""
    chats = chat_svc.list_chats(scenario_id)
    chat = next((c for c in chats if c.id == chat_id), None)
    if chat is None or not chat_svc.is_default_chat_title(chat.title):
        return None

    records = chat_svc.get_chat_records(scenario_id, chat_id)
    user_text, agent_text = _extract_turn_context(records, turn=1)
    if not user_text:
        return None

    title: str | None = None
    try:
        title = await _generate_title_llm(user_text, agent_text, config, llm=llm)
    except Exception:
        title = None
    if not title:
        title = _truncate_fallback(user_text)
    if not title or chat_svc.is_default_chat_title(title):
        return None
    return chat_svc.rename_chat(scenario_id, chat_id, title)
