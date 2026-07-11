# 03 - 事件模型、可见性与存档

> 上级文档: [index.md](index.md) | 相关: [04-state-machine.md](04-state-machine.md), [07-engine.md](07-engine.md)

## 1. 设计原则

1. **一切皆事件**: 发言、动议、投票、指令、判定、阶段切换、换组、时钟推进、人类干预——全部是带scope的事件, append-only写入事件日志;
2. **事件日志即存档**(决策D7): 存档/回放/断点续推/复盘导出全部基于事件日志(事件溯源). 运行时状态 = reduce(全部事件);
3. **可见名单在发出时物化**: 非global事件在emit时计算并固化`visible_to`, 之后成员变动不影响历史事件的可见性——这天然实现了"中途加入小组者看不到之前的聊天";
4. **回放不重调LLM**: LLM的输出(发言内容、判定叙述)本身记录在事件里, 回放只是重放事件流.

## 2. Event schema

```python
class Event(BaseModel):
    id: int                # 全局自增(SQLite rowid)
    session_id: str
    seq: int               # 会话内严格递增序号, 全序
    story_time: str | None # 故事内时间(ISO), 部分控制类事件为空
    real_time: str         # 真实时间(ISO)
    type: str              # 见事件类型表
    actor: str             # seat:<id> | chair | dm | recorder | system | human
    venue_id: str | None
    group_id: str | None   # 非正式磋商小组事件
    scope: str             # global | venue | group | private | dm-only | self
    visible_to: list[str] | None  # scope∈{venue,group,private}时物化的席位列表
    payload: dict          # 按type定义, 见下
    rng: dict | None       # 判定类事件: {seed, rolls:[...]}
```

## 3. 事件类型表

| type | 产生者 | 默认scope | payload要点 |
|---|---|---|---|
| `speech` | 代表 | venue/group | text(仅公开发言, 不含内心动机) |
| `speech_thought` | 代表 | self | thought, ref_seq(指向所属speech事件) |
| `motion` | 代表 | venue | motion_type(切阶段/表决指令/组临时会场), target |
| `phase_change` | 主席 | venue | from, to, reason |
| `vote_call` / `vote_cast` / `vote_result` | 主席/代表/系统 | venue | directive_id, choice, tally |
| `directive_submitted` | 代表 | private(个人)/venue(联合) | directive全文, kind |
| `directive_status` | 系统 | 同指令 | 生命周期状态变化 |
| `adjudication` | DM | dm-only | 概率档位, roll, 结果档位, 完整结果叙述 |
| `crisis_update` | 主席 | global/venue | text(可按会场定制), source_directive_ids |
| `group_formed` / `group_dissolved` | 系统 | venue | members |
| `group_move` | 系统 | venue* | seat, from_group, to_group (*会场内可见谁在串门, 但组内谈话内容不可见) |
| `group_join_request` / `group_join_decision` | 系统/发起人 | group+申请者 | seat, decision |
| `clock_advance` | 主席/系统 | venue | from, to |
| `summary_written` | 书记 | 同源层级 | level, text, covers_seq_range |
| `note_delivered` | 系统 | private | 危机笔记送达(内容在directive_submitted中) |
| `human_control` | human | dm-only | 干预内容(强切阶段/注入事件/审改草稿) |
| `session_control` | system | dm-only | start/pause/resume/end, 预算告警 |

**内心动机的处理**: 代表结构化输出中的`inner_thought`不放进`speech`事件本体, 而是拆成一条伴生的`speech_thought`事件(`scope=self`, `visible_to=[本席位]`, payload只含thought与ref_seq, 不重复发言文本). 效果: 其他代表与主席团Agent查询时都命中不了它(不读心); 代表本人查询时A/B两条都命中, 引擎按ref_seq配对渲染为「你发言: …(你当时的盘算: …)」喂回其上下文, 保证Agent记得自己在演什么局; 复盘"上帝视角"(人类, 戏外)仍可见.

## 4. 可见性规则

viewer(某席位)可见的事件集合:

```
scope=global                         → 可见
scope∈{venue, group, private, self}  → viewer ∈ visible_to
scope=dm-only                        → 仅主席团/上帝视角
```

- `visible_to`物化规则: venue事件=发出时刻该会场在场席位; group事件=发出时刻组内成员; private事件=显式指定(如危机笔记的收件人+主席团); self事件=仅行为者本席位;
- 主席团(chair/dm/recorder)可见**除self外**的一切(DM不读心, 判定依据是代表主动写出的指令与危机笔记); 复盘"上帝视角"(给人类的戏外观察)可见一切, 含self;
- Agent构建上下文、前端按视角订阅, 都走同一个过滤函数: `bus.query(viewer, filters) `. **过滤必须在服务端做**, 前端永远只收到过滤后的事件.

## 5. 事件总线API

```python
class EventBus:
    def emit(self, e: Event) -> Event         # 补全seq, 物化visible_to, 落库, 推给订阅者
    def query(self, viewer: str, *,           # viewer="god"为上帝视角
              venue: str = None, group: str = None,
              types: list[str] = None,
              since_seq: int = None, limit: int = None) -> list[Event]
    def subscribe(self, viewer: str, callback) # WS推送用; 引擎内部组件也可订阅
```

同一会话内`emit`串行化(asyncio单写者), 保证seq全序——这是回放确定性的基础.

## 6. 持久化(SQLite)

```sql
CREATE TABLE sessions (
  id TEXT PRIMARY KEY, scenario_id TEXT, created TEXT,
  config TEXT,          -- JSON: 参与模式/模型路由快照/预算
  master_seed INTEGER,  -- 判定RNG的根种子(见06)
  status TEXT           -- running | paused | ended
);
CREATE TABLE events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL, seq INTEGER NOT NULL,
  story_time TEXT, real_time TEXT NOT NULL,
  type TEXT NOT NULL, actor TEXT NOT NULL,
  venue_id TEXT, group_id TEXT,
  scope TEXT NOT NULL, visible_to TEXT,  -- JSON数组
  payload TEXT NOT NULL, rng TEXT,
  UNIQUE(session_id, seq)
);
CREATE INDEX idx_events_query ON events(session_id, venue_id, type, seq);
CREATE TABLE scenarios (id TEXT PRIMARY KEY, path TEXT, manifest TEXT);
```

token用量记录在独立表`llm_usage(session_id, role, model, prompt_tokens, completion_tokens, cache_hit_tokens, cache_miss_tokens, real_time)`, 不进事件日志. 缓存命中列供命中率监控(见[11-cost-and-caching.md](11-cost-and-caching.md)§5).

## 7. 回放、断点续推与导出

- **回放**: 只读, 按seq顺序重放事件流+视角过滤, 支持跳转到任意seq. 不涉及LLM;
- **断点续推**: 加载会话 → 用reducer从事件流重建运行时状态(各会场阶段、组结构、指令队列、时钟、数值) → 引擎从安全点(见07"最小步")继续. 要求: 一切运行时状态必须可由事件推导, **禁止**引擎持有不落事件的隐藏状态;
- **导出**: 复盘页可导出markdown会议记录 = 按视角过滤后的事件流 + 书记摘要渲染;
- **脱敏纪律**: api key及任何配置严禁进入事件日志(见[08-config.md](08-config.md)安全红线); LLM报错文本落日志前脱敏.
