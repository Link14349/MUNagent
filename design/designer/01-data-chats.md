# 01 场景包与 .chats/ 数据设计

细化 [index.md](index.md)「场景包数据设计」一节. 核心原则: **场景包文件是唯一事实源, .chats/ 是绑定在包内的对话历史**——agent 做过什么、改过什么, 都能在 .chats/ 里查到, 但场景内容本身永远以包内文件为准.

## 1. 场景包结构(含 .chats/)

以 `scenarios/cabinet-crisis/` 为格式参考, 增加 .chats/:

```
<scenario_id>/
├── manifest.yaml
├── background.md
├── story_design.md
├── venues.yaml
├── crisis_arcs.yaml
├── stats.yaml
├── seats/
│   └── <seat_id>.yaml
├── references/              # 资料(agent 检索或用户添加), 结构沿用 introduction.md
│   ├── index.yaml
│   ├── <doc_id>.md
│   └── raw/
├── .chats/                  # 本场景的全部 agent 对话(隐藏目录)
│   └── <chat_id>.jsonl      # 一个对话一个文件, 一行一条记录
└── .history/                # 版本快照(见 §5)
    └── <snap_id>/           # 每份快照 = 场景内容文件的一份完整拷贝 + .meta.yaml
```

- **.chats/ 与 .history/ 不进导出**: 导出 zip 恒剔除这两者, `references/raw/` 默认剔除(可选包含); 场景分享的是设定, 不是设计过程;
- **.chats/ 与 .history/ 不进文件树**: 前端文件树不显示它们(以及 `.` 开头的其他文件), 分别由对话 UI 与历史版本面板专管(见 02); 删了只丢历史不伤场景;
- 没有 `.chats/index.yaml`: 对话清单由后端扫描 `.chats/*.jsonl` 生成(标题等元信息在每个文件的首行 meta 记录里), 避免索引与文件不同步的经典 bug.
- **`story_design.md` 与 `crisis_arcs.yaml` 分工**(设计 Agent 生成两份文件时必须遵守, 避免互相抄一遍): `crisis_arcs.yaml` 的 `main_arc` 是外部世界**可投放的压力事件库**——何时投哪条由时间窗口与会场进程共同决定; `story_design.md` 是给 DM/主席用的**叙事透镜**, 装 `main_arc` 装不下的东西——剧情参考线、「会场产出→外部反应」映射、分支转化条件("内阁若公开分裂, 同样动作会被解读为失控")、DM 节奏笔记. 先写 story_design 理清映射, 再为需投放节点写 crisis_arcs. 两者对同一个事件各自成文时, `story_design.md` 里对应段落要写清引用哪个 `main_arc` 事件 id, 不重复抄内容(时间线表格、事件正文都不许在两份文件里各写一遍).

## 1.0 manifest.yaml: 场景元信息

`manifest.yaml` 是场景包的**身份卡与目录摘要**, 不含危机弧线细节(那些归 `crisis_arcs.yaml`). 用于场景库列表展示、Agent 开场上下文、导出分享时的元数据.

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 场景唯一标识, 与目录名一致; 仅 `[a-z0-9-]` |
| `title` | 是 | 人类可读标题(场景库/设计器顶栏) |
| `author` | 否 | 作者或组织名, 默认空 |
| `version` | 否 | 语义化版本字符串, 默认 `1.0.0` |
| `created` | 否 | 创建日期(ISO 日期或自由文本), 默认空 |
| `language` | 否 | 场景主语言 BCP47 简写, 默认 `zh` |
| `start_story_time` | 是 | 推演起始故事时间(ISO 8601, 含时区), 如 `2026-03-15T09:00:00+08:00` |
| `description` | 否 | **一句话简介**, ≤100 字; 场景库卡片、搜索摘要用 |
| `content` | 否 | **长梗概**, ≤500 字; 交代时代背景、核心矛盾、推演起点与终局类型, 供 Agent 与人类快速把握场景全貌 |

**硬约束**: `description` 与 `content` 按字符数计(中文一字=一字符); 超长由结构校验报错. **不写** `end_conditions`——推演何时结束归 `crisis_arcs.yaml`.

示例:

```yaml
id: cabinet-crisis
title: 三人内阁危机
author: munagent
version: 1.0.0
created: "2026-07-12"
language: zh
start_story_time: "2026-03-15T09:00:00+08:00"
description: 邻国边境军演引发的三人内阁危机推演，考验外交降级与军事威慑之间的抉择。
content: |
  邻国在争议边境增兵并实弹演习，内阁在总理、国防部长、外交部长三人之间分裂……
  (完整梗概 ≤500 字)
```

