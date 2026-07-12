# Prompt 组装 API

代表/主席/书记等 Agent 的上下文按五段结构组装, 最终映射为 OpenAI 兼容的 `system` + `user` 两条消息. 详见设计 [11-cost-and-caching.md](../design/11-cost-and-caching.md)§2.

## 消息映射

`AgentContext.to_messages()` (`agents/base.py`):

| LLM 角色 | 来源段 |
|----------|--------|
| `system` | G + L1 |
| `user` | L2 + L3 + L4(包在 XML 风格标签内) |

```
system: {G}\n{L1}
user:
  <此前局势(书记摘要)>
  {L2}
  </此前局势>
  <当前有效文件(原文, 仅当前版本, 历史版本已隐藏)>   ← 仅 docs 非空时渲染
  {docs}
  </当前有效文件>
  <最近发生(原文)>
  {L3}
  </最近发生>
  <当前任务>
  {L4}
  </当前任务>
```

**当前有效文件区**(`Engine._docs_dossier(seat_id)`): 该席位可见的现行文件全文——已通过生效的文件 / 各草案线**当前版本**(历史版本隐藏, fork 对抗版并列显示) / 本人递交过的私密指令 / **本人收到的危机笔记**(仅送达成功的; 被截获的笔记收件人一无所知, 作者也不知被截). turn(Mod/Unmod) 与 vote 任务注入; 表决时投票人能看到全部竞争版本.

**纪律**: 易变信息只许在尾部(L4, 以及追加的 L3). G/L1 在会话内应字节级稳定以利前缀缓存.

---

## 代表 Agent (`DelegateAgent`)

### G 段 — `build_delegate_g_global(scenario, venue_id) -> str`

**全场所有代表共享同一份 G 段**, 由场景包在会话启动时组装一次, 传入各 `DelegateAgent`.

组成(按顺序):

1. **历史委通用惯例 + 会议通用规则** (`G_RULES`): 玩法定位(可偏离史实)/前后场分工/指令写作要领/博弈规范/扮演纪律/行动代价, 以及行动/动议/指令类型与 JSON 输出约定
2. **背景文书**: `background.md` **全文**, 不截断
3. **会场设置**: 会场名、议程、主持席(若有)
4. **会场席位**: 各席位公开信息
   - 头衔、派系、公开立场
   - 职权列表(含限制说明)
   - 主持席标注 `(本会场主持席)`

G 段还包含 **turn / vote 任务的输出 schema 说明**(高频任务 schema 进 G 一次缓存, L4 只引用"按 turn schema 输出"; 主持类低频任务 schema 仍在 L4). schema 文本与 pydantic 模型的一致性由 `tests/test_agents.py::test_g_rules_covers_all_output_schema_fields` 锁定.

**不在 G 段的内容**(仅该席位 L1): 秘密目标、人际关系、私有资源、诚信映射、带限制的权力清单.

```python
from munagent.agents.delegate import build_delegate_g_global
from munagent.core.scenario import load_scenario

sc = load_scenario("scenarios/cabinet-crisis")
g = build_delegate_g_global(sc, "cabinet")
```

### L1 段 — `DelegateAgent.build_l1()`

每席位固定, 会话内不变:

- 扮演身份: 姓名、头衔、派系
- `<人格卡>`: 性格、说话风格、决策倾向、诚信描述(`honesty` 映射)
- `<你的秘密信息>`: `private.secret_goals` + `private.relationships`(人际关系) + `private.resources`(私有资源)
- `<你的权力清单>`: 权力名称含限制文本(写指令时对照合法边界)

### L2 段 — 书记纪元摘要

- 引擎维护 `summaries["seat:<id>"]`
- 该席位 L3 累积超 `engine.epoch_l3_max_tokens` 时, `RecorderAgent` 压缩更新
- 未触发前为 `(暂无摘要)`
- **所有任务**(turn/vote/主持类)统一注入 L2

### L3 段 — 纪元内可见事件(只追加不截断)

来源: `EventBus.query(viewer, venue=...)` 后经 `Engine._epoch_slice(visible, viewer)` 过滤——只保留 **本纪元起点 seq 之后** 的事件, `render(event)` 全量逐条渲染, 不做"最近 N 条"滑动窗口(滑动窗口会让前缀每次调用都变化, 摧毁前缀缓存, 见设计 11§3).

- 纪元起点: `Engine._l3_start_seq[viewer]`, 在 `_check_epochs` 触发摘要压缩时推进
- 纪元内同一视角的 L3 前缀字节级稳定, 仅尾部追加新事件

Agent 上下文用 **UTC** 时间渲染(`timezone=None`). CLI 显示才转会场时区.

各席位可见范围: 会场/组公开事件 + **仅自己的** `speech_thought`(`scope=self`). 看不到他人内心盘算.

### L4 段 — 按任务类型

