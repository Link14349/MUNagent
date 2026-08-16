"""按当前权威状态和一批新观察构建代表 Agent 的单轮上下文。"""

from __future__ import annotations

from agent.inbox import EventSnapshot, Observation
from event.event import Event
from scenario.representative import Representative


_RECENT_EVENT_LIMIT = 8


def snapshot_event(event: Event) -> EventSnapshot:
    """复制事件的可提示字段。

    收件箱中的内容不会随后续事件编辑而漂移。
    """
    if event.id is None or event.time is None:
        raise ValueError("只有已经盖戳并入表的事件才能生成观察快照")

    attached_file = None
    for attribute in ("instruction", "resolution"):
        file = getattr(event, attribute, None)
        if file is None:
            continue
        filesystem = file._filesystem
        attached_file = (
            filesystem._relkey(file.path)
            if filesystem is not None
            else file.path.name
        )
        break

    return EventSnapshot(
        id=event.id,
        venue_id=event.venue,
        event_type=event.type.value,
        content=event.content,
        status=event.status.value,
        time=event.time.isoformat(),
        scope=tuple(sorted(event.scope)),
        attached_file=attached_file,
    )


def build_activation_prompt(
    rep: Representative,
    observations: list[Observation],
) -> str:
    """构建一次激活使用的 user 消息；不延续上一轮 LLM 临时对话。"""
    venue = rep._require_venue()
    current_agenda = venue.current_agenda
    agenda_text = (
        f"{current_agenda.title}（{current_agenda.id}）"
        if current_agenda is not None
        else "无"
    )
    phase = venue.session_phase.value if venue.session_phase is not None else "未设置"

    visible = venue._require_event_list().get_events(rep.id)
    pending = [event for event in visible if event.status.value == "pending"]
    recent = visible[-_RECENT_EVENT_LIMIT:]

    return f"""你因新的会场变化被激活。
下面的“新观察”是本轮必须优先处理的信息；
“近期事件”和“未决事项”只用于恢复必要上下文。
普通文本不会对外生效，只有成功的工具调用才会产生行动。

# 当前权威状态

- 剧情时间：{venue.scenario.time.isoformat()}
- 会场阶段：{phase}
- 当前议题：{agenda_text}

# 新观察

{_format_observations(observations)}

# 当前未决事项

{_format_events(pending)}

# 近期可见事件（最多 {_RECENT_EVENT_LIMIT} 条）

{_format_events(recent)}

请判断这些变化是否需要你采取行动。若需要，直接使用工具；
若不需要，不要为了刷存在感而重复发言。"""


def _format_observations(observations: list[Observation]) -> str:
    if not observations:
        return "- 无"
    lines: list[str] = []
    for observation in observations:
        change = observation.kind.value
        if observation.changed_field is not None:
            change = f"{change}:{observation.changed_field}"
        actor = observation.actor_id or "系统/未知"
        lines.append(
            f"- [观察序号 {observation.sequence}] {change}；行动者：{actor}；"
            f"优先级：{observation.priority.value}\n"
            f"  {_format_snapshot(observation.event)}"
        )
    return "\n".join(lines)


def _format_events(events: list[Event]) -> str:
    if not events:
        return "- 无"
    return "\n".join(f"- {_format_snapshot(snapshot_event(event))}" for event in events)


def _format_snapshot(event: EventSnapshot) -> str:
    file_text = f"；绑定文件：{event.attached_file}" if event.attached_file else ""
    return (
        f"事件 #{event.id} [{event.event_type}/{event.status}] "
        f"{event.time}：{event.content}{file_text}"
    )
