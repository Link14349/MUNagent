# 04 - 会场状态机与回合调度

> 上级文档: [index.md](index.md) | 相关: [03-event-model.md](03-event-model.md), [05-agent-harness.md](05-agent-harness.md), [07-engine.md](07-engine.md)

## 1. 会场形态与生命周期

| 形态 | kind | 来源 | 生命周期 |
|---|---|---|---|
| 总会场 | main | 场景包定义 | 全程存在 |
| 分会场 | sub | 场景包定义 | 全程存在 |
| 临时会场 | temp | 运行时由主席创建(谈判/联席会议) | 主席宣布结束即解散 |

临时会场规则: 成员从原会场"借出", 原会场中该席位标记`离场`(不参与点名/分组/投票计数); 临时会场解散后归还. 一个席位同一时刻只在一个会场**在场**. 临时会场默认无投票权(谈判性质), 主席创建时可显式赋予决策规则(联席表决).

**交互边界**: 同会场在场席位间才能直接对话/表决; 跨会场只能经指令→DM→主席间接传达.

## 2. 双轨模型总览

```
前场轨(每会场一个状态机)          后场轨(全局一条流水线)
ModCaucus ⇄ UnmodCaucus          指令队列 → DM判定 → 主席处理
     ⇡ Voting(动议子流程)              ↑随时入队        ↓
     ⇡ CrisisUpdate(中断, 可抢占) ←──────────────── 播报决策
```

- 个人指令/危机笔记: 任何前场阶段随时递交(挂在代表的行动回合里), 直接入后场队列;
- 联合指令: 前场Voting通过后入同一队列;
- Crisis Update: 不是状态, 是中断事件, 可抢占前场任意阶段.

## 3. 前场状态机

### 状态与转移表

状态: `Opening`(开场) / `ModeratedCaucus` / `UnmoderatedCaucus` / `Suspended`(会场暂停, 如全员被借去临时会场) / `Adjourned`(闭会).

| 当前状态 | 触发 | 目标状态 |
|---|---|---|
| Opening | 主席宣布开始 | ModeratedCaucus |
| ModCaucus | 主席决策/动议通过"进入非正式磋商" | UnmodCaucus |
| UnmodCaucus | 小轮跑满/主席决策 | ModCaucus |
| Mod/Unmod | 动议表决某联合指令 | (Voting子流程, 完毕返回原状态) |
| 任意 | Crisis Update中断 | (播报完毕, 主席决定返回原状态或切换) |
| Mod/Unmod | 主席决策"议程结束"或满足manifest的end_conditions | Adjourned |
| 任意 | 全员借出到临时会场 | Suspended(归还后恢复原状态) |

### 戏内主持席(presiding seat)

真实历史委中, 会议程序往往由某个**代表角色**主持(政治局会议由赫鲁晓夫主持、国民议会有议长、内阁会议有总理)——主持人自己是有立场、有秘密目标的玩家, **程序性偏心是历史委的核心博弈维度之一**(不点政敌的名、快速表决盟友的动议、拖延不利议程).

因此把"主席"拆成两层:

| | 戏内主持席(presiding seat) | 戏外主席(主席团Chair) |
|---|---|---|
| 是谁 | `venues.yaml`可选字段`presiding_seat`指定的某代表席位 | 中立的ChairAgent |
| 管什么 | 会议程序: 点名(`next_speaker`)、动议裁决(`motion_ruling`)、宣布磋商形式切换、主持表决 | 游戏层: 时钟、Crisis Update播报、跨会场协调、临时会场、议程终结、预算熔断 |
| 立场 | 带人格卡/秘密目标/honesty行事, **允许偏心** | 中立, 不可下放给代表 |

规则:

- 未设`presiding_seat`(或该席位离场)的会场, 主持职能由中立ChairAgent行使——下文流程中的"主持者"即指"主持席, 无则中立主席";
- **引擎级公平地板不受主持席控制**: 保底轮询与阶段轮数上限由引擎硬性执行——主持席可以偏心, 但不能把任何代表彻底憋死或无限拖延;
- **申诉动议(appeal)**: 代表可动议"申诉主持裁决", 由戏外主席**终裁**(对应议事规则中的appeal机制), 产生venue事件——被偏心针对者的制度出口;
- **主持权可易手**: `presiding_seat`是venue运行时状态的一部分(RuntimeState, 见03§7), 可经指令判定/投票/政变在推演中变更, 产生`presiding_change`事件(venue scope). "罢免议长"是合法玩法;
- 主持席同时保有代表身份: 仍可发言、写指令、投票(主持任务与行动回合是不同task).

