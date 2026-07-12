# agents 模块 API

Prompt 五段结构与代表 G 段组装详见 [prompts.md](prompts.md).

## `agents.base.BaseAgent`
- `act(task, context) -> Any`: Agent 循环(组装→调 LLM→解析→修复重试→fallback)
- `build_context(task, *, g, l1, l2, l3, l4) -> AgentContext`: 五段上下文
- `parse_json_block(raw, schema_model) -> (parsed | None, error | None)`: JSON 提取与校验; 解析前 `normalize_json_delimiter_quotes` 修正弯引号边界

## `agents.delegate.build_delegate_g_global(scenario, venue_id) -> str`
- 组装代表 G 段: 规则 + 完整背景文书 + 会场设置 + 各席位公开简介与职权
- 全场代表共享, 引擎启动时调用一次

## `agents.delegate.DelegateAgent(llm, seat, g_global)`
- `build_l1() -> str`: 人格卡 + 秘密目标 + 权力清单(无背景)
- `build_turn_context(...) -> AgentContext`
- `build_vote_context(...) -> AgentContext`
- `presiding_next_speaker` / `presiding_motion_ruling` / `presiding_caucus_switch`: 主持席任务
- 输出 schema: `DelegateTurnAction(action, text, inner_thought, directive?)`

## `agents.chair.ChairAgent(llm, venue_id, seat_ids)`
- `next_speaker(...) -> NextSpeakerAction`
- `phase_decision(...) -> PhaseDecisionAction`
- `broadcast_decision(...) -> BroadcastDecisionAction`

## `agents.dm.DMAgent(llm, master_seed)`
- `assess_feasibility(...) -> FeasibilityAssessment`: 步骤②
- `write_result(...) -> AdjudicationResult`: 步骤④. 结果含 `seat_status_changes`([{seat, to, reason}]) — 叙事导致的席位资格变化(解职/被捕/死亡/复职), 引擎据此发 `seat_status_change` 事件并执行; **叙事不配合此声明则无机制效果**
- `roll(directive_id) -> (seed, roll)`: 步骤③ 程序掷骰, 可复现
- `outcome_tier(margin) -> str`: 结果档位(大成功/成功/部分成功/失败/灾难性失败)

## `agents.recorder.RecorderAgent(llm)`
章节追加模型(见设计 05§3.4): 每纪元摘一章追加, 低频 squash 合并; 旧 `summarize`(滚动重写)已移除.
- `summarize_chapter(task, new_events, level) -> str`: 本期新事件 → 一章摘要(不含旧摘要, 旧章节由程序拼接)
- `consolidate(task, chapters, level) -> str`: 全部章节压成一章, 强制覆盖全部时间范围; 失败时回退为章节拼接
- `build_chapter_prompt(new_events, level)` / `build_consolidate_prompt(chapters, level)`: L4 组装(前者含输入预算裁剪)
- `max_tokens=16384`; 输入预算见模块常量 `SUMMARIZE_MAX_INPUT_TOKENS`
