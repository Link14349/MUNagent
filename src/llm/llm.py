"""OpenAI 兼容异步 LLM 客户端 - 流式输出与随时停止."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx

from config.load import load_config
from config.models import AppConfig
from llm.stream import ChunkParser
from llm.types import (
    ChatMessage,
    StreamDelta,
    TextDelta,
    ThinkDelta,
    ToolChoice,
    ToolSpec,
    UsageDelta,
)


class LLMCancelledError(Exception):
    """用户主动停止流式输出."""


class LLM:
    """发送 chat/completions 请求, 默认流式返回增量."""

    def __init__(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        thinking: bool = True,
        config: AppConfig | None = None,
        config_path: Path | None = None,
        timeout_s: float = 120.0,
        stream_read_timeout_s: float = 60.0,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config or load_config(path=config_path)
        self.provider = provider or self._config.default_provider
        self.model = model or self._config.default_model
        self.thinking = thinking
        self._timeout_s = timeout_s
        self._stream_read_timeout_s = stream_read_timeout_s
        self._max_retries = max_retries
        self._transport = transport
        self._stop_event = threading.Event()

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        url = base_url.rstrip("/")
        if not url.endswith("/v1"):
            url = f"{url}/v1"
        return url

    def _resolve_provider(self) -> tuple[str, str]:
        provider_cfg = self._config.providers.get(self.provider)
        if provider_cfg is None:
            known = ", ".join(sorted(self._config.providers)) or "(无)"
            raise KeyError(f"未知 provider: {self.provider!r}, 可选: {known}")
        if not provider_cfg.api_key or provider_cfg.api_key == "none":
            raise ValueError(
                f"provider {self.provider!r} 未配置 api_key, "
                f"请在 ~/.munagent/config.yaml 中设置 providers.{self.provider}.api_key"
            )
        return provider_cfg.base_url, provider_cfg.api_key

    def _build_payload(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int,
        tools: list[ToolSpec] | None = None,
        tool_choice: ToolChoice | None = None,
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        base_url, api_key = self._resolve_provider()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_payload() for m in messages],
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
            "thinking": {"type": "enabled" if self.thinking else "disabled"},
        }
        if tools:
            payload["tools"] = [tool.to_payload() for tool in tools]
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice
        elif tool_choice is not None:
            raise ValueError("传入 tool_choice 时必须同时提供 tools")
        url = f"{self._normalize_base_url(base_url)}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        return url, headers, payload

    def stop(self) -> None:
        """停止当前流式请求; 可在另一线程/协程中调用."""
        self._stop_event.set()

    async def stream(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int = 4096,
        tools: list[ToolSpec] | None = None,
        tool_choice: ToolChoice | None = None,
        on_delta: Callable[[StreamDelta], None] | None = None,
    ) -> AsyncIterator[StreamDelta]:
        """流式 chat/completions; 首个增量产出前可静默重试.

        ``tools`` 为 OpenAI function tools 列表;流中会产出 ``ToolCallDelta`` 片段,
        结束时若有完整调用再产出 ``ToolCallsDelta``.
        """
        url, headers, payload = self._build_payload(
            messages,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
        )
        timeout = httpx.Timeout(
            connect=10.0,
            read=self._stream_read_timeout_s,
            write=30.0,
            pool=10.0,
        )

        self._stop_event.clear()
        last_exc: Exception | None = None

        for attempt in range(self._max_retries):
            parser = ChunkParser()
            yielded = False
            try:
                async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:
                    async with client.stream("POST", url, json=payload, headers=headers) as resp:
                        resp.raise_for_status()
                        async for line in resp.aiter_lines():
                            if self._stop_event.is_set():
                                raise LLMCancelledError("流式输出已停止")
                            if not line.startswith("data:"):
                                continue
                            data = line[len("data:") :].strip()
                            if data == "[DONE]":
                                break
                            for delta in parser.feed(json.loads(data)):
                                yielded = True
                                if on_delta is not None:
                                    on_delta(delta)
                                yield delta
                for delta in parser.finish():
                    yielded = True
                    if on_delta is not None:
                        on_delta(delta)
                    yield delta
                if self._stop_event.is_set():
                    raise LLMCancelledError("流式输出已停止")
                return
            except LLMCancelledError:
                raise
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.TransportError) as exc:
                if yielded:
                    raise RuntimeError(_format_http_error(exc)) from exc
                last_exc = exc
                if attempt + 1 >= self._max_retries:
                    break
                await asyncio.sleep(2**attempt)

        assert last_exc is not None
        raise RuntimeError(_format_http_error(last_exc)) from last_exc

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int = 4096,
        tools: list[ToolSpec] | None = None,
        tool_choice: ToolChoice | None = None,
        on_delta: Callable[[StreamDelta], None] | None = None,
    ) -> str:
        """消费 stream 并拼接正文; thinking / tool_call 增量不计入返回值."""
        parts: list[str] = []
        async for delta in self.stream(
            messages,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
            on_delta=on_delta,
        ):
            if isinstance(delta, TextDelta):
                parts.append(delta.text)
        return "".join(parts)


def _format_http_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        body = exc.response.text[:500].strip()
        if body:
            return f"{exc}; response: {body}"
    return str(exc)


def _default_printer(delta: StreamDelta) -> None:
    """终端实时刷出: thinking 用灰色前缀, 正文直接输出."""
    if isinstance(delta, ThinkDelta):
        sys.stdout.write(f"\033[2m{delta.text}\033[0m")
    elif isinstance(delta, TextDelta):
        sys.stdout.write(delta.text)
    elif isinstance(delta, UsageDelta):
        sys.stdout.write(
            f"\n\n[用量 prompt={delta.prompt_tokens} "
            f"completion={delta.completion_tokens}"
            f"{f' finish={delta.finish_reason}' if delta.finish_reason else ''}]\n"
        )
    sys.stdout.flush()


async def run_interactive(
    llm: LLM,
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int = 4096,
) -> str:
    """流式打印到 stdout; Ctrl+C 或 llm.stop() 可中断."""
    messages: list[ChatMessage] = []
    if system:
        messages.append(ChatMessage(role="system", content=system))
    messages.append(ChatMessage(role="user", content=prompt))
    try:
        return await llm.complete(messages, max_tokens=max_tokens, on_delta=_default_printer)
    except LLMCancelledError:
        sys.stdout.write("\n[已停止]\n")
        sys.stdout.flush()
        return ""


async def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="MUNagent LLM 流式测试")
    parser.add_argument("prompt", nargs="?", default="用一句话介绍雅尔塔会议.")
    parser.add_argument("--provider", default=None, help="config 中的 provider 名")
    parser.add_argument("--model", default=None, help="模型名, 如 deepseek-v4-flash")
    parser.add_argument(
        "--thinking",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="是否开启 thinking",
    )
    parser.add_argument("--max-tokens", type=int, default=4096)
    args = parser.parse_args(argv)

    llm = LLM(provider=args.provider, model=args.model, thinking=args.thinking)
    started = time.perf_counter()
    try:
        await run_interactive(llm, args.prompt, max_tokens=args.max_tokens)
    except KeyboardInterrupt:
        llm.stop()
        await asyncio.sleep(0.1)
        sys.stdout.write("\n[已停止]\n")
    elapsed = time.perf_counter() - started
    sys.stderr.write(f"耗时 {elapsed:.1f}s\n")
    return 0


def _main_entry() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    _main_entry()
