# 场景包字段与设计说明

本文定义 MUNagent 单会场场景包 `schema_version: "0.1"` 的当前格式。它既供场景作者使用，也是后续加载器和推演引擎读取场景数据的依据。

当前示例位于 [`scenario-template/`](../scenario-template/)。场景包只保存声明式内容；动作校验、状态转换、时钟、签署、终局判定和存档属于通用推演引擎。

## 1. 设计边界

场景包负责：

- 历史切入点、公开背景和资料来源；
- 会场、席位、议程和允许的行动类型；
- 每名代表的公开/私密角色卡；
- 外部事件和预期结束条件。

场景包不负责：

- 实现草案版本、比例校验和签署状态；
- 实现时间推进、事件调度和终局判定；
- 调用 LLM、组织 Agent 回合或保存运行记录；
- 提供场景专属可执行机制。

`mechanism.yaml` 不属于当前设计，不应存在。`mechanism.py` 暂时保留为 0 字节占位文件，不被 index 索引、不由加载器读取，也不得写入代码。

## 2. 标准目录

```text
<scenario>/
├── AGENTS.md                 # 编辑该场景包时的 Agent 约束
├── index.yaml                # 场景元数据和资料来源
├── background.md             # 全体代表共享的公开背景
├── venues/
│   └── <venue_file>.yaml     # 会场定义；当前只允许一个正式会场
├── reps/
│   └── <rep_id>.yaml         # 每名代表一个文件；文件名就是代表 ID
├── storyline.yaml            # 外部事件和结束条件
├── mechanism.py              # 0 字节预留文件，当前不参与场景加载
└── simulation/               # 推演运行时输出；不参与场景内容加载
    └── <YY-M-D-HH:MM>/       # 每次 initialize 新建；由 FileSystem 管理
        ├── reps/<rep_id>/
        └── submissions/<venue_id>/   # 仅含代表提交副本：<primary_owner>+<原文件名>+v<版本号>
```

`background.md` 和 `storyline.yaml` 使用固定文件名。venue 和代表文件分别通过扫描 `venues/*.yaml`、`reps/*.yaml` 发现，因此 `index.yaml` 不需要 `files`、`venues` 或 `representatives` 字段。

`simulation/` 由通用引擎在 `Scenario.initialize()` 时创建并绑定一个 `FileSystem`；场景包作者不在此目录写入声明式内容。`initialize` 同时新建 `EventList`，并将 `storyline.yaml` 载入的 `event_pool` 中所有 `type: time` 的外部事件经 `pull_up_event` 挂入待触发队列；`text` 条件事件暂不自动挂载。

运行时文件可见性由程序强制执行：

- `reps/<rep_id>/`：工作文件，通过 `scope`/`owner` 控制读/写；`list_visible` / `list_writable` 只枚举该目录。
- `submissions/<venue_id>/`：仅存放经 `File.submit()` 复制的提交副本，命名为 `<primary_owner>+<原文件名>+v<版本号>`（`primary_owner` 为该文件 owner 集合中最先加入者）；与同系列最新版内容 hash 相同则拒绝，否则递增版本。副本 `owner`/`scope` 为空，**不能**通过文件系统列表或直接路径被代表发现或改写。
- 代表若要得知某份 submission 的存在并读取其内容，只能经由 `EventList.get_events(rep_id)` 返回的、对该代表可见的事件（例如绑定了 `File` 的 `InstructionEvent` / `ResolutionEvent`）索引到该文件；引擎组装 Agent 上下文时不得把未被子事件引用的 submission 注入可见文件列表。
- 运行时 `Event` 对象构造时不携带剧情时间（`time` 为 `None`）；只有经 `EventList.submit_event` 入表时，才由事件表用当前时钟盖戳并分配 `id`。仍为 `PENDING` 的事件进入 pending 队列；经 `Event.status` 离开 `PENDING` 时由事件回调 `EventList._event_updated` 出队。剧情时钟由 `EventList.update_time`（绝对时刻）或 `EventList.time_pass`（相对时长）推进。

## 3. 通用约定

### 3.1 ID 与文件名