**席位状态(seat status)**: 每席位有`active/suspended/removed`三态. 叙事导致的资格变化(解职/被捕/死亡/复职)由DM在结果撰写中通过`seat_status_changes`显式声明, 引擎产生`seat_status_change`事件并执行——非active席位退出点名/保底轮询/Unmod分组/投票分母, 亦不再进入新事件的可见名单(离席); 主持席失活时主持权自动回落中立主席(`presiding_change`); 在席席位不足2时会议自动闭会. **叙事必须配合机制声明才生效**——DM只写"某某被解职"而不声明状态变化, 该角色会继续开会.

阶段切换: 戏内的磋商形式切换(Mod⇄Unmod)由主持者决定; 议程终结(Adjourned)、临时会场创建等游戏层切换仍由戏外主席决定(输入: 会场近期氛围摘要+待决动议+阶段预算余量; 输出schema见05). 人类导演可通过`human_control`事件强制切换, 优先级最高.

### ModeratedCaucus回合流程
1. 主持者点名: 从"举手席位+未发言席位"中选择下一位(输出`next_speaker`; 主持席行使时带戏内立场), 引擎附加**保底轮询**规则——连续K轮(默认K=会场人数)未发言的席位强制获得一次发言机会, 防饿死;
2. 被点名代表执行一次行动回合(可选动作: 发言/动议/写指令/pass, 见05的输出schema);
3. 动作产生对应事件; 若为动议, 主持者即刻裁决(受理→切磋商形式或进Voting; 驳回→继续; 若为appeal动议→交戏外主席终裁);
4. 每回合按`clock_rate.per_mod_speech`推进故事时钟.

### UnmoderatedCaucus: 小轮+屏障(决策D4)

```
def run_unmod(venue, rounds):                     # rounds默认4, 可配
    groups = initial_grouping(venue)              # ①
    for r in range(rounds):
        await gather(*[run_group_round(g) for g in groups])   # ②轮内并行
        moves = collect_next_moves(groups)        # ③
        groups = settle_barrier(venue, groups, moves)         # ④
    emit(phase_change → ModCaucus建议)             # 或主席决定续期
```

1. **初始分组**: 每代表输出磋商意愿(想找谁), 引擎按意愿聚类(互相点名优先, 落单者进最大意愿相近组或单独行动);
2. **轮内**: 各组并行推进一轮组内对话(每成员发言一次左右, asyncio并发). 轮内成员表冻结, 无竞态. 每轮按`clock_rate.per_unmod_round`推进时钟;
3. **去留决策**: 每代表本轮最后一次输出中附带`next_move: stay | join:<group_id> | new_group:[seats] | solo`, 零额外LLM调用;
4. **屏障结算** `settle_barrier`:
   - 按**固定席位顺序**(seat id字典序)逐一结算, 写`group_move`事件 → 确定性、可回放;
   - 目标组为**闭门**时: 引擎向发起人Agent发起一次轻量决策调用(放行/拒绝), 产生`group_join_request`/`group_join_decision`事件(组内+申请者可见); 拒绝则申请者留原组或solo;
   - 合流(多人转投同一目标)、消亡(空组)自然处理; 组数上限(默认: ⌈会场人数/2⌉), 超限的new_group请求降级为join;
   - `group_move`事件对全会场可见(看得见谁在串门), 组内对话内容仍是group scope.

**闭门小组**: `new_group`时发起人可置`closed: true`; 组内可见"有人想进来被拒"事件; 发起人离组后闭门标记随发起人资格转移给最早成员.

玩家模式下人类的换组/申请同样在屏障生效, 引擎逻辑不分叉.

### Voting子流程
1. 代表动议表决某联合指令(草稿已在会场传阅=一条venue事件); `motion_target`填**草案线编号**(如D1.2, 默认最新版), 见06§2;
2. 主持者受理 → `vote_call`事件, 冻结前场(主持席拒不受理时, 动议方可appeal至戏外主席);
3. **在场**席位依次投票(aye/nay/abstain; 借出到临时会场的"离场"席位不参与), 玩家席位走WS等待(超时按弃权);
4. **程序**按venue的`decision_rule`计票 → `vote_result`(含完整唱票). LLM只负责投票行为本身, 通过与否是纯程序逻辑;
5. 通过 → 指令入后场队列; 否决 → 指令进入`rejected`态(可修改后重提);
6. 返回被打断的阶段.

