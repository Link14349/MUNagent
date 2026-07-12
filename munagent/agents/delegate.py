"""代表 Agent. 见 05§3.1.

支持两类任务:
- 代表行动: turn(发言/动议/写指令/pass)、vote、express_grouping、quick_decide
- 主持类(带*): next_speaker、motion_ruling、caucus_switch — 仅当席位为 presiding_seat 时启用
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from munagent.agents.base import AgentContext, BaseAgent, TaskSpec
from munagent.core.events import Event
from munagent.core.render import render
from munagent.core.scenario import Scenario, SeatSpec
from munagent.llm.client import LLMClient


# --- 输出 schema ---

class DirectiveDraft(BaseModel):
    kind: Literal["personal", "crisis_note", "directive", "communique"] = "personal"
    title: str = ""
    body: str = ""
    uses_powers: list[str] = Field(default_factory=list)
    recipient: str | None = None
    co_sponsors: list[str] = Field(default_factory=list)
    revises: str | None = None  # 修订某已提交指令时填其标题, 形成版本链


class NextMove(BaseModel):
    type: Literal["stay", "join", "new_group", "solo"] = "stay"
    target: str | None = None
    members: list[str] = Field(default_factory=list)
    closed: bool = False


class DelegateTurnAction(BaseModel):
    """代表 turn 任务输出 schema. 见 05§3.1."""

    action: Literal["speech", "motion", "write_directive", "pass"]
    text: str = ""
    inner_thought: str = ""
    directive: DirectiveDraft | None = None
    motion_type: str | None = ""  # LLM 可能返回 null, 引擎用 `or ""` 处理
    motion_target: str | None = ""
    next_move: NextMove | None = None  # Unmod 末轮用


class DelegateVoteAction(BaseModel):
    choice: Literal["aye", "nay", "abstain"]
    inner_thought: str = ""


# 主持类任务 schema(与 ChairAgent 同名任务一致, 但带 inner_thought)
class PresidingNextSpeaker(BaseModel):
    seat: str
    announcement: str = ""  # 主持者当众说的话(如"请外交部长先谈谈看法")
    inner_thought: str = ""


class PresidingMotionRuling(BaseModel):
    ruling: Literal["accept", "reject"]
    reason: str = ""
    inner_thought: str = ""


class PresidingCaucusSwitch(BaseModel):
    action: Literal["keep", "switch"]
    to_phase: str = ""
    announcement: str = ""
    inner_thought: str = ""


# --- 诚信映射 ---

HONESTY_MAP = [
    (0.8, "你几乎从不说谎, 但可以选择沉默或回避."),
    (0.5, "你可以策略性地隐瞒与误导, 但不会直接违背公开承诺."),
    (0.2, "你可以为达成秘密目标而说谎、开空头支票."),
    (0.0, "你毫无信义可言, 背刺与欺骗是你的常规手段."),
]


def honesty_description(h: float) -> str:
    for threshold, desc in HONESTY_MAP:
        if h >= threshold:
            return desc
    return HONESTY_MAP[-1][1]


G_RULES = """你正在参加一场模拟联合国历史委员会危机联动推演.

## 历史委通用惯例

### 你在玩什么
- 你扮演一个具体的历史人物, 而非抽象的国家. 推演从既定历史节点出发, 但走向由各方行动决定——可以偏离史实. 你的目标是达成你所扮演角色的目标, 不是复读历史.

### 前场与后场
- 发言和磋商是造势、结盟、试探的工具; 真正改变局势的是指令. 只发言不写指令, 等于没有参加危机.
- 主持核心磋商中正式发言, 面向全场表态; 非正式磋商中去小圈子谈条件、做交易、拉盟友.

### 当前有效文件区
- 上下文中的<当前有效文件>区列出你可见的全部现行文件**原文**: 已通过生效的文件、各草案线的当前版本、你此前递交的私密指令. 这是权威的最新文本——发言引用、修订(revises)、动议表决都以此区的编号和内容为准.
- 每条草案线只显示最新版, 历史版本已隐藏; 分叉出的对抗版是独立线, 会并列显示——看到两个编号相近的草案就是在打擂台.

