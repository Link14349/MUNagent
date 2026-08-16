"""单会场 DM Agent：裁定指令成败并推演已裁定决议。"""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import TYPE_CHECKING

from agent.dm_tools import DMToolExecutor, InstructionAdjudication
from agent.inbox import Observation
from agent.system_agent import EventDrivenSystemAgent
from event.event import (
    Event,
    EventStatus,
    EventType,
    InstructionEvent,
    ResolutionEvent,
    SystemEvent,
)
from filesystem.filesystem import SYSTEM_ACTOR
from scenario.venue import Venue

if TYPE_CHECKING:
    from llm import LLM


_SUBMISSION_PREVIEW_CHARS = 6000


@dataclass(frozen=True)
class DMOutcome:
    """一次指令/决议任务的可审计处理结果。"""

    source_event_id: int
    source_status: str
    published_event_ids: tuple[int, ...]
    advanced_minutes: int
    instruction_adjudication: InstructionAdjudication | None
    final_text: str


class DMAgent(EventDrivenSystemAgent):
    """不监听普通对话；裁定指令成败并推演已裁定决议。"""

    venue: Venue
    tools: DMToolExecutor

    def __init__(
        self,
        venue: Venue,
        *,
        llm: LLM | None = None,
        random_seed: str | int = "0",
        stop_event: threading.Event | None = None,
    ) -> None:
        self.venue = venue
        self.__task_lock = threading.RLock()
        self.__queued_event_ids: set[int] = set()
        self.__processed_event_ids: set[int] = set()
        self.__active_events: list[Event] = []
        self.__outcomes: list[DMOutcome] = []
        tools = DMToolExecutor(venue, random_seed=random_seed)
        super().__init__(
            identity=f"dm:{venue.id}",
            system_prompt=_build_dm_system_prompt(venue),
            tools=tools,
            llm=llm,
            stop_event=stop_event,
            interrupt_on_urgent=False,
        )

    @property
    def processed_event_ids(self) -> set[int]:
        with self.__task_lock:
            return set(self.__processed_event_ids)

    @property
    def outcomes(self) -> list[DMOutcome]:
        with self.__task_lock:
            return list(self.__outcomes)

    def notify(self, observation: Observation) -> bool:
        event_id = observation.event.id
        with self.__task_lock:
            if (
                event_id in self.__queued_event_ids
                or event_id in self.__processed_event_ids
            ):
                return False
            self.__queued_event_ids.add(event_id)
        accepted = super().notify(observation)
        if not accepted:
            with self.__task_lock:
                self.__queued_event_ids.discard(event_id)
        return accepted

    def before_step(self, observations: list[Observation]) -> None:
        events = self.venue._require_event_list().events
        active: list[Event] = []
        for item in observations:
            event_id = item.event.id
            if event_id < 0 or event_id >= len(events):
                raise RuntimeError(
                    f"DMAgent 收到不存在的会场事件 #{event_id}"
                )
            event = events[event_id]
            if not isinstance(event, (InstructionEvent, ResolutionEvent)):
                raise TypeError(
                    f"DMAgent 收到不支持的事件类型: {type(event).__name__}"
                )
            active.append(event)
        self.__active_events = active
        self.tools.begin_tasks(active)

    def activation_batches(
        self,
        observations: list[Observation],
    ) -> list[list[Observation]]:
        """提交正文可能很长；每个指令/决议使用独立局部上下文。"""
        return [[item] for item in observations]

    def build_prompt(self, observations: list[Observation]) -> str:
        blocks = [self._task_block(event) for event in self.__active_events]
        venue = self.venue
        agenda = venue.current_agenda
        agenda_text = (
            f"{agenda.title}（{agenda.id}）" if agenda is not None else "无"
        )
        phase = (
            venue.session_phase.value
            if venue.session_phase is not None
            else "未设置"
        )
        return f"""你收到了一批新的指令/决议任务。每个任务只处理一次。

# 当前权威状态

- 剧情时间：{venue.scenario.time.isoformat()}
- 会场阶段：{phase}
- 当前议题：{agenda_text}

# 近期危机与正式行动

{self._recent_world_events()}

# 当前任务

{''.join(blocks)}

对 pending 指令，先根据权限、资源、时距、组织阻力、对手反制和情报质量选择六档，
调用 `adjudicate_instruction` 进行唯一一次随机判定；然后严格按照返回的成功/失败结果
推演，不得自行更改骰点。无论成功或失败，都至少发布一条相应的危机更新。

对 accepted 决议直接推演其实际执行结果，并至少发布一条危机更新；rejected 决议不得
执行或推进时间。需要时可推进剧情时间，并用不同 scope 的更新表达不同知情层级。
普通文本不会发布给代表。"""

    def _recent_world_events(self) -> str:
        active_ids = {event.id for event in self.__active_events}
        excluded = {EventType.NOTE, EventType.CHAT, EventType.MESSAGE}
        candidates = [
            event
            for event in self.venue._require_event_list().events
            if event.id not in active_ids and event.type not in excluded
        ][-12:]
        if not candidates:
            return "- 无"
        lines: list[str] = []
        for event in candidates:
            action_text = ""
            if isinstance(event, SystemEvent) and event.action:
                action_text = f"；变化={event.action}"
            lines.append(
                f"- #{event.id} [{event.type.value}/{event.status.value}] "
                f"{event.content}{action_text}"
            )
        return "\n".join(lines)

    def after_step(
        self,
        observations: list[Observation],
        *,
        completed: bool,
        final_text: str,
    ) -> None:
        if not completed:
            return
        results = self.tools.task_results()
        with self.__task_lock:
            for event in self.__active_events:
                if event.id is None:
                    continue
                result = results[event.id]
                if (
                    isinstance(event, InstructionEvent)
                    and result.instruction_adjudication is None
                ):
                    raise RuntimeError(
                        f"DMAgent 未对指令 #{event.id} 完成六档概率判定"
                    )
                must_publish = isinstance(event, InstructionEvent) or (
                    isinstance(event, ResolutionEvent)
                    and event.status == EventStatus.ACCEPTED
                )
                if must_publish and not result.published_event_ids:
                    raise RuntimeError(
                        f"DMAgent 未为可执行任务 #{event.id} 发布危机更新"
                    )
                self.__outcomes.append(
                    DMOutcome(
                        source_event_id=event.id,
                        source_status=event.status.value,
                        published_event_ids=result.published_event_ids,
                        advanced_minutes=result.advanced_minutes,
                        instruction_adjudication=(
                            result.instruction_adjudication
                        ),
                        final_text=final_text,
                    )
                )
                self.__queued_event_ids.discard(event.id)
                self.__processed_event_ids.add(event.id)
        self.__active_events = []

    @staticmethod
    def _task_block(event: Event) -> str:
        if event.id is None:
            raise ValueError("DM 任务事件尚未入表")
        file = (
            event.instruction
            if isinstance(event, InstructionEvent)
            else event.resolution
        )
        filesystem = file._filesystem
        path = (
            filesystem._relkey(file.path)
            if filesystem is not None
            else file.path.name
        )
        submission = file.get_content(SYSTEM_ACTOR)
        preview = submission[:_SUBMISSION_PREVIEW_CHARS]
        remainder = len(submission) - len(preview)
        truncation = (
            f"\n\n（正文尚有 {remainder} 字符未注入；"
            "使用 read_submission 按 offset 继续读取。）"
            if remainder > 0
            else ""
        )
        return f"""
## 事件 #{event.id} [{event.type.value}/{event.status.value}]

- 事件说明：{event.content}
- 原事件可见范围：{sorted(event.scope)}
- 提交文件：{path}

### 提交全文

{preview}{truncation}
"""