## 1.1 venues.yaml: 会场结构

顶层字段 `venues` 为会场列表; 单会场场景通常只有一项, 多分会场场景每项对应一个独立决策空间(如苏联政治局 / 美国国会).

### 会场字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 会场唯一标识, `[a-z][a-z0-9_]*`; 席位文件 `venue` 字段引用此值 |
| `name` | 是 | 人类可读名称(文件树、推演 UI 标签) |
| `kind` | 否 | `main`(总会场) / `sub`(分会场) / `temporary`(临时联合会场), 默认 `main` |
| `timezone` | 否 | IANA 时区, 如 `Asia/Shanghai` |
| `presiding_seat` | 否 | 主持席席位 id(主席 Agent 扮演), 须出现在本节 `seats` 列表中 |
| `decision_rule` | 否 | 决策规则: `pass_threshold`(如 `majority` / `unanimity`)、`veto_seats`(一票否决席位 id 列表) |
| `initial_agenda` | 否 | 开场议程文案 |
| `initial_phase` | 否 | 开场阶段(状态机阶段名, 如 `ModeratedCaucus`) |
| `seats` | 是 | **本会场全部席位清单**, 见下表; 与 `seats/` 目录双向一致 |
| `clock_rate` | 否 | 故事时钟倍率提示, 如 `per_mod_speech: 5m`(一次 mod 发言推进 5 分钟故事时间) |

### `seats` 列表(会场内)

每个元素描述一个在本会场开会的角色; **`id` 与 `name` 必须与 `seats/<id>.yaml` 内完全一致**, 且该文件的 `venue` 字段等于本会场的 `id`.

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 席位 id, 与文件名 `seats/<id>.yaml` 一致 |
| `name` | 是 | 角色显示名, 与席位文件顶层 `name` 一致 |

**一致性纪律**(结构校验 error):
- `venues` 某会场的 `seats` 列表 = 所有 `seats/*.yaml` 中 `venue` 指向该会场的条目(不多不少);
- 新增席位时**同时**写 `seats/<id>.yaml` 并在对应会场的 `seats` 里追加 `{id, name}`;
- 删除席位时两处同步删除.

示例:

```yaml
venues:
  - id: cabinet
    name: 内阁会议室
    kind: main
    timezone: Asia/Shanghai
    presiding_seat: premier
    decision_rule:
      pass_threshold: majority
      veto_seats: []
    initial_agenda: 讨论对边境危机的应对方案
    initial_phase: ModeratedCaucus
    seats:
      - id: premier
        name: 总理
      - id: defense_minister
        name: 国防部长
      - id: foreign_minister
        name: 外交部长
    clock_rate:
      per_mod_speech: 5m
      per_unmod_round: 15m
```

## 1.2 seats/<seat_id>.yaml: 席位角色卡

每个可扮演角色一个文件, 文件名 = 顶层 `id` + `.yaml`. 含公开信息(全体可见)、私密信息(仅该代表 Agent 与 DM)、权力清单(指令判定依据)、人格卡(代表 Agent 扮演用).

### 顶层字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 席位唯一标识, `[a-z][a-z0-9_]*`, 与文件名及 `venues.yaml` 中对应条目的 `id` 一致 |
| `name` | 是 | 角色显示名, 与 `venues.yaml` 中对应条目的 `name` 一致 |
| `venue` | 是 | 所属会场 id, 引用 `venues.yaml` 中某会场的 `id` |
| `public` | 是 | 公开信息(见下) |
| `private` | 是 | 私密信息(见下) |
| `portfolio_powers` | 否 | 权力清单, 判定个人指令时的依据 |
| `persona` | 是 | 人格卡, 代表 Agent 扮演参数 |

### `public` — 全体可见

| 字段 | 必填 | 说明 |
|---|---|---|
| `title` | 否 | 职务/头衔 |
| `faction` | 否 | 所属阵营或派系标签 |
| `stance` | 否 | 公开立场一句话 |

### `private` — 仅本席位 Agent 与 DM

| 字段 | 必填 | 说明 |
|---|---|---|
| `secret_goals` | 否 | 秘密目标字符串列表 |
| `relationships` | 否 | 与其他席位关系, 每项 `{seat: <席位id>, attitude: <描述>}` |
| `resources` | 否 | 可动用资源/筹码列表 |

