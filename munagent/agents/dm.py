"""DM Agent 最小版: 判定流水线 ②④(LLM) + ③程序掷骰. 见 06§3."""

from __future__ import annotations

import hashlib
import random
from typing import Literal

from pydantic import BaseModel

from munagent.agents.base import AgentContext, BaseAgent, TaskSpec
from munagent.llm.client import LLMClient


class FeasibilityAssessment(BaseModel):
    probability_tier: int  # 90|70|50|30|10
    reasoning: str = ""
    takes_effect_at: str = ""
    visible_consequences: str = ""


class AdjudicationResult(BaseModel):
    narrative_full: str = ""
    stat_changes: list[dict] = []
    per_venue_visible: list[dict] = []
    author_private_result: str = ""
    suggest_broadcast: Literal["immediate", "delayed", "withhold"] = "immediate"
    seat_status_changes: list[dict] = []  # [{seat, to: active|suspended|removed, reason}] 叙事导致的席位资格变化


G_DM = """你是模拟联合国历史委员会危机联动推演的危机导演(DM). 职责:
- 评估代表提交的指令的可行性, 给出成功概率档位.
- 根据结果档位撰写事件结果叙述.

## 概率档位
90=稳操胜券, 70=占优, 50=五五开, 30=冒险, 10=异想天开.

## tags模式判定指引
- 己方相关标签"强"且对抗方"弱" → 上调一档
- 均势 → 50基准
- 行动与自身资源/权力高度匹配 → 上调
- 依赖多个不确定环节 → 下调

## 结果档位(掷骰后由程序判定, 你只需按档位写叙述)
- 大成功: 完全达成目标, 可能附带额外收益
- 成功: 达成目标
- 部分成功: 达成但有代价或妥协
- 失败: 未达成, 无严重后果
- 灾难性失败: 未达成且暴露/反噬

## 叙事文风(重要)
你决定的是**事态走向**, 不是写小说. 一切结果叙述用**新闻通讯社电讯体**——克制、客观、准确:
- 只写可核实的事实: 谁、何时、何地、发生了什么、规模多大. 数字、番号、地名要具体.
- **禁止**描写人物表情、语气、内心与气氛渲染("面色阴沉""厉声宣布""气氛降至冰点"一律不许出现). 事实自己会说话.
- **不得替会场内的代表编写台词、决定或行动**——他们如何反应由他们自己的回合决定. 你只写: 指令本身的执行后果, 以及**会场之外**的世界反应(部队动向、外国照会、媒体报道、议会动作、街头民情). 会场内人物只能作为后果的知情者被提及(如"该报告已送达总理办公室"), 不能被你安排说话或做事.
- 篇幅克制: narrative_full 一般不超过200字; per_venue_visible 更短, 只写该会场能观察到的现象.

## 席位资格变化(seat_status_changes)
若结果导致某席位**失去或恢复参会资格**(被捕/死亡/被外部机构罢免/复职等), 必须同时在 seat_status_changes 中声明, 否则不产生机制效果, 该角色仍会继续开会:
- 格式: [{"seat": "席位id", "to": "suspended|removed|active", "reason": "一句话缘由"}]
- suspended=停职(可复席), removed=除名/死亡(通常不可逆), active=复席.
- 资格变化必须来自**会场外部力量**(议会弹劾生效/军方拘押/司法逮捕)或指令作者自身行动的直接反噬——不得假手于某位在场代表的"当场决定"(那是他自己的回合该做的事).
- 仅在结果明确导致资格变化时使用, 不要作为普通惩罚滥用; 无变化时输出空数组.

## 判定通用做法
- 概率反映现实约束而非戏剧需要: 不因为行动"精彩"而上调, 不因为平淡而下调.
- 同类行动同标准: 对不同代表的相似行动给出一致的档位, 你的公信力来自一致性.
- 部分成功是最有戏的档位: 写清"达成了什么+付出了什么代价", 给后续博弈留钩子.
- 失败叙述要给信息: 让作者知道为什么失败(资源不足/时机不对/被反制), 而非单纯"没成功".
- 灾难性失败写暴露与反噬, 但不越权替代表做后续决定, 烂摊子留给代表自己收拾.
- 结果要为后续推演留空间: 避免一锤定音终结所有矛盾的叙述, 危机应当螺旋演进.
- per_venue_visible只写该会场能观察到的现象, 不泄露幕后原因与他方秘密行动.

在```json代码块中按指定 schema 输出.
"""


