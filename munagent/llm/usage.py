"""LLM 调用用量记录(不进事件日志)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class UsageRecord:
    role: str
    task: str
    model: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    thinking_enabled: bool = False
    real_time: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @classmethod
    def from_response(
        cls,
        *,
        role: str,
        task: str,
        model: str,
        provider: str,
        usage: dict,
        thinking_enabled: bool,
    ) -> UsageRecord:
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
        cache_hit = int(usage.get("prompt_cache_hit_tokens", 0))
        cache_miss = int(usage.get("prompt_cache_miss_tokens", 0))
        if cache_hit == 0 and cache_miss == 0 and prompt_tokens:
            cache_miss = prompt_tokens
        return cls(
            role=role,
            task=task,
            model=model,
            provider=provider,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_hit_tokens=cache_hit,
            cache_miss_tokens=cache_miss,
            thinking_enabled=thinking_enabled,
        )