### `portfolio_powers` — 权力清单

列表, 每项:

| 字段 | 必填 | 说明 |
|---|---|---|
| `power` | 是 | 可行使的权力描述 |
| `limits` | 否 | 边界/限制(什么情况下不能单独行使) |

### `persona` — 人格卡

| 字段 | 必填 | 说明 |
|---|---|---|
| `personality` | 否 | 性格关键词 |
| `speech_style` | 否 | 说话风格 |
| `decision_tendency` | 否 | 决策倾向(风险厌恶/行动导向等) |
| `honesty` | 否 | 诚信倾向 `0.0`–`1.0`, 默认 `0.5`; 见 introduction.md 欺骗边界 |

示例(节选):

```yaml
id: premier
name: 总理
venue: cabinet
public:
  title: 内阁总理
  faction: 温和派
  stance: 主张外交途径化解边境危机
private:
  secret_goals:
    - 保住总理职位, 避免提前大选
  relationships:
    - { seat: defense_minister, attitude: 既依赖又警惕 }
  resources:
    - 议会脆弱多数
portfolio_powers:
  - power: 召集内阁会议并设定议程
    limits: 不能单方面罢免部长
persona:
  personality: 稳重、谨慎、善于权衡
  speech_style: 官方、委婉、注重程序
  decision_tendency: 风险厌恶, 倾向拖延与妥协
  honesty: 0.6
```

## 1.3 crisis_arcs.yaml: main_arc、random_pool 与 end_conditions

`crisis_arcs.yaml` 有三个顶层字段: `main_arc`(预埋事件列表)、`random_pool`(随机事件池)、`end_conditions`(推演终局条件). **没有独立的 timeline 字段**——时间信息全部内联在事件的 `trigger` 表达式里(单一事实源).

### end_conditions: 推演终局

`end_conditions` 是**何时进入终局评估**的判定清单, 与 `main_arc` 里"外部世界下一拍发生什么"分开——前者回答"这场推演什么时候该收场、按什么标准收场". 列表内**满足任一条件**即触发终局流程(DM 做收场叙述与结果评估); 多条并存表示"时限到了"或"剧情已达成关键结局"都可以结束.

| 字段 | 必填 | 说明 |
|---|---|---|
| `type` | 是 | 终局类型, 见下表 |
| `at` | `type=story_time_reached` 时必填 | ISO 8601 故事时间(含时区); 当前故事时间到达该时刻时触发终局 |
| `desc` | `type=dm_judgement` 时必填 | 自然语言描述的终局判定条件, 由 DM(LLM)对照当前局势判断是否已达成 |

**`type` 取值**:

| type | 含义 | 示例 |
|---|---|---|
| `story_time_reached` | **时限型终局**: 故事时钟到达 `at`, 无论剧情是否"自然完结"都进入终局评估 | `at: "2026-03-16T18:00:00+08:00"` |
| `dm_judgement` | **结果型终局**: 当 `desc` 描述的局势结果已发生时触发(如政权更迭、条约签署、战争爆发) | `desc: "总理被罢免, 或内阁通过紧急状态令"` |

```yaml
end_conditions:
  - type: story_time_reached
    at: "2026-03-16T18:00:00+08:00"
  - type: dm_judgement
    desc: "总理被罢免, 或内阁通过紧急状态令, 或三方达成妥协方案"
```

- 结构校验覆盖: `type` 合法、`story_time_reached` 必有 `at`、`dm_judgement` 必有 `desc`;
- 主席跳时、DM 判定 `takes_effect_at` 时应对照 `main_arc` 事件时点; **是否该结束推演**则对照本节 `end_conditions`(见 `story_design.md` 时间线指引).

### 事件字段

`main_arc` 是一个事件列表, 列表的一个元素即为一个事件:

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 全文件唯一; 只由大小写英文字母、数字、下划线组成的连续字符串, 且以字母开头(它要在表达式里被引用, 不能与数字/时长字面量混淆) |
| `trigger` | 否 | 主动触发条件: 每回合 DM 都会判定一次是否满足, 满足了才进入触发判定、检查 `condition`; 省略视为恒真 |
| `condition` | 否 | 事件最终被触发需要满足的条件(与 trigger 同一表达式语言); 省略视为恒真 |
| `content` | 是 | 事件内容(播报底稿, DM 可临场改写) |
| `default_scope` | 否 | 默认的事件可见范围(沿用事件 scope 体系, 见 introduction.md; 常用 `global` 全场播报 / `dm-only` 暂扣仅主席团), DM 可临场修改 |