- 机器 ID 使用 ASCII `snake_case`；
- 场景本身不设置 `id`；
- 代表 ID 唯一取自角色 YAML 的文件名，不含 `.yaml`；
- 角色文件内部不得重复声明代表 `id`；
- venue、事件、议题等非代表对象仍通过显式 `id` 跨字段引用；
- 显示名称和正文使用简体中文，YAML 字段名使用英文。

例如：

```text
reps/winston_churchill.yaml -> winston_churchill
```

venue 的 seats 和角色关系中使用的 `winston_churchill` 都指向该文件。

### 3.2 时间

- 剧情时间使用带 UTC 偏移的 ISO 8601，例如 `1944-10-09T22:00:00+03:00`；
- 场景和会场同时声明 IANA 时区，例如 `Europe/Moscow`；
- 时间解析和推进由通用引擎实现，不能依赖运行机器的本地时区。

## 4. `index.yaml`

`index.yaml` 是场景入口文件。它只保存场景级元数据和资料来源，不索引可以从固定目录发现的内容。

### 4.1 顶层字段

| 字段 | 类型 | 必需 | 说明 |
|---|---|---:|---|
| `schema_version` | `str` | 是 | 场景格式版本，当前为 `"0.1"` |
| `title` | `str` | 是 | 主标题 |
| `author` | `str` | 是 | 作者或维护者 |
| `version` | `str` | 是 | 场景内容版本，建议使用语义化版本 |
| `language` | `str` | 是 | BCP 47 语言标签，例如 `zh-CN` |
| `start_story_time` | `time str` | 是 | 完整剧情开场时间 |
| `timezone` | `str` | 是 | IANA 时区 |
| `description` | `str` | 是 | 不包含角色秘密的场景简介 |
| `sources` | `list[source]` | 是 | 历史来源清单 |

### 4.2 `sources[]`

| 字段 | 类型 | 说明 |
|---|---|---|
| `title` | `str` | 来源或档案标题 |
| `url` | `str` | 可访问 URL；只有档案号时可指向机构检索入口 |
| `note` | `str` | 该来源支持哪些场景事实，不复制长篇原文 |

## 5. `background.md`

`background.md` 没有机器字段，是所有代表共享的公共知识。它应包含：

- 截至开场时间的必要历史背景；
- 会议为何召开、主要矛盾和现实约束；
- 玩家必须看到的初始数字、文件或公开情报；
- 会场需要讨论和产出的内容；
- 对标题简化、争议史实或伦理风险的说明。

它不得包含 `private.target`、秘密底线、角色专属情报或预定结局。

## 6. `venues/<venue_file>.yaml`

### 6.1 顶层字段

| 字段 | 类型 | 必需 | 说明 |
|---|---|---:|---|
| `id` | `str` | 是 | 会场 ID |
| `name` | `str` | 是 | 会场显示名称 |
| `timezone` | `str` | 是 | IANA 时区 |
| `description` | `str` | 是 | 空间、保密程度和谈判形态 |
| `chair` | `str` | 是 | `none` 或代表 ID |
| `seats` | `list[rep_id]` | 是 | 参加会场的代表 ID 列表 |
| `initial_agenda` | `str` | 是 | 开场正在处理的议题 |
| `session_phase` | `session_phase` | 是 | 会场开场时的会议阶段 |
| `agenda` | `list[agenda_item]` | 是 | 议题阶段和引导问题 |

### 6.2 `session_phase`

`session_phase` 声明会场在推演开始时的会议阶段，取值如下：

| 值 | 说明 |
|---|---|
| `chaired_core` | 有主持核心磋商 |
| `unchaired_core` | 无主持核心磋商 |
| `free_discussion` | 自由讨论 |
| `recess` | 休会 |
| `meeting_ended` | 会议结束 |

引擎侧的对应枚举为 `SessionPhase`（`scenario.venue`）。

### 6.3 `chair`

`chair` 是单个字符串：

- `none`：使用系统提供的中立主席；
- 代表 ID：由该代表担任会场主席，该 ID 必须同时出现在 `seats`。

它不是对象，不包含 `type`、`id` 或 `role` 子字段。

### 6.4 `seats[]`

`seats` 是纯字符串列表，每项都是从 `reps/<rep_id>.yaml` 文件名派生的代表 ID。代表姓名、代表团、职务和权力只在角色卡中定义，不在 venue 重复。

