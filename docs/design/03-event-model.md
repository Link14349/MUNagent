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
    story_time: str | None # 故事内时间(ISO, 统一UTC存储, 显示时按会场时区转换, 见04§5)
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
    def stage(self, e: Event) -> Event        # 最小步内: 补全seq, 物化visible_to, 写入步缓冲(不落库)
    def commit_step(self) -> list[Event]      # 最小步结束: SQLite事务批量落库, 推给订阅者, 清空缓冲
    def rollback_step(self) -> None            # 最小步失败/中止: 丢弃步缓冲(不产生孤儿事件)
    def query(self, viewer: str, *,           # viewer="god"为上帝视角; 含已commit+当前步缓冲
              venue: str = None, group: str = None,
              types: list[str] = None,
              since_seq: int = None, limit: int = None) -> list[Event]
    def subscribe(self, viewer: str, callback) # WS推送用; 仅推送commit后的事件
```

同一会话内`stage`/`commit_step`经单写者串行化(asyncio单写者), 保证seq全序——这是回放确定性的基础. **决策D12**: 最小步执行中事件只进内存缓冲; 步成功结束时`commit_step`一次性落库; 步失败则`rollback_step`, 保证断点续推无孤儿事件(见07§2). 为简洁, 引擎内部可继续用`emit`作为`stage`的别名, 但对外语义是"暂存而非即时持久化".

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

token用量记录在独立表`llm_usage(session_id, role, model, prompt_tokens, completion_tokens, cache_hit_tokens, cache_miss_tokens, thinking_enabled, real_time)`, 不进事件日志. 缓存命中列供命中率监控(见[11-cost-and-caching.md](11-cost-and-caching.md)§5).

## 7. Reducer与RuntimeState

事件日志有两类"读历史"消费者, 不要混:

- **回放(replay)**: 按seq顺序+视角过滤展示给人看, 只读, 不需要知道"现在处于哪个阶段"——P1即可用;
- **续推(resume)**: 进程重启后引擎要还原内存状态接着跑——需要**reducer**, P2交付.

### Reducer定义
纯函数, 把已提交事件流折叠为运行时状态, 放在`core/reducer.py`:

```python
def reduce(events: Iterable[Event]) -> RuntimeState   # 全量折叠
def apply(state: RuntimeState, e: Event) -> RuntimeState  # 单事件递推, reduce=fold(apply)
```

引擎运行时**在线维护**同一个RuntimeState(每次commit_step后对新事件调apply), 续推时用reduce重建——两条路径共用apply, 保证"跑出来的状态"和"重建的状态"必然一致.

### RuntimeState结构(草案)

```python
class GroupState(BaseModel):
    id: str; members: list[str]; closed: bool; founder: str

class VoteState(BaseModel):
    directive_id: str
    cast: dict[str, str]            # seat -> aye|nay|abstain

class VenueState(BaseModel):
    id: str
    kind: str                       # main|sub|temp
    parent_return: dict | None      # temp会场: 解散后各席位归还去向
    phase: str                      # Opening|ModCaucus|UnmodCaucus|Suspended|Adjourned
    interrupted_phase: str | None   # Voting/CrisisUpdate结束后要返回的阶段
    present_seats: list[str]        # 在场席位(被借出的不在)
    agenda: str
    groups: list[GroupState]        # 仅UnmodCaucus期间非空
    unmod_round: int
    mod_speech_count: int           # 阶段预算计数
    story_time: str                 # 该会场时钟读数(UTC)
    active_vote: VoteState | None

class EpochState(BaseModel):        # 每视角一份, 供上下文组装(05§2/11§3)
    summary_seq: int                # 当前L2摘要对应的summary_written事件seq
    l3_start_seq: int               # L3追加段起点

class RuntimeState(BaseModel):
    session_id: str
    last_seq: int                   # 已折叠到的事件seq
    venues: dict[str, VenueState]
    directives: dict[str, str]      # directive_id -> 生命周期状态(06§2)
    backroom_queue: list[str]       # 待判定directive_id, 保序
    pending_interrupts: list[dict]  # 已触发未播报的中断(弧线/判定结果)
    fired_arcs: list[str]           # 已触发弧线id
    stats: dict[str, dict]          # entity_id -> 当前tags/values
    epochs: dict[str, EpochState]   # viewer -> 纪元状态
```

### 事件→状态折叠映射

| 事件type | apply的状态变更 |
|---|---|
| `phase_change` | venue.phase更新, 阶段计数器清零; 进/出Unmod时初始化/清空groups |
| `speech` | mod_speech_count+1(Mod期间) |
| `speech_thought`/`motion` | 无状态变更(动议后果由主席的后续事件承载) |
| `vote_call` | 创建active_vote, 记录interrupted_phase |
| `vote_cast` | active_vote.cast[seat]=choice |
| `vote_result` | 清active_vote; directives[id]→passed/rejected; passed追加backroom_queue |
| `directive_submitted` | directives新增; personal/crisis_note直接入backroom_queue |
| `directive_status` | 状态推进(queued/adjudicating/resolved/announced/withheld); resolved时出队 |
| `adjudication` | 按payload.stat_changes更新stats |
| `crisis_update` | pending_interrupts移除对应项; fired_arcs追加(弧线来源时) |
| `group_formed/move/dissolved`, `group_join_*` | groups增删改 |
| `clock_advance` | venue.story_time |
| `summary_written` | epochs[viewer]更新(summary_seq, l3_start_seq) |
| `session_control`/`human_control` | 运行标志/待消费干预 |

新增事件类型时**必须**同步此表与apply实现——事件模型和reducer是一对一契约, 漏写=续推后状态错乱.

### 确定性要求
- apply是纯函数: 不读时钟/不掷随机/不做IO;
- 同一事件流reduce两次, 结果结构级相等(pydantic模型相等), 为plan.md P2验收项;
- 属性测试: 任意事件前缀的reduce结果 = 逐事件apply的结果.

## 8. 回放、断点续推与导出

- **回放**: 只读, 按seq顺序重放事件流+视角过滤, 支持跳转到任意seq. 不涉及LLM;
- **断点续推**: 加载会话 → 用reducer从事件流重建运行时状态(各会场阶段、组结构、指令队列、时钟、数值) → 引擎从安全点(见07"最小步")继续. 要求: 一切运行时状态必须可由事件推导, **禁止**引擎持有不落事件的隐藏状态. **分阶段**: P1仅实现回放+视角过滤; 完整reducer留P2(见plan.md P2);
- **导出**: 复盘页可导出markdown会议记录 = 按视角过滤后的事件流 + 书记摘要渲染;
- **脱敏纪律**: api key及任何配置严禁进入事件日志(见[08-config.md](08-config.md)安全红线); LLM报错文本落日志前脱敏.