**事件生命周期**: 每个事件至多触发一次; 触发时刻(story_time)被记录, 供其他事件的表达式做相对定位; trigger 为真但 condition 为假时本回合不触发, 后续回合继续评估(直到触发或推演结束).

**trigger 与 condition 的分工**是成本与语义, 不是语法(两者语法同构): trigger 建议只放可程序求值的时间条件——每回合要扫全部未触发事件, 必须便宜; condition 放需要 LLM 判断的 `text` 语义条件——只在 trigger 命中后才评估. 把 `text` 写进 trigger 语法上合法, 但每回合都烧一次 LLM 判定, 生成时应避免.

### 事件类型(写每条 main_arc 事件前先归类)

| 类型 | 含义 | trigger / condition | content |
|---|---|---|---|
| **环境压力** | 外部世界自有节奏, 不取决于本场表决/指令 | 可纯时间 trigger; condition 省略 = 到点可发 | 只写事实性压力/新闻 |
| **反应/后果** | 外部世界对会场已发生之事的回应 | trigger 定时间窗口; condition **必须**含 `text` | 只写事实性压力/新闻, 不写派系预定行动 |

- **反应/后果类禁止纯时间到点必发**——若代表做了完全不同选择就不该触发的节点, 必须有 `text`;
- **`text` 陈述须可对照会场产出**: 已通过的联合指令、已生效公报、主席已播报的 Crisis Update、DM 已落盘的指令后果; 不写「激进派情绪高涨」等不可验证句;
- **`content` 不写「某派将/开始/决定……」**——派系行动由代表在会场里演;
- **反模式**: main_arc 过半为纯时间链且 content 预写各方反应 = 历史时间轴复刻, 不合格.

### 条件表达式

`trigger` 与 `condition` 通过 bool 表达式与文字表达条件混合的方式编写, 具体值为一个字符串(整个表达式用 `""` 括起来). 基本组成单元:

- **时间比较** `time <op> <时点>`, op ∈ `>, >=, <, <=, =`:
  - 时点可为**绝对时间**(ISO 8601): `time > 2026-03-16T08:00:00+08:00`, 当前故事时间在该时刻之后则为 True;
  - 也可**相对其他事件定位**: `time > parliament_window + 1y2mo3d2h30m` = 当前故事时间已过 parliament_window 触发时刻之后的 1年2月3天2小时30分. 时长单位: `y`(年) `mo`(月) `d`(日) `h`(时) `m`(分)——月必须写 `mo`, 避免与分钟的 `m` 歧义;
  - **偏移只能向后(`+`)**: 只能表达"某事件发生之后多久", 不能写 `- 时长` 表达"某事件发生之前"——未触发事件的时刻不可知, "X 之前 2 小时"在 X 发生前无法判定;
  - **被引用事件尚未触发时**: `>`/`>=`/`=` 恒返回 False; `<`/`<=` 恒返回 True(尚未发生, 自然早于它之后的任何时点);
  - `=` 按分钟精度比较, 命中窗口极窄, 生成时避免使用.
- **文字表达** `text '<自然语言陈述>'`: 如 `text '内阁已通过外交渠道推动降级或与邻国实质接触'`, 由 DM(LLM)对照当前局势判断真伪. 写成**可判定的陈述句**, 须可对照会场产出核对; 不写疑问句/情绪/倾向模糊句; 同一互斥组的多个事件应共用同一句陈述、一正一 `not`, 保证互斥(见示例).
- **括号** `()`: 确定优先级, 如 `time > parliament_window and (text '矛盾公开化' or time < 2026-03-16T08:00:00+08:00)`;
- **非** `not` / **与** `and` / **或** `or`: 优先级 `not > and > or`, 更复杂的用括号显式提级.

**短路求值**(运行时语义, 生成侧与推演侧共享):

- 连续 `and`(`A and B and C …`)从左到右依次求值, 遇到第一个 False **立即返回 False**, 其后的项不再求值;
- 连续 `or`(`A or B or C …`)从左到右依次求值, 遇到第一个 True **立即返回 True**, 其后的项不再求值;
- 被短路跳过的项完全不求值——`text` 谓词被短路 = 省掉一次 LLM 判定. 这是下面写作纪律的依据.

