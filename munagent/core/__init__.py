"""核心域模型: 事件总线、状态机、时钟、场景包、reducer."""

from munagent.core.events import Event, Scope, materialize_visible_to
from munagent.core.bus import EventBus

__all__ = ["Event", "EventBus", "Scope", "materialize_visible_to"]
