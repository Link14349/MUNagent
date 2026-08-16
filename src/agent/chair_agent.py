"""单会场主席 Agent：主持程序，不代替代表进行政治行动。"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from agent.chair_tools import ChairToolExecutor
from agent.inbox import Observation
from agent.memory import AgentMemory
from agent.system_agent import EventDrivenSystemAgent
from scenario.venue import Venue

if TYPE_CHECKING:
    from llm import LLM
    from scenario.representative import Representative


class ChairAgent(EventDrivenSystemAgent):
    """会场主席运行角色。

    中立主席不取得任何代表秘密；代表主席只继承该代表自身的角色信息和
    结构化长期记忆。两种模式都只拥有主席工具。
    """

    venue: Venue
    tools: ChairToolExecutor

    def __init__(
        self,
        venue: Venue,
        *,
        llm: LLM | None = None,
        representative_memory: AgentMemory | None = None,
        stop_event: threading.Event | None = None,
    ) -> None:
        self.venue = venue
        self.representative_memory = representative_memory
        tools = ChairToolExecutor(venue)
        super().__init__(
            identity=f"chair:{venue.id}",
            system_prompt=_build_chair_system_prompt(venue),
            tools=tools,
            llm=llm,
            stop_event=stop_event,
            interrupt_on_urgent=True,
        )
        venue.chair_agent_managed = llm is not None

    @property
    def mode(self) -> str:
        return "representative" if self.venue.chair is not None else "neutral"

    def initial_prompt(self) -> str | None:
        self.tools.begin_turn()
        return self._state_prompt(
            "会议调度线程刚启动。检查当前阶段与议程；只有确有程序需要时才使用工具。"
        )

    def before_step(self, observations: list[Observation]) -> None:
        self.tools.begin_turn()

    def build_prompt(self, observations: list[Observation]) -> str:
        lines = []
        for item in observations:
            target_text = (
                f"；点名={list(item.event.target_reps)}"
                if item.event.target_reps
                else ""
            )
            lines.append(
                f"- [序号 {item.sequence}] {item.kind.value}；"
                f"事件 #{item.event.id} "
                f"[{item.event.event_type}/{item.event.status}]；"
                f"行动者={item.actor_id or '系统/未知'}："
                f"{item.event.content}{target_text}"
            )
        return self._state_prompt(
            "你因以下会场变化被激活：\n" + "\n".join(lines)
        )

    def _state_prompt(self, opening: str) -> str:
        agenda = self.venue.current_agenda
        pending = self.tools.visible_pending()
        agenda_text = (
            f"{agenda.title}（{agenda.id}）" if agenda is not None else "无"
        )
        phase = (
            self.venue.session_phase.value
            if self.venue.session_phase is not None
            else "未设置"
        )
        pending_text = "\n".join(
            f"- #{item.id} [{item.type.value}/{item.status.value}] {item.content}"
            for item in pending[-12:]
        ) or "- 无"
        recent_text = "\n".join(
            f"- #{item.id} [{item.type.value}/{item.status.value}] {item.content}"
            for item in self.tools.visible_events()[-10:]
            if item not in pending
        ) or "- 无"
        memory_text = "- 不适用（中立主席）"
        if self.representative_memory is not None:
            memories = self.representative_memory.relevant(
                f"{agenda_text}\n{opening}",
                limit=8,
            )
            memory_text = "\n".join(
                f"- [{item.id}/{item.category.value}/重要度 {item.importance}] "
                f"{item.content}"
                for item in memories
            ) or "- 无相关 active 记忆"
        return f"""{opening}

# 当前权威状态

- 剧情时间：{self.venue.scenario.time.isoformat()}
- 会场阶段：{phase}
- 当前议题：{agenda_text}
- 主席模式：{self.mode}
- 主席身份：{self.venue.chair_actor_id()}

# 当前未决事件

{pending_text}

# 主席可见的近期事件

{recent_text}

# 主席代表自身的相关长期记忆

{memory_text}

判断是否需要点名、澄清程序、组织表决、裁定决议或落实已经通过的动议。
普通文本不会对会议生效；需要采取主持行动时必须调用工具。
不要为了回应每条普通发言而制造程序噪音。"""


def _build_chair_system_prompt(venue: Venue) -> str:
    powers = "\n".join(
        f"- {power.value}：{'允许' if enabled else '禁止'}"
        for power, enabled in venue.chair_power.items()
    )
    identity = "系统中立主席"
    role_context = """你没有国家立场、私密目标或谈判利益。保持程序中立，
只依据会议当前权威状态、已提交事件、表决结果和主席权力行动。"""
    if venue.chair is not None:
        rep = venue.reps[venue.chair]
        identity = f"{rep.name}（代表 ID：{rep.id}）兼任主席"
        role_context = _representative_chair_context(rep)

    return f"""你是 MUNagent 会场 {venue.name}（{venue.id}）的 ChairAgent。
你的唯一职责是主持会议程序：维护议程与阶段、点名发言、组织并记录表决，
以及在权限允许时裁定决议。你不能代替任何代表公开发表
政治立场、传纸条、撰写或提交代表文件，也不能推演指令造成的外部世界结果；
后者属于 DMAgent。

# 主席身份

{identity}

{role_context}

# 主席权力

{powers}

# 不变量

1. 只有成功的主席工具调用才会改变会议；普通回复只是内部说明。
2. `decide_resolution` 权力关闭时，不得直接接受或拒绝决议，只能组织表决。
3. `decide_switch_phase` 权力关闭时，只能落实已经通过且目标一致的阶段动议。
4. 指令的可行性分档和成败判定完全属于 DMAgent，主席不得接受、拒绝或裁定指令。
5. 裁定正式决议前先用 `read_submission` 检查正文；长文按 offset 分段读取。
6. 点名事件全场可见，但只激活被点名代表。涉及私密提交的程序事件不得扩大原 scope。
7. 不读取其他代表的纸条、私聊、秘密文件或私有记忆。
8. 代表主席可以考虑本代表自身立场，但仍须遵守显式权限并留下裁定事件。
9. 每次激活只处理当前程序需要，避免对普通发言逐条重复回应。"""


def _representative_chair_context(rep: Representative) -> str:
    targets = "\n".join(
        f"- [{item.importance}] {item.objective}" for item in rep.private_target
    ) or "- 无"
    red_lines = "\n".join(f"- {item}" for item in rep.private_red_lines) or "- 无"
    bargaining = (
        "\n".join(f"- {item}" for item in rep.private_bargaining_space) or "- 无"
    )
    persona = rep._persona
    return f"""你与该代表的 RepresentativeAgent 属于同一人物，但职责和工具分离。
你可以在规则允许的酌情空间内考虑该代表自己的立场与记忆；不得借主席身份取得
其他代表的秘密，也不得执行属于 RepresentativeAgent 的政治行动。

- 公开立场：{rep.position}
- 人物性格：{persona.get('personality', '')}
- 决策倾向：{persona.get('decision_tendency', '')}

## 私密目标

{targets}

## 私密底线

{red_lines}

## 可谈判空间

{bargaining}"""