**计票规则明细**(模联/联合国惯例):

- **分母按"到会且投票"计**: 弃权不算入分母. 例: 8人在场, 3赞成/2反对/3弃权, majority通过(3/5);
- **全体弃权或无有效票**: 不通过;
- **平票**: 未达多数, 不通过(主席团中立, 不设破平票权);
- **veto语义**: veto席位投nay → 无论票数直接否决; veto席位**弃权不构成否决**(循安理会先例);
- **unanimous口径**: 到会且投票席位中无nay即通过, 弃权不阻止一致通过;
- **公开唱票**: `vote_cast`为venue scope, 全场可见谁投了什么——公开表态的政治压力是历史委博弈的一部分, 不做匿名表决.

## 4. Crisis Update中断流程

触发源: ①后场判定结果达到播报条件; ②危机弧线触发(引擎每次时钟推进后检查`crisis_arcs`的trigger, condition类交DM评估); ③私密指令酿成大事; ④主席节奏调控(僵局时抽随机事件池).

流程: 主席决定播报(内容可按会场定制、可延迟、可对某会场扣发) → 对目标会场发出中断 → 引擎在该会场**当前最小步结束后**(见07)插入`crisis_update`事件+推进时钟 → 主席决定返回原阶段或切换.

## 5. 推演时钟

- 每会场独立时钟读数, 但共享同一故事时间轴; 主席负责保持各会场时间大致同步(Crisis Update时对齐);
- 推进来源: 前场活动按`clock_rate`累加; 主席在Crisis Update/阶段切换时可显式跳时(`clock_advance`);
- 指令生效挂在时间轴上: DM判定时给出`takes_effect_at`(如"部队调动需12小时"), 时序冲突按生效时刻排序裁定(见06);
- 一切时钟变化都是`clock_advance`事件, 可回放;
- **危机更新后的主席跳时**: 每次Crisis Update播报后, 中立主席做`clock_decision`——对照G段中的时间线节点(见02 story-design.md/crisis_arcs.timeline)与局势决定推进到哪个时间点: 会场空转跳向下一个压力节点, 重大转折后小步推进(或不跳). 引擎程序校验: 只许向前、单次不超过最大步长(默认24h)、非法输出静默忽略; 生效即`clock_advance`事件(actor=chair, 带reason).

### 时区处理: 内部单一UTC轴 + 会场本地时区仅作渲染

多会场跨时区场景(古巴导弹危机: 1962年10月华盛顿UTC-4、莫斯科UTC+3, 差7小时)的处理原则:

- **内部一律UTC**: 引擎只有一条时间轴——事件`story_time`、`takes_effect_at`、弧线触发`at`、manifest起止时间加载时归一化为UTC(ISO带`Z`). 时序比较(生效排序/弧线触发/跨会场对齐)只在UTC轴上做;
- **会场声明时区**: `venues.yaml`每会场一个`timezone`字段(IANA名, 如`America/New_York`), 用Python `zoneinfo`转换——IANA历史数据自动处理1962年美国夏令时切换(10月28日)、莫斯科当年无夏令时等破事;
- **渲染规则**: 代表Agent的L4任务段与会场时间线UI只显示**本会场本地时间**(戏内真实感: 政治局委员想的是莫斯科时间); 主席团/上帝视角双显UTC+各会场本地; DM叙述中可自由穿插他地时间("此刻华盛顿为凌晨2时"). UTC→本地转换是确定性纯函数, 不破坏缓存纪律(11§4);
- **输入校验**: 场景包中人写的一切时间必须带时区偏移(`1962-10-27T10:00:00-04:00`)或显式`Z`, 加载时归一化为UTC; 裸时间串校验器直接报错(见02§5).

## 6. 阶段预算(防失控)

| 配置项 | 默认 | 说明 |
|---|---|---|
| `mod_max_speeches` | 12 | 单次ModCaucus最大发言数, 到达后强制主席做阶段决策 |
| `unmod_rounds` | 4 | 单次UnmodCaucus小轮数 |
| `session_max_tokens` | 2M | 会话token上限, 到达后自动暂停并通知 |
| `human_timeout_s` | 300 | 玩家回合等待超时, 超时AI代打或pass |