| task | 触发时机 | 要点 |
|------|----------|------|
| `turn` | 被点名行动 | 阶段、故事时间, 引用 G 段 turn schema. 主持席额外提示可偏心; Unmod 末轮附 next_move 要求(`require_next_move=True`); 附本场已提交指令数(`directives_submitted`, 为 0 时强化"共识要落成指令"); Unmod 中附"预期产出是指令文本"; 附该席位可见的 stats 当前值(`own_stats`, 行动成败判定依据) |
| `vote` | 表决轮 | 指令标题 + **指令正文**(引擎 `_directive_index` 提供) + 引用 G 段 vote schema |
| `next_speaker` | 主持席点名 | 可选席位列表、已发言列表、开场提示 |
| `motion_ruling` | 主持席裁决动议 | 动议文本 + accept/reject schema |
| `caucus_switch` | 主持席切换磋商 | keep/switch schema |

### Thinking 开关 (`llm/thinking.resolve_thinking`)

| 条件 | thinking |
|------|----------|
| `turn` + Mod | 开 |
| `turn` + Unmod + `scope=group` | 关 |
| 主持类任务 | 开 |
| `vote` | 开 |

### 构造入口

- `DelegateAgent(llm, seat, g_global)` — `g_global` 由引擎传入
- `build_turn_context(task, visible_events, phase, story_time, is_presiding, l2_summary, require_next_move, directives_submitted, own_stats, docs_dossier)` — `visible_events` 应为纪元过滤后的列表
- `build_vote_context(task, visible_events, directive_title, story_time, directive_body, l2_summary, docs_dossier)`
- `presiding_next_speaker` / `presiding_motion_ruling` / `presiding_caucus_switch` — async, 内部 `act()`, 均接受 `l2_summary`; 主持类任务的可见事件用**主持席自己的视角**查询(不用 chair 上帝视角, 防泄密)

---

## 书记 Agent (`RecorderAgent`)

G 段为固定 `G_RECORDER`; L1=`你是会议书记.`; L2/L3 为空.

两个任务(章节追加模型, 见设计05§3.4):
- `summarize_chapter`: L4 由 `build_chapter_prompt(new_events, level)` 生成——**只含本期事件, 不含旧摘要**(旧章节由程序拼接, LLM 无从丢失);
- `consolidate`: L4 由 `build_consolidate_prompt(chapters, level)` 生成——低频 squash, 强制覆盖全部时间范围.

引擎侧: `summaries[viewer]` = 章节拼接文本(消费端只读); `l2_chapters[viewer]` 为章节列表; 两者随 `summary_written` 事件(`kind: chapter|consolidated`)存档并在续推时回灌.

详见 [agents.md](agents.md) Recorder 小节.

---

## 主席 / DM Agent

主席的 G 段由 `build_chair_g(scenario)` 组装(职责 + 剧情走向设计 + 时间线节点); DM 的 G 段由 `build_dm_g(scenario)` 组装——**判定规则 + 背景文书全文 + 剧情走向设计 + 时间线节点 + 全席位权力清单**, 会话内字节级稳定(缓存友好). DM 判定的 L4 放动态内容: <当前故事时间>、指令全文、当前 stats 数值、dm 摘要.

`clock_decision`(主席): 每次危机更新后调用——L4 给当前时间/刚播报的更新/在途生效点, 主席对照 G 段时间线节点决定 `advance_to`(留空=不跳); 引擎 `_validate_clock_advance` 程序校验(只向前、默认≤24h), 生效即 `clock_advance` 事件(带 reason).

当前主席/DM 的 L2 摘要**已生成但未接入**其 context 构建(DM 摘要经 `_adjudicate` 的 context_summary 传入 L4).

`phase_decision` 接受 `directives_submitted`: 为 0 时 L4 追加**公开催办**职责提示(点名请代表把共识落成联合指令); `action=keep` 且 announcement 非空时, 引擎将 announcement 作为 chair 的 venue 级 speech 事件播报——催办由此对全场可见.

---

## 三人内阁示例 G 段结构

```
{G_RULES}

## 背景文书

{background.md 全文}

## 会场设置
- 会场: 内阁会议室 (`cabinet`)
- 议程: 讨论对边境危机的应对方案
- 主持席: 总理 (`premier`), 由该席位代表主持戏内程序

## 会场席位
### 总理 (`premier`) (本会场主持席)
- 头衔: 内阁总理
- 派系: 温和派
- 公开立场: 主张外交途径化解边境危机
- 职权:
  - 召集内阁会议并设定议程 (限制: 不能单方面罢免部长)
  - 发布政府公开声明 (限制: 需经内阁简单多数同意)

### 国防部长 (`defense_minister`)
...

### 外交部长 (`foreign_minister`)
...
```

各席位 L1 在此基础上追加私密人格卡与秘密目标.