def build_dm_g(scenario) -> str:
    """组装 DM 的 G 段: 判定规则 + 背景文书全文 + 全席位权力清单.

    会话内字节级稳定(前缀缓存), 判定上下文(L4)只放动态内容(指令/stats/摘要).
    """
    parts = [G_DM.rstrip()]
    if scenario.background.strip():
        parts.append(f"## 背景文书\n\n{scenario.background.strip()}")
    roster = ["## 各席位权力清单(合法性检查依据)"]
    for seat in scenario.seats.values():
        roster.append(f"### {seat.name} (`{seat.id}`)")
        if seat.portfolio_powers:
            for pw in seat.portfolio_powers:
                limit = f" (限制: {pw.limits})" if pw.limits else ""
                roster.append(f"- {pw.power}{limit}")
        else:
            roster.append("- (未列明)")
    parts.append("\n".join(roster))
    return "\n\n".join(parts)


def roll_directive(master_seed: int, directive_id: str) -> tuple[int, int, int]:
    """掷骰: seed=sha256(master_seed, directive_id). 见 06§3, 决策 D6.

    返回 (seed_int, roll, margin=probability_tier - roll 之前不预知, 这里只返回 seed 和 roll).
    """
    h = hashlib.sha256(f"{master_seed}:{directive_id}".encode()).digest()
    seed_int = int.from_bytes(h[:8], "big")
    rng = random.Random(seed_int)
    roll = rng.randint(1, 100)
    return seed_int, roll, 0  # margin 由调用方算


def outcome_tier(margin: int, thresholds: dict | None = None) -> str:
    """margin -> 结果档位. 见 06§3."""
    t = thresholds or {"great": 40, "success": 10, "partial": 0, "fail": -20}
    if margin >= t["great"]:
        return "大成功"
    if margin >= t["success"]:
        return "成功"
    if margin >= t["partial"]:
        return "部分成功"
    if margin > t["fail"]:
        return "失败"
    return "灾难性失败"


class DMAgent(BaseAgent):
    def __init__(self, llm: LLMClient, master_seed: int, g_dm: str = G_DM) -> None:
        super().__init__(llm, max_tokens=8192)
        self.master_seed = master_seed
        self._g_dm = g_dm

    async def assess_feasibility(
        self,
        task: TaskSpec,
        directive_text: str,
        context_summary: str,
    ) -> FeasibilityAssessment:
        self._schema_model = FeasibilityAssessment
        l4 = (
            f"待判定指令:\n{directive_text}\n\n"
            f"当前局势:\n{context_summary}\n\n"
            f"评估成功概率档位(90/70/50/30/10). 在```json中输出: "
            '{"probability_tier": 70, "reasoning": "依据", '
            '"takes_effect_at": "<生效故事时刻: 基于当前故事时间推算, ISO格式UTC带Z>", '
            '"visible_consequences": "预期"}'
        )
        ctx = self.build_context(
            task, g=self._g_dm, l1="你是危机导演(DM).", l2="", l3="", l4=l4
        )
        result = await self.act(task, ctx)
        if isinstance(result, FeasibilityAssessment):
            return result
        return FeasibilityAssessment(probability_tier=50, reasoning="fallback")

    async def write_result(
        self,
        task: TaskSpec,
        directive_text: str,
        probability_tier: int,
        roll: int,
        outcome: str,
        context_summary: str,
    ) -> AdjudicationResult:
        self._schema_model = AdjudicationResult
        l4 = (
            f"指令:\n{directive_text}\n\n"
            f"概率档位: {probability_tier}%, 掷骰: {roll}, 结果: {outcome}\n"
            f"当前局势:\n{context_summary}\n\n"
            f"撰写结果叙述. 在```json中输出: "
            '{"narrative_full": "完整结果", "per_venue_visible": [{"venue":"cabinet","text":"可见版本"}], '
            '"author_private_result": "给作者的私密回执", "suggest_broadcast": "immediate", '
            '"seat_status_changes": []}'
        )
        ctx = self.build_context(
            task, g=self._g_dm, l1="你是危机导演(DM).", l2="", l3="", l4=l4
        )
        result = await self.act(task, ctx)
        if isinstance(result, AdjudicationResult):
            return result
        return AdjudicationResult(
            narrative_full=f"指令结果: {outcome}",
            per_venue_visible=[{"venue": "cabinet", "text": f"结果: {outcome}"}],
        )

    def roll(self, directive_id: str) -> tuple[int, int]:
        """程序掷骰, 可复现. 返回 (seed, roll)."""
        seed, roll, _ = roll_directive(self.master_seed, directive_id)
        return seed, roll
