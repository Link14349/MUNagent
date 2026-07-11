# 05 - Agent Harness: 基类循环、上下文与各Agent设计

> 上级文档: [index.md](index.md) | 相关: [03-event-model.md](03-event-model.md), [06-directives-adjudication.md](06-directives-adjudication.md), [08-config.md](08-config.md)

## 1. Agent基类循环(决策D9: 自研轻量循环)

所有Agent共享同一个执行骨架:

```python
class BaseAgent:
    role: str                     # delegate | chair | dm | recorder | designer → 模型路由键

    async def act(self, task: TaskSpec) -> Action:
        ctx = self.build_context(task)              # 五段组装, 见§2
        last_err = None
        for attempt in range(3):                    # 最多1次正常+2次修复
            raw = await llm.chat(route(self.role), ctx, err_hint=last_err)
            parsed = parse_json_block(raw, task.output_schema)   # pydantic校验
            if parsed.ok:
                return parsed.action
            last_err = parsed.error                 # 把校验错误回填给下一次调用
        return self.fallback(task)                  # 兜底, 按角色定义
```

- **结构化输出协议**: prompt要求模型在```json代码块中输出, 按task给定schema; 解析失败/校验失败时把错误信息作为修复提示重试;
- **fallback表**: 代表→`pass`(跳过本回合); 主席→维持当前阶段; DM→指令重新入队(计失败次数, 3次后暂停会话报错); 书记→跳过本次摘要(下次累积);
- 设计Agent例外: 其循环是**工具调用循环**(function calling多轮), 直到输出`finish`或达到工具调用上限(单步骤默认30次).

## 2. 上下文五段组装(代表Agent为例)

按**变化频率递增**排序, 服务于前缀缓存命中(设计动机与纪元机制详见[11-cost-and-caching.md](11-cost-and-caching.md)):

| 段 | 内容 | 来源 | token预算(flash 8k方案) |
|---|---|---|---|
| G 全局共享段 | 会议规则+四类指令格式+全部任务输出schema+背景文书摘要(**所有代表一字不差**, 跨Agent共享缓存) | 场景包+固定文案 | ~1.5k |
| L1 席位固定段 | 人格卡+席位公开/私密信息+权力清单 | 场景包 | ~1k |
| L2 纪元摘要段 | 会场公开记录摘要+本席位私人记忆摘要(本纪元冻结版) | 书记摘要(§4) | ~2k |
| L3 追加事件段 | 本纪元内该席位可见事件原文, 只追加不删除(含自己的speech_thought——记得自己的盘算) | `bus.query(viewer=seat)` | ~3k(纪元切换阈值) |
| L4 任务段 | 当前阶段+故事时间+本次任务+指定schema | 引擎TaskSpec | <0.5k |

主席团Agent同构, 区别在G(主席团规则版)与L1(职责说明+危机弧线)与查询视角. 易变信息(故事时间/阶段)只允许出现在L4; 事件渲染必须字节级确定(见11§4).

**诚信倾向注入**(决策D3): `persona.honesty`映射为L1中的指令性描述——

| honesty | prompt描述 |
|---|---|
| ≥0.8 | 你几乎从不说谎, 但可以选择沉默或回避 |
| 0.5~0.8 | 你可以策略性地隐瞒与误导, 但不会直接违背公开承诺 |
| 0.2~0.5 | 你可以为达成秘密目标而说谎、开空头支票 |
| <0.2 | 你毫无信义可言, 背刺与欺骗是你的常规手段 |

## 3. 各Agent的任务与输出schema

### 3.1 代表Agent(DelegateAgent)

| task | 触发 | 输出schema(要点) |
|---|---|---|
| `turn` | Mod点名/组内轮到发言 | `{action: speech\|motion\|write_directive\|pass, text, inner_thought, directive?, next_move?}` |
| `vote` | Voting子流程 | `{choice: aye\|nay\|abstain, inner_thought}` |
| `express_grouping` | Unmod开始 | `{want_to_talk_to: [seat_id], topic}` |
| `quick_decide` | 闭门小组收到加入申请 | `{decision: admit\|reject, reason}` |

- `next_move`仅Unmod小轮末尾要求输出: `{type: stay|join|new_group|solo, target?, members?, closed?}`;
- `directive`子对象格式见[06](06-directives-adjudication.md);
- `inner_thought`一律拆为伴生`speech_thought`事件(`scope=self`, 仅本席位可见, 见03§3): 其他代表与主席团Agent都读不到心; 本席位构建L3上下文时自动带回自己的历史内心盘算(按ref_seq与发言配对渲染), 保证欺骗行为的前后连贯.

### 3.2 主席Agent(ChairAgent)

| task | 输出schema(要点) |
|---|---|
| `phase_decision` | `{action: keep\|switch\|adjourn\|create_temp_venue, to_phase?, temp_venue_spec?, announcement}` |
| `next_speaker` | `{seat, reason}` (引擎叠加保底轮询) |
| `motion_ruling` | `{ruling: accept\|reject, reason}` |
| `broadcast_decision` | 收到DM结果后: `{plan: [{venue, text, delay_story_minutes}], withhold: [venue]}` — 每会场文本可不同、可延迟、可扣发 |
| `clock_decision` | `{advance_to, reason}` |

### 3.3 DM Agent
判定流水线见[06](06-directives-adjudication.md). 任务: `adjudicate`(五步流水线中的②可行性评估与④结果撰写两次LLM调用)、`arc_condition_check`(评估condition型弧线触发)、`random_pool_draw`建议.

### 3.4 书记Agent(RecorderAgent): 滚动摘要

- **分层**: 每会场维护venue公开摘要; 每席位维护私人记忆摘要(输入=仅该席位可见事件); 主席团另有dm-only全量摘要;
- **触发**: 由**纪元机制**驱动(见[11-cost-and-caching.md](11-cost-and-caching.md)§3)——某视角的L3追加段累积超过`epoch_l3_max_tokens`(默认3k)时切换纪元: 书记将L3压缩进新版摘要(旧摘要+新事件→新摘要), L3清空重积, 产出`summary_written`事件. 摘要更新与缓存失效绑定在同一时刻;
- **格式**: 按故事时间排列的编年体要点, 保留: 立场表态、承诺与背弃、指令及结果、投票结果; 丢弃: 寒暄与重复表态;
- 私人摘要技术上由recorder服务用flash模型代跑, 但输入严格限制为该席位可见事件, 不泄密.

### 3.5 设计Agent(DesignerAgent)
工具调用循环(web_search/fetch_page/download_file/pdf_to_markdown + 写场景包文件), 每个设计步骤(S1~S8)一个task, 输出为对应场景包文件的草稿+给用户的说明. 详见[02](02-scenario-design.md).

## 4. Prompt骨架示例(delegate `turn`)

```
[system]
你正在参加一场模拟联合国历史危机推演, 扮演: {name}({title}).
<人格卡>{persona; honesty映射描述}</人格卡>
<你的秘密信息>{private}</你的秘密信息>
<你的权力清单>{portfolio_powers}</你的权力清单>
<背景>{background摘要}</背景>
<指令格式说明>{四类指令说明}</指令格式说明>

[user]
<此前局势(书记摘要)>{L2}</此前局势>
<最近发生(原文)>{L3}</最近发生>
<当前阶段>{phase说明; 若为unmod末轮, 附next_move要求}</当前阶段>
现在轮到你行动. 以既定人格做出对你的目标最有利的选择, 在```json中按schema输出:
{output_schema}
```

## 5. 并发与用量

- 同一会话内, 不同小组/不同会场的Agent调用可并行(asyncio), 单个Agent的调用串行;
- 每次调用记录到`llm_usage`表(role/model/tokens/缓存命中tokens), 推演界面实时汇总并展示缓存命中率(见11§5);
- 模型路由: role→provider/model, 见[08-config.md](08-config.md). 建议delegate/recorder走flash, chair/dm/designer走pro.