**写作纪律**: 生成表达式时利用短路语义控制 LLM 判定频率, 但**语义正确优先于省调用**:

- **该用 `text` 的必须用 `text`**(反应/后果类); 成本靠时间闸门缩窗口, 不是靠假装一切都能用时间表达;
- 时间与 `text` 混用时, **把时间比较放在 `text` 之前**(同一条 and/or 链内), 让程序可求值的部分先跑;
- 且**让排在前面的时间条件充当"闸门"**: and 链开头放时间窗口(如 `time >= 某事件 + 3h and text '…'`), 使 `text` 判定只在窗口内发生.

### 结构: 开场、分支与收敛

- **开场布景(2~4 拍)**: 可用 time 线性链(`time >= 前事件 + 2h`)把棋盘摆好——到点必发的环境压力;
- **此后 main_arc**: 默认 `时间窗口 and text '会场可验证陈述'`, 勿一路线性链排到终局;
- **分支**: 同窗口多条互斥 reaction——同句 text 一正一 `not`, 或多条各绑不同 text;
- **收敛**: 后续事件用绝对时间, 或用 `or` 引用多个前驱, 天然汇合;
- **兜底**: 都不满足就不触发, DM 即兴(弧线是参考, 不是脚本).

**生成自检**(main_arc 写完后):

- [ ] 纯时间到点事件 ≤ 4 个, 且均为环境压力、content 无派系预定反应
- [ ] 每个「历史转折点」有 `text` 绑会场产出, 或明确标为环境压力
- [ ] `content` 无「某某派将/开始/决定……」
- [ ] `random_pool` 用于僵局搅局, 非 main_arc 线性 filler

### 示例

```yaml
main_arc:
  - id: border_skirmish                              # [环境压力] 开场布景, 纯时间到点
    trigger: "time >= 2026-03-15T13:00:00+08:00"
    content: |
      边境传来消息: 邻国军队在争议地区进行实弹演习, 双方边防部队发生对峙.
    default_scope: global

  - id: parliament_window                            # [环境压力] 开场线性链(仅布景阶段)
    trigger: "time >= border_skirmish + 2h"
    content: |
      议会就边境对峙召开紧急质询, 内阁必须有可公布的立场.
    default_scope: global

  - id: diplomatic_backchannel                       # [反应/后果] 分支一; text 绑会场产出
    trigger: "time >= parliament_window + 1h and time < 2026-03-16T09:00:00+08:00"
    condition: "text '内阁已通过外交渠道推动降级或与邻国实质接触'"
    content: |
      邻国通过秘密渠道释放缓和信号, 国内舆论对此反应分裂.
    default_scope: global

  - id: escalation_night_patrol                      # [反应/后果] 分支二: 同句取反, 与分支一互斥
    trigger: "time >= parliament_window + 5h"
    condition: "not text '内阁已通过外交渠道推动降级或与邻国实质接触'"
    content: |
      夜间侦察对峙加剧, 前线指挥官请求扩大交火规则, 走火风险骤升.
    default_scope: global

random_pool:
  - id: media_leak
    weight: 3
    content: 外国媒体披露内阁内部在战和问题上存在严重分歧.
```

### 其余约定

- `random_pool` 事件只有 `id` / `weight` / `content`(可选 `default_scope`), **无 trigger/condition**——由主席在需要搅动节奏时按权重抽取, 不参与 main_arc 的评估循环;
- 结构校验(02§5 校验 chip)覆盖: id 唯一且格式合法、表达式可解析、表达式引用的事件 id 存在于 main_arc、时长单位合法;
- DM 运行时如何执行评估循环(程序先短路求值 time 部分、text 才进 LLM)属 deducer, 不在本文档范围; 但表达式的**语义**以本节为准, 生成侧与推演侧共享.

## 1.4 stats.yaml: 数值体系粒度

对应 introduction.md"数值体系设定"一条: 粒度可配置, 目的是给 DM 判定指令成败时一个参考依据, **不是精确战棋数值**. `stats.yaml` 全文件可选(不需要数值体系就不生成这个文件); 一旦生成, 顶层 `mode` 二选一, 整份文件只能用一种粒度, 不支持文件内混用.

### `mode: tags`(粗粒度标签, 默认推荐)

