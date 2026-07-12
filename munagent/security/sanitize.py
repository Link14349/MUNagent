"""日志/异常文本中的密钥脱敏 — 防止 key 落进可分享存档."""

from __future__ import annotations

import re

# 常见 API key 形态; 匹配后保留首尾便于排错
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bsk-[A-Za-z0-9]{8,}\b"), "sk-****"),
    (re.compile(r"\btvly-[A-Za-z0-9]{8,}\b"), "tvly-****"),
    (re.compile(r"(?i)(api[_-]?key[\"'=:]\s*)[^\s\"',}]+"), r"\1****"),
    (re.compile(r"(?i)(authorization:\s*bearer\s+)[^\s]+"), r"\1****"),
]


def sanitize_text(text: str) -> str:
    """脱敏任意可能含 key 的文本."""
    if not text:
        return text
    result = text
    for pattern, repl in _PATTERNS:
        result = pattern.sub(repl, result)
    return result


def sanitize_exception(exc: BaseException) -> str:
    """异常转字符串前先脱敏."""
    return sanitize_text(f"{type(exc).__name__}: {exc}")
