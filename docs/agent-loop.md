# 代表 Agent 主循环与上下文管理

本文描述当前单会场闭环中代表 Agent 的事件驱动主循环。目标是让每名代表拥有独立线程，同时避免把整场会议的 LLM 临时对话无限追加到上下文。

## 1. 权威记录与观察收件箱

`EventList`、会场状态和文件系统仍是权威事实来源。每名代表另有一个线程安全的 `AgentInbox`，其中只保存由 `VenueEngine` 投递的不可变 `Observation`：

- `sequence` 是会场内单调递增的观察序号；
- `kind` 区分事件新建、字段编辑和状态变化；
- `event` 是投递时刻的事件快照，后续编辑不会反向改变已经排队的观察；
- `priority` 决定是否中断正在进行的 LLM 轮次；
- `activates_agent` 决定该观察是否需要触发决策。

事件新建、事件编辑、状态裁定和主席议题操作都先由 `VenueEngine` 顺序落实，再投递观察。事件 `scope` 的程序过滤发生在投递前；编辑 `scope` 时，原 scope 和新 scope 中的代表都会收到这次权限变化，避免已经知道事件的代表被假定“忘记”。

代表提交事件时，`EventSubmission.actor_id` 记录行动来源。它只用于观察调度，不参与权限裁定。新建事件不会再次激活它的提交者，但提交者仍可从当前工具结果和权威 `EventList` 中看到该事件；事件随后被编辑或裁定时仍会正常激活相关代表。

## 2. 固定合并窗口

Agent 线程空闲时阻塞等待首条观察。收到第一条普通观察后开启固定 300ms 合并窗口：

```text
0ms    收到 A，窗口开始
120ms  收到 B
260ms  收到 C
300ms  将 A、B、C 作为一个 batch 激活 Agent
```

窗口截止时间不会因 B、C 到达而延后，避免事件持续产生时 Agent 永远无法开始。紧急且可激活的观察会跳过剩余窗口立即处理。

LLM 正在运行时到达的普通观察只进入 Inbox；本轮到达安全点并结束后，Agent 用 `take_ready()` 一次取走这些观察。当前紧急类型包括：

- 系统外部事件；
- 阶段切换；
- 当前议题切换；
- 直接纸条；
- pending 事件的状态裁定。

紧急观察会设置本轮中断标志并调用 `LLM.stop()`。LLM 客户端会通过所在线程的 asyncio 事件循环取消当前流任务，不必等到下一条网络数据到达。已经成功执行的工具不会回滚；尚未执行的工具调用会在安全点被放弃。

## 3. 结构化长期记忆

每名代表拥有独立的 `AgentMemory`。它不进入 `EventList`，不会被其他代表看到，也不能参与引擎的权限或规则裁定。每条 `MemoryEntry` 包含：

- 稳定 ID（`m1`、`m2`……）；
- 类别：`strategy`、`commitment`、`belief`、`open_question`、`relationship` 或 `fact`；
- 正文与 1–5 重要度；
- 支持该记忆的可见事件 ID；
- `active`、`resolved` 或 `superseded` 状态；
- 创建和最后修订时的观察序号。

模型通过三个私有工具维护记忆：

- `remember`：新增记忆；同类别同正文的 active 记忆会合并来源；
- `revise_memory`：修订正文、重要度、来源或状态，不删除审计 ID；
- `list_memories`：按类别或状态查询。

工具层会验证 `source_event_ids` 对本代表确实可见。记忆只在当前模拟进程内保存，尚未实现模拟暂停后的落盘恢复。

## 4. 历史摘要与相关性检索

`EventHistory` 只记录实际投递给该代表的事件快照，因此不同代表的历史索引天然遵守各自可见性。事件编辑和状态裁定会更新当前快照，但已获知事件的代表不会被假定忘记。

每次激活按以下顺序选取上下文：

1. 本批新观察；
2. 所有当前可见的 pending 事件；
3. 最近 6 条尚未重复注入的可见事件；
4. 最多 12 条相关 active 长期记忆；
5. 最多 6 条相关旧事件；
6. 最多 4 段更早历史摘要。

相关事件检索使用确定性评分：记忆显式引用的来源优先，其次比较中英文词项重合、事件类型重要度和新近度。中文以二元字组建立词项，不依赖向量数据库或第三方运行时。未直接注入的旧事件每 6 条组成一段结构化摘要；摘要由事件 ID、类型、状态和截断正文生成，不调用 LLM，因此不会把摘要模型的猜测写成事实。