```yaml
mode: tags
tag_scale: [弱, 中, 强]        # 可选: 显式声明本文件的定性级别, 从低到高排列; 省略则默认这三级
entities:
  - id: cabinet_stability      # 全文件唯一
    label: 内阁稳定性          # 人类可读名
    owner: faction:温和派      # 归属: faction:<阵营名> / seat:<席位id>; 无明确归属可省略(视为场景整体态势)
    tags:
      议会支持: 弱
      民意: 中
```

- **`tag_scale` 要固定、全文件统一, 不要让不同实体各用各的词表**: DM 做判定时要能across实体做相对比较("弱"和"低"字面不同但语义相同, 会让 DM 的比较基准漂移), 生成 Agent 应该先定好这一个词表, 后面所有 `tags` 的值都从这个词表里选;
- 词表本身没有语义上限, 场景需要更细的分级可以扩成 `[弱, 中, 强, 极强]`, 但一旦定下就不要在同一文件里再引入词表外的词.

### `mode: values`(精确数值, 可选高级模式)

```yaml
mode: values
value_range: [0, 100]          # 可选: 声明数值范围, 供 DM/前端归一化展示; 省略则不假定范围
entities:
  - id: cabinet_stability
    label: 内阁稳定性
    owner: faction:温和派
    values:
      议会支持: 42
      民意: 55
```

- 结构和 `tags` 模式一一对应, 只是 `tags: {…}` 换成 `values: {…}`, 值是数字而不是词表里的词;
- 这是"战棋化"选项, 面向想要更精确数值博弈的场景; 默认场景不需要, 生成 Agent 不应主动升级到这个模式, 除非用户明确要求。

### "无数值"选项怎么表达

不是 `mode` 的第三个值, 而是**整个 `stats.yaml` 文件不生成**(该文件本来就可选). 不要为了"三选一"而生成一个空壳 `mode: none` 文件.

### 共同约定

- `owner` 只是归属标注(这个数值描述的是谁), **不再控制可见性**——`visibility` 字段已废弃, 数值体系走场景内容的常规可见性规则, 不单独定义一套"阵营可见性";
- 结构校验覆盖: `id` 全文件唯一; `mode: tags` 下所有 `tags` 的值必须落在 `tag_scale`(或默认三级)内, 出现词表外的词判定为错误, 不是警告.

## 2. chat 文件格式(JSONL)

选 JSONL 的理由: agent 回合是流式追加的(文本段/工具调用/文件编辑交错), 追加写一行一条最自然, 中途崩溃最多丢最后一行, 不会损坏整个文件.

`chat_id` 格式: `<yyyymmddHHMMSS>-<4位随机>`(如 `20260712143005-a3f1`), 生成后不变; 排序用文件内时间戳.

### 2.1 首行 meta

```json
{"type": "meta", "v": 1, "id": "20260712143005-a3f1", "title": "初始场景生成", "created_at": "2026-07-12T14:30:05+08:00"}
```

- `title` 新建时默认为「新对话」; **首轮 agent 任务结束后**, 若仍为默认标题, 后端用 LLM 根据首轮用户消息与 agent 回复概括 8～16 字标题(异步, 不阻塞主任务); LLM 失败则回退为首条用户消息前 30 字截断. 用户可手动改名(改名 = 重写首行), 改过后不再自动覆盖;
- `v` 是 chat 格式版本号, 将来变更格式时做迁移判断.

### 2.2 记录行

meta 之后每行一条记录, 公共字段: `seq`(文件内自增, 从 1 起)、`ts`(ISO 时间)、`turn`(第几轮用户↔agent 交换, 用户每发一条消息 turn+1, 该轮 agent 产生的所有记录共享同一 turn)、`type` + 各类型载荷:


| type | 载荷字段 | 说明 |
|---|---|---|
| `user_message` | `text` | 用户发送的消息 |
| `agent_text` | `text` | agent 的一段完整回复文本(一轮内可多段, 与工具/编辑交错; 流式增量不落盘, 只落最终整段) |
| `tool_call` | `tool`, `args_summary`, `status: ok\|error`, `result_summary` | 一次工具调用; args/result 只存单行摘要(≤200 字), 大体积产物应落 references/ |
| `file_edit` | `path`, `op: create\|modify\|delete`, `diff` | agent 对场景包文件的一次编辑; `diff` 为 unified diff 全文(create 时 old 为空, delete 时 new 为空), 是"看改了什么"与"撤销"的数据基础 |
| `system` | `kind: aborted\|error\|revert`, `text` | 中止、脱敏后的错误、用户撤销某次编辑(`text` 注明撤销的 seq) |
| `usage` | `model`, `input_tokens`, `output_tokens`, `tool_calls` | 每轮结束追加一条, 记本轮消耗, 供 UI 显示与统计 |
| `todo` | `text` | agent 调用 `edit_todo` 产生的**全量快照**(一行一项, 前缀 `[ ] `/`[x] `), 不是差量; 当前 todo = 文件里最后一条 `todo` 记录, 见 §2.4 |


