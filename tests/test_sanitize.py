"""key 脱敏单元测试."""

from munagent.security.sanitize import sanitize_text


def test_sanitize_openai_key() -> None:
    raw = "401 Unauthorized: sk-abcdefghijklmnopqrstuvwxyz invalid"
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in sanitize_text(raw)
    assert "sk-****" in sanitize_text(raw)


def test_sanitize_tavily_key() -> None:
    raw = "failed with tvly-abcdefghijklmnop"
    assert "tvly-****" in sanitize_text(raw)


def test_sanitize_bearer() -> None:
    raw = "Authorization Bearer sk-secret-token failed"
    assert "Bearer ****" in sanitize_text(raw)
