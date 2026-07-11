"""事件渲染器: 纯函数, 字节级确定. 见 11§4.

同一事件任何时候渲染进 prompt 必须字节级相同: 固定模板、固定字段顺序、
不掺渲染时刻的时间戳、不做随请求变化的编号重排. 修改渲染模板视为破坏性变更.
"""

from __future__ import annotations

from munagent.core.events import Event


def render(event: Event) -> str:
    """把事件渲染为 prompt 用的文本. 纯函数, 字节级确定."""
    parts: list[str] = []
    # 时间头(故事时间或真实时间, 固定取 story_time 优先)
    ts = event.story_time or event.real_time
    parts.append(f"[{ts}]")

    # 主体按 type 分模板
    t = event.type
    if t == "speech":
        parts.append(f"{event.actor}发言: {event.payload.get('text', '')}")
    elif t == "speech_thought":
        parts.append(f"(你当时的盘算: {event.payload.get('thought', '')})")
    elif t == "motion":
        parts.append(
            f"{event.actor}动议: {event.payload.get('motion_type', '')}"
            f"({event.payload.get('target', '')})"
        )
    elif t == "motion_ruling":
        parts.append(
            f"主持者裁决: {event.payload.get('ruling', '')}"
            f" (动议#{event.payload.get('motion_seq', '')}) {event.payload.get('reason', '')}"
        )
    elif t == "phase_change":
        parts.append(
            f"阶段切换: {event.payload.get('from', '')} → {event.payload.get('to', '')}"
            f" ({event.payload.get('reason', '')})"
        )
    elif t == "vote_call":
        parts.append(f"主席发起表决: 指令 {event.payload.get('directive_id', '')}")
    elif t == "vote_cast":
        parts.append(
            f"{event.actor}投票: {event.payload.get('choice', '')}"
            f" (指令 {event.payload.get('directive_id', '')})"
        )
    elif t == "vote_result":
        parts.append(
            f"表决结果: 指令 {event.payload.get('directive_id', '')} "
            f"= {event.payload.get('result', '')} ({event.payload.get('tally', '')})"
        )
    elif t == "directive_submitted":
        parts.append(
            f"{event.actor}提交{event.payload.get('kind', '')}指令: "
            f"{event.payload.get('title', '')}"
        )
    elif t == "directive_status":
        parts.append(
            f"指令 {event.payload.get('directive_id', '')} 状态: "
            f"{event.payload.get('status', '')}"
        )
    elif t == "adjudication":
        parts.append(
            f"DM判定: 指令 {event.payload.get('directive_id', '')} "
            f"概率{event.payload.get('probability_tier', '')}% "
            f"掷骰{event.payload.get('roll', '')} → {event.payload.get('outcome', '')}"
        )
    elif t == "crisis_update":
        parts.append(f"危机更新: {event.payload.get('text', '')}")
    elif t == "clock_advance":
        parts.append(
            f"时钟推进: {event.payload.get('from', '')} → {event.payload.get('to', '')}"
        )
    elif t == "presiding_change":
        parts.append(
            f"主持权变更: {event.payload.get('from_seat', '')} → {event.payload.get('to_seat', '')}"
            f" ({event.payload.get('cause', '')})"
        )
    elif t == "session_control":
        parts.append(f"会话控制: {event.payload.get('action', '')}")
    elif t == "summary_written":
        parts.append(f"摘要({event.payload.get('level', '')}): {event.payload.get('text', '')}")
    else:
        parts.append(f"{event.type}: {event.actor}")

    return " ".join(parts)