## 5. 无主持阶段冷却与防回声

`unchaired_core` 使用三层限制：

1. **行动冷却**：一次会场行动成功后，普通新观察至少等待 1 秒；冷却期内事件继续合并，紧急观察可立即打断等待。
2. **单轮硬预算**：一次激活最多 1 次公开发言、3 次会场事件行动；记忆和只读查询不占该预算。
3. **公共波次预算**：一名代表在同一公共发言波次中成功公开回应一次后，后续纯 `message/chat` 观察只记入历史，不再调用 LLM。出现纸条、动议、文件提案、裁定、系统事件、议题或阶段变化后，才恢复新的公开回应额度。

这条公共波次限制是防止 Agent 相互无限“收到—回复—再收到”的硬终止条件。它有意要求谈判从重复口头表态转向纸条、文件、提案或程序变化；如果未来需要更开放的长时间自由讨论，应由程序调度器显式开启新波次，而不是依赖 Agent 自行互相唤醒。

## 6. 单轮局部上下文

`RepresentativeAgent.messages` 只保存最近一次 `step` 的局部消息，不再作为跨轮永久聊天记录。每次激活重新构造：

1. 静态角色 system prompt；
2. 当前剧情时间、会议阶段和议题；
3. 本批新观察；
4. 相关长期记忆；
5. 当前所有可见 pending 事件；
6. 最近事件、相关旧事件和更早历史摘要；
7. 当前行动冷却与公共波次约束；
8. 本轮 LLM 与工具调用记录。

本轮结束后，第 8 项不进入下一轮。真正产生的会议行动已经保存在事件或文件系统中；只有经私有记忆工具明确保存的内容才会作为长期 Agent 判断继续参与后续上下文。

## 7. 主席 Agent 与 DM Agent

每个会场另有两个独立系统角色，它们与代表共享事件总线和停止信号，但使用
各自的线程、Inbox、局部 LLM 上下文和工具集：

- `ChairAgent` 只负责程序通知、点名发言、议程、阶段、表决和决议裁定；
- `DMAgent` 在指令提交时直接判断其可行性和实际成败；对于决议，DM 只消费主席或
  表决产生的 `accepted/rejected` 结果，再推演并发布危机更新。

### 7.1 中立主席与代表主席

`chair.rep: none` 创建中立主席。中立主席没有代表立场和私有记忆；它不读取纸条
或私聊，也不读取或裁定指令；它只读取需要主持程序处理的正式决议。

`chair.rep: <rep_id>` 创建代表主席。该人物仍保留自己的 `RepresentativeAgent`
处理政治发言、纸条和文件，同时由独立 `ChairAgent` 执行主席职责。两者共享该
代表的线程安全结构化长期记忆，但工具实行单写者：当绑定 LLM 的 ChairAgent
接管会场后，RepresentativeAgent 不能再调用议程或主席直切阶段工具。

代表主席不会因主持身份扩大情报范围：ChairAgent 不接收任何纸条/私聊，只能
读取该代表本来就在事件 scope 内的正式决议。未将代表主席列入 scope 的私密决议
不会由该主席看到或裁定。中立主席也只接收全场可见的普通系统更新。

`ChairEvent` 表示程序动作。通知默认全场可见；点名发言时全场都记录事件，但只有
`target_reps` 中的代表被激活。私密决议的裁定审计事件沿用原决议 scope，不扩大
可见范围。`decide_resolution` 和 `decide_switch_phase` 由程序硬校验：权力关闭时，
决议必须走表决，阶段切换必须引用目标一致且已经通过的动议。

### 7.2 DM 指令判定与决议任务队列

DM 不监听普通发言。`InstructionEvent` 以 `pending` 入表后立即投递给 DM，不经过主席
的 accepted/rejected 审批；`ResolutionEvent` 则只在主席或表决把状态改为 accepted /
rejected 后投递。每个事件 ID 在进程内只处理一次，并使用独立局部上下文，避免同时
注入多份长文书。任务提示最多注入 submission 前 6000 字符；更长正文由 DM 使用
`read_submission` 按 offset 分段读取，内容不会直接转发给代表。主席的同名工具只
能读取其有权处理的正式决议。

DM 必须先根据权限、资源、时距、组织阻力、情报质量和对手反制，把指令放入六档：

