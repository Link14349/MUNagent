"""书记 Agent 摘要输入裁剪."""

from munagent.agents.recorder import (
    build_summarize_prompt,
    estimate_tokens,
    render_for_summarize,
)
from munagent.core.events import Event


def _speech(seq: int, text: str) -> Event:
    return Event(
        session_id="s1",
        seq=seq,
        story_time="2026-03-15T09:00:00+08:00",
        type="speech",
        actor="seat:premier",
        venue_id="cabinet",
        scope="venue",
        payload={"text": text},
    )


def test_render_for_summarize_truncates_long_speech() -> None:
    long_text = "发言" * 300
    ev = _speech(1, long_text)
    rendered = render_for_summarize(ev, max_text_chars=50)
    assert "..." in rendered
    assert long_text not in rendered


def test_build_summarize_prompt_respects_budget() -> None:
    old = "旧摘要\n" * 500
    events = [_speech(i, f"事件{i}-" + "内容" * 200) for i in range(1, 30)]
    l4, trimmed = build_summarize_prompt(old, events, "venue")
    assert len(trimmed) < len(events)
    assert estimate_tokens(l4) <= 12_500