def _build_dm_system_prompt(venue: Venue) -> str:
    targets = "\n".join(f"- {item}" for item in venue.scenario.targets) or "- 无"
    return f"""你是 MUNagent 会场 {venue.name}（{venue.id}）的 DMAgent，负责危机推演。
你不是主席或代表，不参与会议辩论。决议是否通过由主席/表决决定；指令则不经过主席
接受或拒绝，而是在 pending 状态直接交给你作六档可行性判断和随机成败判定。

# 场景背景

{venue.scenario.background}

# 推演目标

{targets}

# 工作规则

1. pending 指令必须先选择六档之一：极有可能成功 95%、成功 80%、可能成功 60%、
   可能失败 40%、失败 20%、极大概率失败 5%。分档依据必须写入 rationale。
2. `adjudicate_instruction` 返回的 roll 是唯一有效骰点；roll < probability 才成功。
   成功把指令状态记为 completed，失败记为 failed，不使用 accepted/rejected。
3. accepted/rejected 只用于决议。accepted 决议允许推演，rejected 决议不得执行。
4. 推演须考虑权限、资源、时距、组织摩擦、对手反应和已有危机状态。
5. 每条危机更新必须通过工具发布，并绑定 `source_event_id`；普通文本不对代表可见。
6. scope 是硬可见性边界。可以让秘密行动造成公开可观察后果，但不得在扩大后的 scope
   中泄露原提交的秘密正文、行动者身份或只有提交范围内才知道的细节。
7. 如结果对不同代表可见程度不同，应发布多条不同 scope、不同内容的更新。
8. 不生成新的代表指令或决议，不修改提交文件，不替主席裁定决议。
9. 相同指令只能分档和抽取一次；更新须客观描述结果并保留不确定性。"""