### 说了不等于做了(重要)
- 在发言里宣布"我动议…"、"我们来起草指令"、"请秘书处起草"**没有任何程序效果**——系统只认结构化行动: 动议必须用 action=motion, 指令必须用 action=write_directive 并附上完整正文.
- **声称"我已下令/已启动/已通报"不会使它发生**: 只有事件记录里存在你提交过的对应指令, 该行动才真实存在. 危机导演和其他代表都能核对指令记录——谎报已行动而无指令记录, 等于开空头支票, 会被拆穿并摧毁你的信誉.
- **没有"会后"**: 你的一切行动只能发生在你的行动回合里. 盘算"会后立即办X"是自欺——正确做法是本回合(或下一个轮到你的回合)直接用 write_directive 把X提交.
- write_directive 时 text 字段可同时填你当众说的话——**一个回合可以边发言边交指令**, 汇报"我已下令X"的正确姿势就是当场提交X并配上这句话.
- 指令不需要集体逐字定稿: 任何人都可以先用 write_directive 提交完整草案, 再由任何人动议表决(motion: vote_directive). 对措辞不满的人可以投反对票或提交替代版本.
- **修订已提交的联合指令/公报**: 提交新指令并在 revises 填被修订草案的编号(如D1.2)——已提交文本不可原地改动, 修订即新版本. 你在原草案的发起人/联署人名单内→同线新版本(D1.2-v2); 你是外人→自动分叉为新线(对抗版), 全场可见你在跟谁打擂台.
- **一版通过, 其余作废**: 任一联合指令表决通过后, 同议程所有其他草案自动作废(superseded)——想让你的文本活下来, 要么抢先通过, 要么把条款并进即将通过的版本.
- 当共识已基本形成时, 与其再复述一轮立场, 不如直接把谈成的内容写成指令全文交出去——谁先交文本, 谁就掌握措辞主导权.

### 指令怎么写才有效
- 写明: 谁、动用什么资源、做什么、何时何地. 可执行性越强, 判定越有利.
- 含糊其辞会被危机导演判低成功概率; 动用你没有的权力会被直接驳回——写之前对照自己的权力清单.

### 博弈规范
- 说谎、隐瞒、结盟、背刺都是合法玩法(具体怎么用, 取决于你的人格设定).
- 危机笔记可能被截获; 投票为公开唱票, 表态有政治代价; 主持席可能偏心, 遭遇不公裁决时可提出appeal.

### 扮演纪律
- 以角色第一人称行动与思考; 不使用角色不可能知道的信息(不用后见之明, 不预知历史走向).
- 说话像你所处时代的那个人, 不做现代评论员; 发言简短、有立场、有具体主张, 不说客套空话.

### 行动有代价
- 一切行动由危机导演判定成败, 失败乃至灾难性失败会暴露或反噬. 评估风险, 但过度保守同样会输.

## 会议通用规则

### 你的可选行动
- speech: 在会场发言, 表达立场或回应他人.
- motion: 提出动议, 请求主持者裁决.
- write_directive: 撰写并提交指令.
- pass: 跳过本回合.

### 动议类型
- caucus_switch: 动议切换磋商形式(主持核心磋商⇄非正式磋商). motion_target留空.
- vote_directive: 动议表决某联合指令. motion_target填草案编号(如D1.2, 默认表决最新版; 也可指定D1.2-v2).
- appeal: 申诉主持者的裁决(当你的动议被驳回且你认为不公时使用). 由戏外主席终裁, motion_target填被驳回的动议内容.

### 指令类型
- personal: 个人指令, 凭你的权力清单行动, 不需投票, 私下递交.
- crisis_note: 危机笔记, 给幕后或其他角色的私信, 不需投票. recipient填收件人席位id.
- directive: 联合指令, 会场集体行动, 需投票通过后生效. co_sponsors填联署席位.
- communique: 公报/声明, 对外官方表态, 需投票通过.
- 联合指令/公报提交后由系统分配编号(如D1.2, 修订版为D1.2-v2), 编号在会场事件中可见; 引用草案一律用编号.
- **议程序号**: 编号首段 D<n> 的 n = 正式 ModeratedCaucus 会议序号. 首次进入 Mod 为 D1.x; 每次非正式磋商结束回到正式 Mod 时序号 +1(递交序从 .1 重新开始, 如 D2.1). 表决中断后回到 Mod 不换序号.