| 档位 | 工具值 | 成功率 |
|---|---|---:|
| 极有可能成功 | `very_likely_success` | 95% |
| 成功 | `success` | 80% |
| 可能成功 | `possible_success` | 60% |
| 可能失败 | `possible_failure` | 40% |
| 失败 | `failure` | 20% |
| 极大概率失败 | `very_likely_failure` | 5% |

`adjudicate_instruction` 根据显式 `dm_random_seed`、会场 ID、指令事件 ID 和提交正文
哈希生成稳定的
`[0, 1)` 伪随机数；仅当 `roll < probability` 时成功。随机数不依赖所选档位，因此
不能通过反复换档重抽。相同种子和事件输入得到相同结果，便于复盘；不同模拟需要不同
结果时，应显式传入不同种子。每份指令只能抽取一次。成功后状态变为 `completed`，
失败后变为 `failed`；`accepted/rejected` 专用于决议。档位、概率、骰点、结果和理由
会写入原指令 scope 内可见的审计 `SystemEvent`。

DM 可执行两类动作：

- `advance_time`：完成判定的指令（包括失败尝试）和 accepted 决议可推进 1–1440 分钟
  剧情时间并触发到期事件；rejected 决议被程序禁止推进时间；
- `publish_crisis_update`：发布显式 scope 的 `SystemEvent`，其 `action` 自动加入
  `source_event:<id>` 与 `source_status:<status>`，使危机结果可追溯到原提交。

一项秘密行动可以产生公开可观察后果，但公开更新不得泄露原秘密正文或行动者细节。
需要不同知情层级时，DM 应发布多条不同 scope、不同正文的更新。每项任务每轮最多
四条更新、最多一次时间推进，防止单次 LLM 工具循环失控。

## 8. 启动方式

`Simulator` 通过可选 `llm_factory` 为每名代表创建独立 LLM：

```python
from engine.end_conditions import LLMTextEndConditionEvaluator
from engine.simulator import Simulator
from llm import LLM

simulator = Simulator(
    scenario,
    llm_factory=lambda rep: LLM(thinking=True),
    chair_llm_factory=lambda venue: LLM(thinking=True),
    dm_llm_factory=lambda venue: LLM(thinking=True),
    dm_random_seed="run-001",
    text_end_condition_evaluator=LLMTextEndConditionEvaluator(
        LLM(thinking=False)
    ),
)
simulator.start()
```

绑定 LLM 的代表线程启动后等待第一条可见事件，不会空转调用模型。ChairAgent 会在
启动时做一次程序状态检查，以便在有主持阶段发布开场通知或点名；它不会自动伪造
会议事件，只有实际工具调用才入表。DMAgent 等待新建 pending 指令或终态决议。

三个 factory 相互独立；未传某个 factory 时，对应角色线程立即退出且不会访问真实
API。`dm_random_seed` 默认是字符串 `"0"`；正式运行应为每局显式保存一个种子。
测试应使用 mock LLM，不消费真实模型请求。

所有角色线程建立完成后，`Simulator` 必定向每个会场提交一条 completed 的
`MeetingStartEvent`，避免代表与主席都等待第一条观察形成启动互锁：

- `unchaired_core` / `free_discussion`：事件激活全体代表，不激活主席；
- `chaired_core` / `recess`：事件只激活主席，代表只记录事件但不开始抢答；
- `meeting_ended`：不再提交启动事件。

主席不再执行不可审计的隐式开场轮次，而是像其他角色一样由这条权威事件激活。
因此正常启动后的 `EventList` 至少包含 `meeting_start#0`；终端事件流也会立即显示它。

正式命令行入口已经将这些 factory、随机种子、自动终局和运行存档统一装配：

```bash
python src/main.py serve scenario-template --seed run-001
python src/main.py watch
```

时间终局条件由程序直接判断；所有文本终局条件在权威事件版本变化后合并为一次只读
裁判请求。触发后会场提交 `meeting_ended` 阶段事件并协作停止。种子、终局理由和事件
审计写入本次 `simulation/<run_id>/`，详见 [`runtime-service.md`](runtime-service.md)。

## 9. 当前边界

- 主席当前支持单次点名激活，尚未实现带时长、候补名单和自动超时的完整发言队列；
- 尚未实现按事件语义细分系统事件紧急程度；
- 长期记忆尚未落盘，不能跨进程恢复；
- DM 处理轨迹当前保存在进程内并通过来源事件关联，尚未单独落盘为危机审计文件；
- 当前相关性检索为确定性词项检索，尚未使用 embedding；
- 普通观察合并窗口、无主持冷却和行动预算当前使用通用默认值，尚未开放为场景配置。
