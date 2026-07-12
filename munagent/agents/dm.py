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

在```json代码块中按指定 schema 输出.
"""


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
    def __init__(self, llm: LLMClient, master_seed: int) -> None:
        super().__init__(llm, max_tokens=8192)
        self.master_seed = master_seed

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
            '"takes_effect_at": "2026-03-15T10:00:00+08:00", "visible_consequences": "预期"}'
        )
        ctx = self.build_context(
            task, g=G_DM, l1="你是危机导演(DM).", l2="", l3="", l4=l4
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
            '"author_private_result": "给作者的私密回执", "suggest_broadcast": "immediate"}'
        )
        ctx = self.build_context(
            task, g=G_DM, l1="你是危机导演(DM).", l2="", l3="", l4=l4
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
