"""安全卫生: api key 等敏感信息脱敏."""

from __future__ import annotations

import re

# OpenAI/DeepSeek sk-*, Tavily tvly-*, Bearer token, 常见 query param
_KEY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-[A-Za-z0-9_-]{8,}"), "sk-****"),
    (re.compile(r"tvly-[A-Za-z0-9_-]{8,}"), "tvly-****"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._-]+", re.IGNORECASE), "Bearer ****"),
    (re.compile(r"(api[_-]?key[\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9._-]+", re.IGNORECASE), r"\1****"),
]


def sanitize_text(text: str) -> str:
    """日志/异常/事件落地前剥离 key 等敏感片段."""
    result = text
    for pattern, repl in _KEY_PATTERNS:
        result = pattern.sub(repl, result)
    return result