```yaml
chair: none
seats:
  - winston_churchill
  - joseph_stalin
```

### 6.5 `agenda[]`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `str` | 议题阶段 ID |
| `title` | `str` | 阶段标题 |
| `questions` | `list[str]` | 主席用于引导的开放问题，不是预设答案 |

venue 不包含 `kind`、`procedure`、`decision_document` 或 `information_policy`。会议流程、可用动作、草案规则和信息过滤属于通用推演引擎。

## 7. `reps/<rep_id>.yaml`

一份角色卡只定义一个代表和一个独立 Agent。代表 ID 来自文件名，角色 YAML 顶层不设置 `id`。

### 7.1 顶层字段

| 字段 | 类型 | 必需 | 说明 |
|---|---|---:|---|
| `name` | `str` | 是 | 历史人物显示名称 |
| `venue` | `str` | 是 | 所属会场 ID |
| `delegation` | `str` | 是 | 代表团 ID |
| `role` | `str` | 是 | 会场功能 |
| `public` | `object` | 是 | 全会场可知的角色信息 |
| `private` | `object` | 是 | 仅本角色及主席组件可知的信息 |
| `persona` | `object` | 是 | 扮演风格，不直接授予权力 |
| `agent_directive` | `str` | 是 | 该 Agent 的行动边界和重点提醒 |

### 7.2 `public.target` 与 `private.target`

可见性已经由父级区块表达，因此两个区块都使用局部字段名 `target`：

```yaml
public:
  target:
    - 公开目标

private:
  target:
    - id: hidden_goal
      objective: 不公开的真实目标
      importance: critical
```

禁止使用 `public_target`、`public_targets`、`private_target`、`private_targets` 或 `priorities`。

### 7.3 `public`

| 字段 | 类型 | 说明 |
|---|---|---|
| `title` | `str` | 开场时的正式职务 |
| `position` | `str` | 可公开表达的总体立场 |
| `target` | `list[str]` | 其他代表可以合理知道的公开目标 |
| `formal_powers` | `list[str]` | 由身份直接拥有的正式权力 |
| `limits` | `list[str]` | 权力边界和无法单方面完成的事项 |

### 7.4 `private`

| 字段 | 类型 | 说明 |
|---|---|---|
| `target` | `list[private_target]` | 真正需要优化的角色目标 |
| `red_lines` | `list[str]` | 正常情况下不可接受的结果 |
| `bargaining_space` | `list[str]` | 可以交换或有条件接受的方案 |
| `private_information` | `list[str]` | 该角色独有的判断、担忧或渠道信息 |
| `relationships` | `mapping[rep_id, str]` | 对其他代表的私下评价 |

`private.target[]`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `str` | 私密目标 ID |
| `objective` | `str` | 角色真正希望达成的目标内容 |
| `importance` | `str` | 推荐 `critical`、`high`、`medium`、`low` |

### 7.5 `persona`

| 字段 | 类型 | 说明 |
|---|---|---|
| `personality` | `str` | 决策与互动性格 |
| `speech_style` | `str` | 发言和语言风格 |
| `decision_tendency` | `str` | 面对风险、妥协和信息不足时的倾向 |
| `honesty` | `float` | 0 至 1 的诚实倾向参考，不是自动随机概率 |

`persona` 不能覆盖 `formal_powers`、通用引擎规则或信息可见性。

## 8. `storyline.yaml`

### 8.1 顶层字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `targets` | `list[story_target]` | 场景设计层面的整体目标 |
| `events` | `list[event]` | 代表无法直接控制的外部事件 |
| `end_conditions` | `list[end_condition]` | 交给通用引擎判定的结束条件 |

`targets[]` 使用 `id` 和 `description`。它描述场景应产生的博弈，不等同于角色卡目标。

### 8.2 `events[]`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `str` | 事件 ID |
| `condition` | `condition` | 事件触发条件，只包含 `type` 和 `content` |
| `content` | `str` | 投递给当前会场的事件内容 |

