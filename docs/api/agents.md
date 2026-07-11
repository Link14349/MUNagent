# agents 模块 API

## `agents.base.BaseAgent`
- `act(task, context) -> Any`: Agent 循环(组装→调 LLM→解析→修复重试→fallback)
- `build_context(task, *, g, l1, l2, l3, l4) -> AgentContext`: 五段上下文
- `parse_json_block(raw, schema_model) -> (parsed | None, error | None)`: JSON 提取与校验

## `agents.delegate.DelegateAgent(llm, seat, background_summary)`
- `build_turn_context(task, visible_events, phase, story_time) -> AgentContext`
- 输出 schema: `DelegateTurnAction(action, text, inner_thought, directive?)`

## `agents.chair.ChairAgent(llm, venue_id, seat_ids)`
- `next_speaker(...) -> NextSpeakerAction`
- `phase_decision(...) -> PhaseDecisionAction`
- `broadcast_decision(...) -> BroadcastDecisionAction`

## `agents.dm.DMAgent(llm, master_seed)`
- `assess_feasibility(...) -> FeasibilityAssessment`: 步骤②
- `write_result(...) -> AdjudicationResult`: 步骤④
- `roll(directive_id) -> (seed, roll)`: 步骤③ 程序掷骰, 可复现
- `outcome_tier(margin) -> str`: 结果档位(大成功/成功/部分成功/失败/灾难性失败)