一轮典型序列:

```jsonl
{"seq":7,"turn":3,"ts":"…","type":"user_message","text":"给临时政府再加两个左翼席位"}
{"seq":8,"turn":3,"ts":"…","type":"agent_text","text":"好的, 我先看一下现有席位构成…"}
{"seq":9,"turn":3,"ts":"…","type":"tool_call","tool":"list_files","args_summary":"seats/","status":"ok","result_summary":"7 个席位文件"}
{"seq":10,"turn":3,"ts":"…","type":"file_edit","path":"seats/louis_blanc.yaml","op":"create","diff":"--- /dev/null\n+++ seats/louis_blanc.yaml\n@@ …"}
{"seq":11,"turn":3,"ts":"…","type":"file_edit","path":"seats/albert.yaml","op":"create","diff":"…"}
{"seq":12,"turn":3,"ts":"…","type":"agent_text","text":"已新增路易·布朗与阿尔贝两个席位, 立场为…"}
{"seq":13,"turn":3,"ts":"…","type":"usage","model":"deepseek-v4-pro","input_tokens":18234,"output_tokens":2110,"tool_calls":3}
```

### 2.3 硬约束

- **key 与配置永不入 chat**(全局安全红线): tool_call 摘要与 error 文本落盘前脱敏;
- **思维链不落 chat**: reasoning_content 只做实时展示(03§7.4), 不回喂模型上下文, 也不落盘——chat 记录重放即可完整重建 agent 上下文, 思维链不在其中;
- chat 记录**只追加不改写**(meta 行改名除外); 撤销编辑不是删掉 file_edit 行, 而是追加一条 `system/revert` + 实际反向写文件;
- agent 对话上下文由后端从 jsonl 重建(user_message/agent_text/工具与编辑的摘要), 前端渲染与 agent 上下文共用同一份记录, 不存在第二份"给模型看的历史".

### 2.4 todo: 全量快照, 派生状态

`check_todo` / `edit_todo` 两个工具(03§7.4)维护的 agent 计划清单, 数据上遵守和其他记录完全一样的"只追加"规则, 不给 todo 开小灶.

- **每次 `edit_todo` 追加一条完整的 `todo` 记录, 不是差量补丁**——`text` 是这一刻整份清单的全文(一行一项, 非空行必须以 `[ ] ` 或 `[x] ` 开头), 哪怕只是把某一行从未完成勾成完成, 也整份重写一遍. 清单本身通常只有几行字, 重复存多份的空间成本可忽略, 换来的是不需要维护"对某一行打补丁"的逻辑;
- **不单独存"当前状态"**: `GET /chats/{chat_id}` 响应里的 `todo` 字段(无 todo 记录则为 `null`)= 扫描全部记录、取最后一条 `type: todo` 的 `text`. 没有第二份状态需要保持同步, 也就不存在"字段"和"历史"对不上的可能;
- **拒绝改写 meta 行存 todo 的方案**: meta 行长度随 `title` 变化, 每次编辑都要整文件重写(读全部→改第一行→整体写回), 中途崩溃会污染从文件开头起的所有字节, 而不是像追加写那样最坏只丢最后一行; 且与同一轮里其他记录的追加写并发时, 需要额外区分"改头锁"和"追尾锁"两种写入模式. todo 因此必须走追加型记录, 不得走 meta 头;
- **不回喂 G 静态段, 但每步刷新 L 段**: agent 每步 loop 重建动态 L 段, 其中含最新 todo 全文(见 03§7.4); 另靠 `edit_todo` 返回值、对话历史里的 `todo` 记录摘要、或主动 `check_todo`; G 段 prompt 缓存不受影响;
- 用户不直接编辑 todo, 只读展示(想改就是对 agent 说, 走对话); todo 记录不落 .chats/ 以外的任何地方, 天然不进导出/快照(在 .chats/ 目录内, 遵守 §1 的 .chats/ 剔除规则).