event 顶层只包含 `id`、`condition` 和 `content`，不设置 `inference`、`historicity` 或 `scope`。事件内容本身应足以让代表判断其影响，不额外附加与 content 重复的解释。所有事件默认由主席/引擎作为当前会场事件处理。

当前事件不使用 `effects`，也不直接修改自定义数值。若将来引擎提供统一效果模型，必须先更新引擎接口和 schema。

### 8.3 `condition`

event 的 `condition` 固定包含两个字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `type` | `str` | 只能是 `time` 或 `text` |
| `content` | `str` | 与类型对应的时间值或自然语言判断条件 |

`time` 表示剧情时间到达指定时刻，由引擎直接比较时间：

```yaml
condition:
  type: time
  content: "1944-10-09T22:45:00+03:00"
```

`text` 表示自然语言条件，由引擎把条件和必要的会议记录交给 LLM 判断是否成立：

```yaml
condition:
  type: text
  content: 会场已经讨论百分比含义，但仍未形成执行办法。
```

LLM 在这里仅判断条件真假，不直接修改状态、生成事件结果或决定会议行动。

### 8.4 `end_conditions[]`

结束条件与 event condition 使用同一套语义，但列表元素不再额外嵌套 `condition`。每项只能包含：

| 字段 | 类型 | 说明 |
|---|---|---|
| `type` | `str` | `time` 或 `text` |
| `content` | `str` | 时间值或交给 LLM 判断的自然语言结束条件 |

示例：

```yaml
end_conditions:
  - type: text
    content: 主要代表均已接受同一份最终方案。
  - type: time
    content: "1944-10-10T10:00:00+03:00"
```

任一结束条件成立时，引擎结束推演。场景包只描述“什么时候结束”，不在这里编码终局类型、结果代码或状态转换。

## 9. 跨文件不变量

引擎侧入口为 `scenario.load.load_scenario(path)`，或 `Scenario().load(path)`（内部委托给前者）。解析与校验逻辑集中在 `scenario.load`，领域类 `Scenario`、`Venue`、`Representative` 只承载推演期状态。

加载场景时至少检查：

1. 固定文件 `index.yaml`、`background.md`、`storyline.yaml` 存在；
2. `venues/` 和 `reps/` 中至少各有一个 YAML 文件，且加载器只扫描场景根目录内的这两个固定目录；
3. 从角色文件名派生的代表 ID、venue 席位和角色文件一一对应；
4. 每张角色卡包含 `public.target` 和 `private.target`，且不包含旧目标字段；
5. venue 的 seats、角色关系引用有效代表 ID；chair 为 `none` 或 seats 中的代表 ID；`session_phase` 为合法枚举值；
6. storyline 的事件 ID 唯一；event 顶层恰好只包含 `id`、`condition` 和 `content`，且 condition 只包含 `type` 和 `content`；
7. 每个 `end_conditions[]` 元素恰好只包含 `type` 和 `content`；
8. 所有 condition 的 `type` 只能是 `time` 或 `text`，前者 content 必须是带 UTC 偏移的 ISO 8601 时间；
9. 私密字段不会进入公共背景、普通会场广播或其他代表上下文；
10. 不存在 `mechanism.yaml`，`mechanism.py` 存在且大小为 0 字节；
11. index 不包含顶层 `id`、`files`、`historical_scope`、`venues`、`representatives`、`content_notice`、`subtitle`、`date` 或 `player_count`。
12. `schema_version` 只在 `index.yaml` 顶层声明；venue、代表和 storyline 文件不得重复声明。

## 10. 推荐设计顺序

1. 在 `index.yaml` 确定基本元数据和资料来源；
2. 写 `background.md`，说明历史切入点并只放开场公共知识；
3. 写 venue，确定主席、参会代表和议题；
4. 为每个代表分别写公开与私密角色卡，检查目标既有冲突又存在交换空间；
5. 写 `storyline.yaml` 的外部压力和结束条件，不预写代表行动；
6. 完成 YAML 解析、引用、可见性和目录边界验证；
7. 将执行这些配置所需的通用功能实现到 `src/`，不要写入场景包。

场景设计完成的标准不是资料数量，而是四类内容边界清楚：所有人知道什么、单个角色知道什么、外部世界可能发生什么、通用引擎需要怎样读取和执行这些声明。
