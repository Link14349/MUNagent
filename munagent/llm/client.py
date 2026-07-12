"""OpenAI 兼容异步 LLM 客户端 — provider 档案 + 角色路由."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from munagent.config.models import AppConfig
from munagent.llm.stream import ChunkParser, StreamDelta, ToolCall
from munagent.llm.usage import UsageRecord, UsageSink
from munagent.security.sanitize import sanitize_exception, sanitize_text

MessageRole = Literal["system", "user", "assistant", "tool"]


class ChatMessage(BaseModel):
    role: MessageRole
    content: str
    tool_calls: list[ToolCall] | None = None  # assistant 回喂 function calling 用
    tool_call_id: str | None = None  # role=tool 时对应 ToolCall.id

    def to_payload(self) -> dict[str, Any]:
        """转 API 消息体; 不带值为 None 的可选字段, reasoning_content 永不回喂."""
        msg: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": c.arguments},
                }
                for c in self.tool_calls
            ]
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        return msg


class LLMClient:
    """统一 chat 入口; Agent 不直接碰 httpx."""

    def __init__(
        self,
        config: AppConfig,
        *,
        usage_sink: UsageSink | None = None,
        timeout_s: float = 120.0,
        stream_read_timeout_s: float = 60.0,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._usage_sink = usage_sink
        self._timeout_s = timeout_s
        # 流式下整体时限没有意义(长回复可以合法地跑很多分钟),
        # 用"相邻增量间隔"判定断流: httpx 的 read 超时正是逐次读之间的时限.
        self._stream_read_timeout_s = stream_read_timeout_s
        self._max_retries = max_retries
        self._transport = transport

    def resolve_route(self, role: str) -> tuple[str, str, str]:
        """role → (provider_name, base_url, model)."""
        role_cfg = self._config.roles.get(role)
        if role_cfg is None:
            raise KeyError(f"未知角色路由: {role}")
        provider = self._config.providers.get(role_cfg.provider)
        if provider is None:
            raise KeyError(f"角色 {role} 引用的 provider 不存在: {role_cfg.provider}")
        return role_cfg.provider, provider.base_url, role_cfg.model

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        url = base_url.rstrip("/")
        if not url.endswith("/v1"):
            url = f"{url}/v1"
        return url

    @staticmethod
    def _extract_assistant_text(message: dict[str, Any]) -> str:
        """解析 assistant 正文; thinking 模式下小 max_tokens 可能只有 reasoning_content."""
        content = message.get("content")
        if content is not None and str(content).strip():
            return str(content).strip()
        reasoning = message.get("reasoning_content")
        if reasoning is not None and str(reasoning).strip():
            return str(reasoning).strip()
        return ""

    async def chat(
        self,
        role: str,
        messages: list[ChatMessage],
        *,
        max_tokens: int = 4096,
        err_hint: str | None = None,
        thinking_enabled: bool = True,
    ) -> str:
        """调用 chat/completions; 失败时指数退避重试."""
        model, url, headers, payload = self._build_request(
            role, messages, max_tokens=max_tokens, thinking_enabled=thinking_enabled
        )
        if err_hint:
            payload["messages"] = payload["messages"] + [
                {"role": "user", "content": f"上次输出校验失败, 请修正:\n{err_hint}"}
            ]

        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            started = time.perf_counter()
            try:
                async with httpx.AsyncClient(
                    timeout=self._timeout_s, transport=self._transport
                ) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                latency_ms = (time.perf_counter() - started) * 1000
                self._record_usage(role, model, data, thinking_enabled, latency_ms)
                choices = data.get("choices") or []
                if not choices:
                    raise RuntimeError("LLM 响应无 choices")
                message = choices[0].get("message") or {}
                content = self._extract_assistant_text(message)
                if not content:
                    raise RuntimeError("LLM 响应 content 为空")
                return content
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt + 1 >= self._max_retries:
                    break
                await asyncio.sleep(2**attempt)
            except Exception as exc:
                raise RuntimeError(sanitize_text(sanitize_exception(exc))) from exc

        assert last_exc is not None
        raise RuntimeError(sanitize_text(sanitize_exception(last_exc))) from last_exc

    def _build_request(
        self,
        role: str,
        messages: list[ChatMessage],
        *,
        max_tokens: int,
        thinking_enabled: bool,
        tools: list[dict[str, Any]] | None = None,
    ) -> tuple[str, str, dict[str, str], dict[str, Any]]:
        """chat 与 chat_stream 共用的路由/鉴权/payload 组装."""
        _provider, base_url, model = self.resolve_route(role)
        api_key = self._config.providers[self._config.roles[role].provider].api_key
        if not api_key or api_key == "none":
            raise ValueError(f"provider 未配置 api_key, 无法调用 LLM (role={role})")
        payload: dict[str, Any] = {
            "model": model,
            "messages": [m.to_payload() for m in messages],
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
        # DeepSeek V4 部分模型默认开 thinking; 显式 disabled 保证非推理任务拿到 content
        payload["thinking"] = {"type": "enabled" if thinking_enabled else "disabled"}
        url = f"{self._normalize_base_url(base_url)}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        return model, url, headers, payload

    async def chat_stream(
        self,
        role: str,
        messages: list[ChatMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
        thinking_enabled: bool = True,
    ) -> AsyncIterator[StreamDelta]:
        """流式 chat/completions, 产出类型化增量(见 llm/stream.py).

        重试纪律(design/designer/03§7.3): 只允许在首个增量产出之前静默重试;
        一旦开始吐字, 中途断流直接抛错, 由上层决定整步重做——否则前端已渲染的文本会回退.
        """
        model, url, headers, payload = self._build_request(
            role, messages, max_tokens=max_tokens, thinking_enabled=thinking_enabled, tools=tools
        )
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        timeout = httpx.Timeout(
            connect=10.0, read=self._stream_read_timeout_s, write=30.0, pool=10.0
        )

        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            started = time.perf_counter()
            parser = ChunkParser()
            yielded = False
            try:
                async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:
                    async with client.stream("POST", url, json=payload, headers=headers) as resp:
                        resp.raise_for_status()
                        async for line in resp.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            data = line[len("data:") :].strip()
                            if data == "[DONE]":
                                break
                            for delta in parser.feed(json.loads(data)):
                                yielded = True
                                yield delta
                for delta in parser.finish():
                    yielded = True
                    yield delta
                if parser.usage_raw is not None:
                    latency_ms = (time.perf_counter() - started) * 1000
                    self._record_usage(
                        role, model, {"usage": parser.usage_raw}, thinking_enabled, latency_ms
                    )
                return
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.TransportError) as exc:
                if yielded:
                    raise RuntimeError(sanitize_text(sanitize_exception(exc))) from exc
                last_exc = exc
                if attempt + 1 >= self._max_retries:
                    break
                await asyncio.sleep(2**attempt)
            except Exception as exc:
                raise RuntimeError(sanitize_text(sanitize_exception(exc))) from exc

        assert last_exc is not None
        raise RuntimeError(sanitize_text(sanitize_exception(last_exc))) from last_exc

    def _record_usage(
        self,
        role: str,
        model: str,
        data: dict[str, Any],
        thinking: bool,
        latency_ms: float,
    ) -> None:
        if self._usage_sink is None:
            return
        usage = data.get("usage") or {}
        hit = int(usage.get("prompt_cache_hit_tokens") or 0)
        miss = int(usage.get("prompt_cache_miss_tokens") or 0)
        if hit == 0 and miss == 0:
            # 部分兼容端点只有 prompt_tokens
            miss = int(usage.get("prompt_tokens") or 0)
        record = UsageRecord(
            role=role,
            model=model,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            cache_hit_tokens=hit,
            cache_miss_tokens=miss,
            thinking_enabled=thinking,
            latency_ms=latency_ms,
        )
        self._usage_sink(record)


class ChatRequest(BaseModel):
    """测试/文档用请求体摘要."""

    role: str
    messages: list[ChatMessage]
    max_tokens: int = Field(default=4096, ge=1)
    thinking_enabled: bool = True
