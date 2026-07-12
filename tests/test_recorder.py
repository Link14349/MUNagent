"""书记 Agent 摘要输入裁剪."""

from munagent.agents.recorder import (
    G_RECORDER,
    JSON_TEXT_OUTPUT_RULES,
    build_chapter_prompt,
    build_consolidate_prompt,
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


def test_build_chapter_prompt_respects_budget() -> None:
    events = [_speech(i, f"事件{i}-" + "内容" * 200) for i in range(1, 60)]
    l4, trimmed = build_chapter_prompt(events, "venue")
    assert len(trimmed) < len(events)
    assert estimate_tokens(l4) <= 12_500


def test_chapter_prompt_has_no_old_summary_section() -> None:
    """章节追加模型: 摘章prompt不含旧摘要——旧章节不经LLM之手, 杜绝合并丢失."""
    l4, _ = build_chapter_prompt([_speech(1, "发言")], "venue")
    assert "旧摘要" not in l4
    assert "本期新事件" in l4


def test_consolidate_prompt_demands_full_coverage() -> None:
    l4 = build_consolidate_prompt(["第一章内容", "第二章内容"], "venue")
    assert "第一章内容" in l4 and "第二章内容" in l4
    assert "覆盖全部章节的时间范围" in l4


def test_recorder_prompt_requires_ascii_json_quotes() -> None:
    assert "ASCII 双引号" in JSON_TEXT_OUTPUT_RULES
    assert "ASCII 双引号" in G_RECORDER
    l4, _ = build_chapter_prompt([_speech(1, "发言")], "venue")
    assert "ASCII 双引号" in l4