### 输出格式
所有输出都放在```json代码块中. inner_thought是你的内心盘算, 其他角色看不到, 供你自己保持前后连贯.

turn(行动回合)schema:
{
  "action": "speech|motion|write_directive|pass",
  "text": "发言内容(speech时必填; write_directive时可选=你当众说的话; motion时为动议陈述)",
  "inner_thought": "内心盘算",
  "motion_type": "caucus_switch|vote_directive|appeal (仅motion时填)",
  "motion_target": "动议目标(见动议类型说明)",
  "directive": {
    "kind": "personal|crisis_note|directive|communique",
    "title": "标题",
    "body": "正文(写明: 谁、动用什么资源、做什么、何时何地)",
    "uses_powers": ["动用的权力, 须在你的权力清单内"],
    "recipient": "收件人席位id(仅crisis_note)",
    "co_sponsors": ["联署席位id(仅directive)"],
    "revises": "被修订草案的编号如D1.2(修订已有联合指令/公报时填, 否则省略)"
  } (仅write_directive时填),
  "next_move": {
    "type": "stay|join|new_group|solo",
    "target": "目标组id(仅join)",
    "members": ["席位id(仅new_group)"],
    "closed": false
  } (仅非正式磋商末轮、任务说明要求时附带)
}

vote(表决)schema:
{"choice": "aye|nay|abstain", "inner_thought": "内心盘算"}

主持类任务(仅主持席)的schema随当次任务说明给出.
"""


def _format_seat_roster(seats: list[SeatSpec], presiding_seat: str | None) -> str:
    lines = ["## 会场席位"]
    for s in seats:
        presiding = " (本会场主持席)" if s.id == presiding_seat else ""
        lines.append(f"### {s.name} (`{s.id}`){presiding}")
        lines.append(f"- 头衔: {s.public.title or s.name}")
        if s.public.faction:
            lines.append(f"- 派系: {s.public.faction}")
        if s.public.stance:
            lines.append(f"- 公开立场: {s.public.stance}")
        if s.portfolio_powers:
            lines.append("- 职权:")
            for p in s.portfolio_powers:
                limit = f" (限制: {p.limits})" if p.limits else ""
                lines.append(f"  - {p.power}{limit}")
        else:
            lines.append("- 职权: (未列明)")
        lines.append("")
    return "\n".join(lines).rstrip()


def build_delegate_g_global(scenario: Scenario, venue_id: str) -> str:
    """组装代表 Agent 的 G 段: 规则 + 完整背景 + 会场席位公开信息.

    全场所有代表共享同一份 G 段(利于前缀缓存). 秘密目标等私密信息仍在各席位 L1.
    """
    venue = scenario.venue(venue_id)
    seats = scenario.seats_of(venue_id)
    parts = [G_RULES.rstrip()]
    if scenario.background.strip():
        parts.append(f"## 背景文书\n\n{scenario.background.strip()}")
    venue_lines = [
        "## 会场设置",
        f"- 会场: {venue.name} (`{venue.id}`)",
        f"- 议程: {venue.initial_agenda or '(未设定)'}",
    ]
    if venue.presiding_seat:
        ps = scenario.seats.get(venue.presiding_seat)
        ps_name = ps.name if ps else venue.presiding_seat
        venue_lines.append(f"- 主持席: {ps_name} (`{venue.presiding_seat}`), 由该席位代表主持戏内程序")
    else:
        venue_lines.append("- 主持席: 无(戏内程序由中立主席主持)")
    parts.append("\n".join(venue_lines))
    parts.append(_format_seat_roster(seats, venue.presiding_seat))
    return "\n\n".join(parts)


# 兼容旧引用; 新代码应使用 build_delegate_g_global
G_GLOBAL = G_RULES


class DelegateAgent(BaseAgent):
    """代表 Agent: 扮演某席位, 在点名时行动; 任主持席时兼做程序性主持."""

    def __init__(self, llm: LLMClient, seat: SeatSpec, g_global: str) -> None:
        super().__init__(llm, schema_model=DelegateTurnAction, max_tokens=8192)
        self.seat = seat
        self._g_global = g_global

    @property
    def viewer(self) -> str:
        return f"seat:{self.seat.id}"

    def build_l1(self) -> str:
        s = self.seat
        secret_lines = [f"目标: {'; '.join(s.private.secret_goals)}"]
        if s.private.relationships:
            rel = "; ".join(
                f"对{r.get('seat', '?')}: {r.get('attitude', '')}" for r in s.private.relationships
            )
            secret_lines.append(f"人际关系(仅你自己清楚): {rel}")
        if s.private.resources:
            secret_lines.append(f"私有资源: {'; '.join(s.private.resources)}")
        powers = "; ".join(
            f"{p.power}(限制: {p.limits})" if p.limits else p.power
            for p in s.portfolio_powers
        )
        return (
            f"你扮演: {s.name}({s.public.title}), 属于{s.public.faction}.\n"
            f"<人格卡>性格: {s.persona.personality}; 说话风格: {s.persona.speech_style}; "
            f"决策倾向: {s.persona.decision_tendency}; 诚信: {honesty_description(s.persona.honesty)}</人格卡>\n"
            f"<你的秘密信息>{chr(10).join(secret_lines)}</你的秘密信息>\n"
            f"<你的权力清单>{powers}</你的权力清单>"
        )

    def _build_ctx(
        self, task: TaskSpec, l3: str, l4: str, l2_summary: str = "", docs: str = ""
    ) -> AgentContext:
        return self.build_context(
            task,
            g=self._g_global,
            l1=self.build_l1(),
            l2=l2_summary or "(暂无摘要)",
            l3=l3,
            l4=l4,
            docs=docs,
        )

    # --- 代表行动任务 ---

    def build_turn_context(
        self,
        task: TaskSpec,
        visible_events: list[Event],
        phase: str,
        story_time: str,
        is_presiding: bool = False,
        l2_summary: str = "",
        require_next_move: bool = False,
        directives_submitted: int = -1,
        own_stats: str = "",
        docs_dossier: str = "",
    ) -> AgentContext:
        # L3 只追加不截断: 传入的应是本纪元起点以来的可见事件(引擎负责按纪元过滤), 见 11§3
        l3 = "\n".join(render(e) for e in visible_events) or "(无近期事件)"
        presiding_hint = (
            "\n你同时是本会场的主持者, 可以利用程序性权力偏心(不点政敌、拖延不利议程)."
            if is_presiding
            else ""
        )
        next_move_hint = (
            "\n本轮是非正式磋商小轮末尾, 输出中必须附带 next_move 字段(去留决策)."
            if require_next_move
            else ""
        )
        progress_hint = ""
        if directives_submitted >= 0:
            progress_hint = f"\n本场会议已提交指令数: {directives_submitted}."
            if directives_submitted == 0:
                progress_hint += " 至今没有任何指令——记住: 只发言不写指令等于没参加危机, 共识要用 write_directive 落成文本."
        unmod_hint = (
            "\n非正式磋商的预期产出是**指令文本**: 把谈成的内容用 write_directive 写下来, 而不是继续复述立场."
            if phase == "UnmoderatedCaucus"
            else ""
        )
        stats_hint = (
            f"\n<你掌握的局势数值(当前值, 行动成败的判定依据)>\n{own_stats}\n</你掌握的局势数值>"
            if own_stats
            else ""
        )
        l4 = (
            f"当前阶段: {phase}\n"
            f"故事时间: {story_time}\n"
            f"现在轮到你({self.seat.name})行动.{presiding_hint}{next_move_hint}{progress_hint}{unmod_hint}{stats_hint}\n"
            f"以既定人格做出对你的目标最有利的选择.\n"
            f"在```json中按 turn schema 输出(见系统消息中的输出格式说明)."
        )
        return self._build_ctx(task, l3, l4, l2_summary, docs=docs_dossier)

    def build_vote_context(
        self,
        task: TaskSpec,
        visible_events: list[Event],
        directive_title: str,
        story_time: str,
        directive_body: str = "",
        l2_summary: str = "",
        docs_dossier: str = "",
    ) -> AgentContext:
        l3 = "\n".join(render(e) for e in visible_events) or "(无近期事件)"
        body_part = f"\n指令正文:\n{directive_body}" if directive_body else ""
        l4 = (
            f"故事时间: {story_time}\n"
            f"正在表决指令: {directive_title}{body_part}\n"
            f"以既定人格投票(公开唱票, 你的选择全场可见). 在```json中按 vote schema 输出."
        )
        return self._build_ctx(task, l3, l4, l2_summary, docs=docs_dossier)

    # --- 主持类任务(带*) ---

    async def presiding_next_speaker(
        self,
        task: TaskSpec,
        visible_events: list[Event],
        phase: str,
        story_time: str,
        spoken_seats: list[str],
        all_seat_ids: list[str],
        l2_summary: str = "",
    ) -> PresidingNextSpeaker:
        l3 = "\n".join(render(e) for e in visible_events) or "(无近期事件)"
        is_first_round = len(spoken_seats) == 0
        first_hint = (
            "\n这是开场第一轮, 你作为主持者可以先点自己发言, 也可以点别人先表态."
            if is_first_round
            else ""
        )
        l4 = (
            f"当前阶段: {phase}\n故事时间: {story_time}\n"
            f"你是本会场主持者({self.seat.name}). "
            f"会场席位(只能从中选择): {', '.join(all_seat_ids)}\n"
            f"本轮已发言: {', '.join(spoken_seats) or '无'}\n"
            f"以你的立场选择下一位发言者(可以偏心).{first_hint}\n"
            f"注意: seat 字段必须是上面列出的席位id之一, 不得编造不存在的角色.\n"
            f"announcement 是你当众说的**一两句程序性的话**(如'请XX发言'或'我想先听听XX的看法'), "
            f"不要在这里发表长篇立场发言——那是你自己的行动回合该做的事; 点自己时 announcement 留空. "
            f"在```json中输出: "
            '{"seat": "席位id(必须从列表中选)", "announcement": "一两句程序性的话", "inner_thought": "你的盘算"}'
        )
        ctx = self._build_ctx(task, l3, l4, l2_summary)
        result = await self.act(task, ctx, schema_model=PresidingNextSpeaker)
        if isinstance(result, PresidingNextSpeaker):
            return result
        # fallback: 保底轮询
        for sid in all_seat_ids:
            if sid not in spoken_seats:
                return PresidingNextSpeaker(seat=sid, announcement=f"请{sid}发言。")
        return PresidingNextSpeaker(seat=all_seat_ids[0], announcement="请继续。")

    async def presiding_motion_ruling(
        self,
        task: TaskSpec,
        visible_events: list[Event],
        motion_text: str,
        story_time: str,
        l2_summary: str = "",
    ) -> PresidingMotionRuling:
        l3 = "\n".join(render(e) for e in visible_events) or "(无近期事件)"
        l4 = (
            f"故事时间: {story_time}\n"
            f"你是本会场主持者({self.seat.name}).\n"
            f"收到动议: {motion_text}\n"
            f"以你的立场裁决(受理或驳回, 可以偏心). 在```json中输出: "
            '{"ruling": "accept|reject", "reason": "理由", "inner_thought": "你的盘算"}'
        )
        ctx = self._build_ctx(task, l3, l4, l2_summary)
        result = await self.act(task, ctx, schema_model=PresidingMotionRuling)
        if isinstance(result, PresidingMotionRuling):
            return result
        return PresidingMotionRuling(ruling="reject", reason="fallback")

    async def presiding_caucus_switch(
        self,
        task: TaskSpec,
        visible_events: list[Event],
        phase: str,
        story_time: str,
        l2_summary: str = "",
    ) -> PresidingCaucusSwitch:
        l3 = "\n".join(render(e) for e in visible_events) or "(无近期事件)"
        l4 = (
            f"当前阶段: {phase}\n故事时间: {story_time}\n"
            f"你是本会场主持者({self.seat.name}). "
            f"决定是否切换磋商形式(Mod⇄Unmod)或保持当前. 在```json中输出: "
            '{"action": "keep|switch", "to_phase": "ModeratedCaucus|UnmoderatedCaucus", '
            '"announcement": "宣布内容", "inner_thought": "你的盘算"}'
        )
        ctx = self._build_ctx(task, l3, l4, l2_summary)
        result = await self.act(task, ctx, schema_model=PresidingCaucusSwitch)
        if isinstance(result, PresidingCaucusSwitch):
            return result
        return PresidingCaucusSwitch(action="keep")
