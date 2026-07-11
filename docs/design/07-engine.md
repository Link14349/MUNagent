# 07 - 推演引擎(运行时Harness)

> 上级文档: [index.md](index.md) | 相关: [03-event-model.md](03-event-model.md), [04-state-machine.md](04-state-machine.md), [05-agent-harness.md](05-agent-harness.md)

引擎是把状态机、事件总线、各Agent接起来的运行时harness: 负责并发调度、中断分发、人类挂点、暂停/续推、预算熔断.

## 1. 运行模型(asyncio)

一次推演会话 = 一组协程:

```
Engine.run(session)
├── venue_loop(v)  × 每个活跃会场      # 前场轨
├── backroom_loop()                    # 后场轨: 指令队列消费者(DM流水线)
├── interrupt_loop()                   # 弧线触发检查 + Crisis Update分发
└── budget_watch()                     # token/费用/轮数熔断
```

```python
async def venue_loop(v):
    while v.phase != Adjourned:
        await pause_gate.wait()                  # 全局暂停闸
        if itr := interrupts.pop(v):             # 中断优先
            await play_crisis_update(v, itr)     # 播报+主席决定去向
            continue
        await step(v)                            # 执行一个"最小步", 见§2
        if phase_budget_exceeded(v):
            await chair.act(PhaseDecision(v))

async def backroom_loop():
    while session.running:
        d = await directive_queue.get()          # 随时入队(见04双轨)
        result = await dm_pipeline(d)            # 06的五步流水线
        await chair.act(BroadcastDecision(result))  # 可能向interrupts投递中断

async def interrupt_loop():
    on_event(clock_advance):                     # 每次时钟推进后
        for arc in due_arcs(clock): interrupts.push(arc)     # story_time型
        for arc in condition_arcs: 
            if await dm.act(ArcConditionCheck(arc)): interrupts.push(arc)
```

## 2. 最小步(step): 调度粒度与安全点

**最小步**是引擎的原子调度单位, 也是暂停/存档/中断插入的**安全点**——最小步执行中不接受中断, 结束后统一检查.

| 阶段 | 一个最小步 |
|---|---|
| ModCaucus | 主席点名 + 该代表一个行动回合(含动议裁决) |
| UnmodCaucus | 一个小轮(各组并行) + 屏障结算 |
| Voting | 完整一次表决(冻结前场, 不可中断) |
| CrisisUpdate | 一次播报 + 主席去向决策 |

断点续推(见03§7)从"上一个完成的最小步之后"恢复: reducer重建状态时, 未完成最小步产生的孤儿事件不存在——因为**事件在最小步完成时才批量提交**(SQLite事务包裹一个最小步).

## 3. 并发与一致性规则

1. 事件`emit`经单写者串行化 → seq全序(见03§5);
2. 会场间并行、Unmod组间并行、单Agent内串行;
3. 后场与前场并行, 但后场产生的中断只在前场安全点生效;
4. 跨会场共享状态(stats、时钟对齐)只允许在backroom/interrupt协程中修改, venue_loop只读 → 免锁.

## 4. 人类参与挂点

三种模式(观察/导演/玩家)统一为一个抽象: **ActionProvider**.

```python
class ActionProvider:                 # 每个席位/主席团角色绑定一个
    async def act(self, task) -> Action

AIProvider(agent)                     # 调Agent
HumanProvider(ws, timeout, fallback)  # 经WS发action_request, 等人类提交
    # 超时策略: fallback = ai_delegate(AI代打) | pass
HybridProvider                        # 导演模式: AI起草 → 人类审改 → 发出
```

- 引擎对"这个席位是人还是AI"无感知, 逻辑零分叉(与04中"人类换组也在屏障生效"一致);
- 导演干预(强切阶段/注入事件/修改判定)以`human_control`事件插入, 在安全点消费, 优先级高于主席Agent决策;
- 观察模式支持**步进控制**: `run | pause | step`(单步=执行一个最小步), 方便边看边学.

## 5. 预算与熔断

| 监控项 | 动作 |
|---|---|
| 阶段轮数上限(04§6) | 强制主席做阶段决策 |
| 会话token上限 | 自动暂停 + 前端告警, 用户确认后可续 |
| 单Agent连续失败3次 | 暂停会话, 报错定位到具体Agent与task |
| LLM接口5xx/超时 | 指数退避重试3次, 然后按上行处理 |

## 6. 错误处理与可观测性

- 每次LLM调用的(role, task, prompt摘要hash, tokens, 时延)入`llm_usage`表; 完整prompt/response在debug模式下另存本地文件(默认关, 含私密信息);
- 事件写入失败 = 致命错误, 中止会话(宁可停也不产生状态与日志不一致);
- 结构化输出解析失败率是核心健康指标, 复盘页展示per-role统计——持续偏高说明prompt或schema需要修.

## 7. 会话生命周期

```
create(scenario, config) → running ⇄ paused → ended
```
- `create`: 校验场景包 → 生成master_seed → 写sessions表 → 初始化各venue状态机(initial_phase) → Opening;
- `ended`: 满足end_conditions(主席在每次Crisis Update后评估) / 用户手动结束 / 熔断后放弃;
- 结束后会话只读, 进入复盘(见[09-gui.md](09-gui.md)).
