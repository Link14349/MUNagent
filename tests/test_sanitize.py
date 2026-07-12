"""密钥脱敏测试."""

from munagent.security import sanitize_exception, sanitize_text


def test_sanitize_sk_key() -> None:
    raw = "401 Unauthorized: sk-abcdefghijklmnop not valid"
    assert "sk-abcdefghijklmnop" not in sanitize_text(raw)
    assert "sk-****" in sanitize_text(raw)


def test_sanitize_tvly_key() -> None:
    raw = "error tvly-abcdefghijklmnop timeout"
    assert "tvly-****" in sanitize_text(raw)


def test_sanitize_exception() -> None:
    exc = RuntimeError("Bearer sk-secretkey1234567890 failed")
    text = sanitize_exception(exc)
    assert "sk-secretkey1234567890" not in text
