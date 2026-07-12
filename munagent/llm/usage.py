"""LLM 调用用量记录 — 供 llm_usage 表与命中率面板消费."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class UsageRecord:
    role: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    thinking_enabled: bool = False
    latency_ms: float = 0.0


UsageSink = Callable[[UsageRecord], None]


class UsageCollector:
    """内存收集器 — P0 测试用; 后续由 engine 写入 SQLite."""

    def __init__(self) -> None:
        self.records: list[UsageRecord] = []

    def emit(self, record: UsageRecord) -> None:
        self.records.append(record)
