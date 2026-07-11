# 06 - 指令系统与判定机制

> 上级文档: [index.md](index.md) | 相关: [04-state-machine.md](04-state-machine.md), [05-agent-harness.md](05-agent-harness.md)

## 1. 指令四类型

| 类型 | 代码名 | 需投票 | 提交scope | 说明 |
|---|---|---|---|---|
| 联合指令 | `directive` | 是(会场decision_rule) | venue | 会场集体行动指令, 格式自由, 重可执行性 |
| 个人指令 | `personal` | 否 | private | 凭portfolio_powers的个人行动, 私下递交 |
| 公报/声明 | `communique` | **是**(一律需投票, 决策D14) | 判定后global | 对外官方表态, 一般无需判定成败, 但DM评估各方反应 |
| 危机笔记 | `crisis_note` | 否 | private | 给幕后/其他角色的私信; 送达本身可被DM判定(截获风险) |

### 指令数据结构
```python
class Directive(BaseModel):
    id: str
    kind: str                  # directive | personal | communique | crisis_note
    author: str                # seat_id; 联合指令为发起席位, 附co_sponsors
    co_sponsors: list[str]
    venue_id: str
    title: str
    body: str                  # 自由文本, 强调可执行步骤
    uses_powers: list[str]     # 声称动用的权力(个人指令必填)
    recipient: str | None      # crisis_note收件人(席位/幕后角色)
    status: str                # 生命周期, 见§2
```

## 2. 指令生命周期

```
draft → submitted → [voting → passed | rejected]   # 仅需投票的类型走中括号段
      passed/submitted → queued → adjudicating → resolved → announced | withheld
```

每次状态变化产生`directive_status`事件. `rejected`可修改后重新提交(新id, 链接旧id). `withheld`(扣发)状态下结果已生效但未播报, 主席可后续补播.

## 3. DM判定流水线(五步)

```
① 合法性检查(程序+LLM) → ② 可行性评估(LLM) → ③ 掷骰(程序) → ④ 结果撰写(LLM) → ⑤ 上报主席
```

### ① 合法性检查
- 程序层: 投票类指令是否真的通过(核对vote_result事件); 提交者是否在场;
- LLM层: `uses_powers`是否落在portfolio_powers内、是否与会场权限矛盾. 越权→直接`rejected`并附理由(private回执给作者).

### ② 可行性评估
DM输入: 指令全文+当前局势摘要+相关stats(tags或数值)+已生效的在途行动. 输出schema:

```json
{
  "probability_tier": 90,        // 90|70|50|30|10 五档
  "reasoning": "...",            // 依据: 实力对比/时机/在途冲突
  "takes_effect_at": "1962-10-27T22:00:00",   // 生效故事时刻
  "visible_consequences": "预期各方可观察到什么"
}
```

tags模式(决策D2)下给DM的对照指引: 己方相关标签"强"且对抗方"弱"→上调一档; 均势→50基准; 行动与自身资源/权力高度匹配→上调; 依赖多个不确定环节→下调. numeric模式则给出差值→档位映射表.

### ③ 掷骰(程序, 决策D6)
```
seed = sha256(session.master_seed, directive.id)   # 可复现
roll = rng(seed).randint(1, 100)
margin = probability_tier - roll
结果档位:  margin ≥ 40        → 大成功
          10 ≤ margin < 40   → 成功
          0 ≤ margin < 10    → 部分成功(达成但有代价)
          -20 < margin < 0   → 失败
          margin ≤ -20       → 灾难性失败(暴露/反噬)
```
`seed`与`roll`记入`adjudication`事件的rng字段. 低概率行动天然摸不到"大成功"档, 抑制无脑梭哈; 阈值可在配置中调.

原则: **LLM评概率+写叙述, 程序掷骰子**——避免LLM既当运动员又当裁判, 叙事偏好导致戏剧性行动总能成功.

### ④ 结果撰写
DM按结果档位撰写叙述, 输出schema:
```json
{
  "narrative_full": "完整结果(dm-only)",
  "stat_changes": [{"entity": "...", "field": "...", "to": "..."}],
  "per_venue_visible": [{"venue": "...", "text": "该会场能观察到的版本"}],
  "author_private_result": "给指令作者的私密回执(个人指令/危机笔记)",
  "suggest_broadcast": "immediate | delayed | withhold"
}
```

### ⑤ 上报主席
主席做`broadcast_decision`(见05): 每会场文本可不同、可延迟、可扣发; 交书记记录; 需要时触发Crisis Update.

## 4. 时序冲突裁定

后场队列按提交顺序判定, 但**生效**按`takes_effect_at`排在故事时间轴上. 若后判定的指令生效时刻早于已判定未生效的指令且互相冲突(如争夺同一部队), DM对冲突集合做一次**对抗性复判**: 双方概率档位对冲(高者减低者, 落到相近档位后各自掷骰), 叙述中写明先后手. 已播报的结果不回滚——DM只能用后续事件圆场(与真实危机联动一致).

## 5. 跨会场交互与危机笔记送达

- 跨会场一切交互走指令→DM→主席链路; 面对面谈判由主席开临时会场(见04);
- `crisis_note`送达判定: 默认成功送达; DM可对敏感收件人/紧张局势判定"截获"(走同一掷骰流水线, 概率档位依据双方情报能力tags), 截获产生给第三方的private事件——这是玩家间猜疑链的主要来源, 设计上鼓励DM低频使用.

## 6. 公报(Communiqué)特例
公报一般不判成败(发出去就是发出去了), DM的工作是评估**各方反应**并把反应写进后续Crisis Update; 但"假旗公报"、冒名公报等骚操作仍走完整判定流水线(可能被识破).