## 3. 编辑的应用与撤销语义

- agent 的文件编辑**直接落盘**(Cursor agent 式), 不做"待确认补丁"——单机单人, 撤销比确认流更顺手; 每次编辑都有 file_edit 记录兜底;
- **撤销一次编辑**: 对该 file_edit 的 diff 做反向应用. 仅当文件当前内容与 diff 的"编辑后"一致时可直接撤销; 已被后续修改覆盖时, 前端提示冲突并给出该次编辑前后的对照, 由用户手工处理(v1 不做三方合并);
- 用户手工编辑不产生 .chats/ 记录(chats 只记对话轮次内发生的事); 手工改动与整体回滚的安全网是版本快照(§5), **不用 git**——目标用户不应被要求理解或安装版本管理工具; 高级用户自行对场景目录 `git init` 与本机制互不干扰.

## 4. 对话清单与生命周期

- `GET chats 列表` = 扫描目录, 每项: `{id, title, created_at, updated_at(文件 mtime), turns}`;
- 新建对话: 建空 jsonl(只有 meta 行); 删除对话: 删文件(二次确认); 重命名: 重写 meta;
- 一个场景可有任意多个对话; **同一场景同一时刻只允许一个对话在跑 agent 任务**(全局并发=1, 场景文件是共享资源);
- 内置(readonly)场景不可开对话——先"另存为副本"到用户目录再设计(见 02§1).

## 5. 版本快照(.history/)

给非技术用户的"文档历史版本"心智: 不引 git(二进制或 dulwich 都不引), 快照就是场景内容文件的**完整目录拷贝**——傻、稳、可被用户在文件管理器里直接理解.

### 5.1 快照内容与存储

```
.history/<snap_id>/
├── .meta.yaml       # {id, created_at, kind, reason, chat_id?, turn?, note?}
└── …                # 场景内容文件的原样拷贝(目录结构保持)
```

- **拷贝范围**: 场景包全部内容文件, **不含** `.chats/`、`.history/` 自身、`references/raw/`(转换后的 references/*.md 与 index.yaml 包含在内——它们是场景内容);
- `snap_id` 格式: `<yyyymmddHHMMSS>-<kind>`; 场景包全文本、单份快照通常几百 KB 级, 直接 copytree, 不做增量/压缩;
- `kind` 三种: `auto`(agent 任务前自动)、`manual`(用户存档点, 可附 `note`)、`restore_backup`(执行恢复前对当前状态的自动兜底快照).

### 5.2 触发时机


| 时机                         | kind           | reason 示例                 |
| -------------------------- | -------------- | ------------------------- |
| 每次 agent 任务启动前(即将写文件的唯一入口) | auto           | `对话「席位扩充」第 3 轮之前`         |
| 用户点"保存版本"                  | manual         | 用户填写的 note, 如 `改弧线前`      |
| 用户执行"恢复到某版本"前              | restore_backup | `恢复到 07-12 14:30 之前的自动备份` |


- 手工编辑不逐次触发快照(否则每 800ms 自动保存都产生一份); 手滑场景由"恢复到上一份 auto/manual 快照"兜住, 粒度足够;
- 连续 agent 轮次间若场景文件无任何变化(纯问答轮), 跳过本次 auto 快照, 避免刷屏.

### 5.3 保留策略

- `auto` 与 `restore_backup` 滚动保留最近 **30** 份(合并计数), 超出删最旧;
- `manual` 不参与滚动淘汰, 只能用户显式删除;
- 删除快照只影响 .history/, 与场景内容和 .chats/ 零耦合.

### 5.4 恢复语义

恢复到快照 S = 原子地把场景内容文件区**整体替换**为 S 的内容: S 里有的文件写回, 当前有而 S 里没有的删除(.chats/、.history/、references/raw/ 不动). 执行顺序:

1. 有 agent 任务在跑则拒绝(先中止);
2. 自动创建 `restore_backup` 快照;
3. 替换文件区, 触发结构校验刷新;
4. 恢复操作永远可反悔——刚才的状态就躺在第 2 步的快照里.

恢复不改写 .chats/: 对话历史里的 file_edit 记录可能因此与文件现状脱节, 这是预期行为(那些记录描述的是"当时发生过什么", 不是"现在文件长什么样"); 受影响的只是"撤销该编辑"可能报内容漂移冲突, 已有冲突路径兜住(§3).