"""OpenAI 兼容异步 LLM 客户端."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from munagent.config.models import MunagentConfig
from munagent.llm.thinking import resolve_thinking
from munagent.llm.usage import UsageRecord
from munagent.security.sanitize import sanitize_text


class LLMError(RuntimeError):
    """LLM 调用失败(已脱敏)."""


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class ChatRequest:
    role: str
    task: str
    messages: list[ChatMessage]
    phase: str | None = None
    scope: str | None = None
    max_tokens: int = 1024
    temperature: float = 0.7


class LLMClient:
    """Provider 档案 + 角色路由 + thinking 开关 + 重试."""

    def __init__(
        self,
        config: MunagentConfig,
        *,
        timeout_s: float = 60.0,
        max_retries: int = 3,
        usage_sink: Callable[[UsageRecord], None] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._timeout = timeout_s
        self._max_retries = max_retries
        self._usage_sink = usage_sink
        self._transport = transport

    async def chat(self, request: ChatRequest) -> str:
        provider, model = self._config.resolve_role(request.role)
        if not provider.api_key or provider.api_key == "none":
            raise LLMError("API key 未配置, 请设置 ~/.munagent/config.yaml 或 MUNAGENT_API_KEY")

        thinking_enabled = resolve_thinking(
            request.role,
            request.task,
            phase=request.phase,
            scope=request.scope,
        )
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": False,
        }
        if thinking_enabled:
            body["thinking"] = {"type": "enabled"}

        url = provider.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        }

        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            for attempt in range(self._max_retries):
                try:
                    response = await client.post(url, json=body, headers=headers)
                    if response.status_code >= 500:
                        raise httpx.HTTPStatusError(
                            "server error",
                            request=response.request,
                            response=response,
                        )
                    if response.status_code >= 400:
                        detail = sanitize_text(response.text)
                        raise LLMError(
                            f"LLM 请求失败 HTTP {response.status_code}: {detail[:500]}"
                        )
                    payload = response.json()
                    content = payload["choices"][0]["message"]["content"]
                    usage = payload.get("usage", {})
                    record = UsageRecord.from_response(
                        role=request.role,
                        task=request.task,
                        model=model,
                        provider=self._config.roles[request.role].provider,
                        usage=usage,
                        thinking_enabled=thinking_enabled,
                    )
                    if self._usage_sink:
                        self._usage_sink(record)
                    return content
                except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                    last_error = exc
                    if attempt + 1 < self._max_retries:
                        await asyncio.sleep(2**attempt)
                    continue
                except httpx.HTTPError as exc:
                    raise LLMError(sanitize_text(str(exc))) from exc

        raise LLMError(sanitize_text(str(last_error or "LLM 调用失败")))

    async def test_provider(self, provider_name: str | None = None) -> UsageRecord:
        """最小补全连通性测试(约 1 token)."""
        name = provider_name or self._config.default_provider_name()
        if name not in self._config.providers:
            raise LLMError(f"provider 不存在: {name}")
        provider = self._config.providers[name]
        if not provider.api_key or provider.api_key == "none":
            raise LLMError(f"provider {name} 的 API key 未配置")

        role_for_test = next(
            (r for r, cfg in self._config.roles.items() if cfg.provider == name),
            "delegate",
        )
        _, model = self._config.resolve_role(role_for_test)
        body = {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "stream": False,
        }
        url = provider.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            try:
                response = await client.post(url, json=body, headers=headers)
            except httpx.HTTPError as exc:
                raise LLMError(sanitize_text(str(exc))) from exc
            if response.status_code >= 400:
                raise LLMError(
                    f"连接测试失败 HTTP {response.status_code}: "
                    f"{sanitize_text(response.text)[:500]}"
                )
            payload = response.json()
            usage = payload.get("usage", {})
            record = UsageRecord.from_response(
                role=role_for_test,
                task="config_test",
                model=model,
                provider=name,
                usage=usage,
                thinking_enabled=False,
            )
            if self._usage_sink:
                self._usage_sink(record)
            return record
