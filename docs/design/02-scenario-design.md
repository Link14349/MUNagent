# 02 - 会场设计与场景包格式

> 上级文档: [index.md](index.md) | 相关: [05-agent-harness.md](05-agent-harness.md)(设计Agent的循环), [08-config.md](08-config.md)(MinerU配置)

## 1. 设计流程

向导式+对话式结合, 由**设计Agent**辅助用户逐步完成. 每步: Agent生成草稿 → 用户直接编辑或对话修改 → 确认进入下一步. 步骤间有依赖(席位依赖会场结构), 允许回退, 回退后下游步骤标记`needs_review`.

| 步骤 | 名称 | 输入 | 产出(场景包文件) | 用户交互点 |
|---|---|---|---|---|
| S1 | 主题与历史切入点 | 用户主题 | `manifest.yaml`(部分) | 从候选切入点中选定; 定起始时间与结束条件 |
| S2 | 资料检索与整理 | S1结果 | `references/` | 审阅资料清单, 手工增删 |
| S3 | 背景文书 | references | `background.md` | 编辑/重生成 |
| S4 | 会场结构设计 | S3 | `venues.yaml` | 确定单会场/多分会场、决策规则 |
| S5 | 席位设计 | S4 | `seats/*.yaml` | 逐席位审阅, 特别是秘密目标与权力清单 |
| S6 | 危机弧线设计 | S3-S5 | `crisis_arcs.yaml` | 审阅主线弧与随机事件池 |
| S7 | 数值体系设定(可选) | S5 | `stats.yaml` | 选模式(none/tags/numeric), 审阅数值 |
| S8 | 审查与导出 | 全部 | 检查报告 + 导出zip | 确认检查报告 |

设计进度状态持久化在场景包目录内的`.design_state.yaml`(导出时剔除), 支持中断续做.

## 2. S2资料检索与整理(细化)

设计Agent以**工具调用循环**(function calling)方式工作, 可用工具:

| 工具 | 签名 | 说明 |
|---|---|---|
| `web_search` | `(query, top_k=8) -> [{title,url,snippet}]` | 搜索API, provider可插拔, 默认Tavily(见下"搜索API选型") |
| `fetch_page` | `(url) -> markdown` | 抓取网页正文并转markdown |
| `download_file` | `(url) -> local_path` | 下载文件到`references/raw/`, 限制单文件大小(默认100MB)与总量 |
| `pdf_to_markdown` | `(local_path) -> markdown` | 调用**在线MinerU服务**, 见下 |

工作流: 围绕主题与切入点生成检索计划(若干query) → 搜索并筛选(相关性+来源可信度) → 网页直接抓取、PDF下载后转换 → 每份资料生成一句话摘要 → 写入`references/index.yaml` → 呈现清单给用户增删.

### 搜索API选型
`web_search`统一接口`(query, top_k) -> [{title, url, snippet}]`, provider适配器可插拔, 配置在`tools.search`(见[08-config.md](08-config.md)). 选型结论(2026-07查证):

- **默认Tavily**: AI原生搜索, 返回清洗过的正文片段(部分结果可免去fetch_page), 免费1000次/月且无需信用卡. 用量估算: 一个场景的S2约20~50次搜索, 免费档完全覆盖;
- **备选Serper.dev**: Google结果代理, 量大最便宜($0.3~1/千次), 中文搜索质量好;
- **备选博查(Bocha)**: 国内直连、人民币计费、中文资料覆盖好——Tavily/Serper端点在国内网络不稳时的后路;
- **不用SerpAPI**: 价格贵一个数量级, 且有Google诉讼的长期风险(2025-12);
- key由用户自行注册填入配置, 项目不内置任何key.

### MinerU调用约定
接口细节见[docs/tools/agent-api-pdf-to-markdown-guide.md](../tools/agent-api-pdf-to-markdown-guide.md). 本项目约定:

- 服务地址从配置`tools.mineru.base_url`读取(环境变量`MUNAGENT_MINERU_URL`可覆盖), 默认`http://36.139.151.129:8282`, 见[08-config.md](08-config.md);
- 调用前先打`/health`, 不可用则该PDF标记`convert_failed`, 不阻塞其他资料;
- **统一走异步接口**(`POST /tasks` + 轮询), 3~5秒轮询一次, 简化逻辑且对大文件安全; 参数用文档推荐值(`backend=pipeline, parse_method=auto, lang_list=ch, return_md=true`, 其余false);
- 并发转换限制为4个任务(服务端4卡);
- 转换结果写入`references/<doc_id>.md`, 原PDF留在`references/raw/`;
- v1只做在线服务, 本地MinerU留作后续(接口签名不变, 换实现即可).

## 3. 场景包格式(字段级schema)

场景包为自包含目录(分享时打zip), 全部人类可读可编辑:

```
scenario/
├── manifest.yaml
├── background.md
├── venues.yaml
├── seats/<seat_id>.yaml
├── crisis_arcs.yaml
├── story-design.md          # 可选: 剧情走向与时间线设计(仅主席团可见)
├── stats.yaml
└── references/
    ├── index.yaml
    ├── <doc_id>.md
    └── raw/                 # 原始文件, 默认不随zip分享(控制体积)
```

### manifest.yaml
```yaml
id: cuban-missile-crisis        # 目录内唯一, [a-z0-9-]
title: 古巴导弹危机
author: link
version: 1.0.0
created: 2026-07-11
language: zh
start_story_time: "1962-10-16T09:00:00-04:00"   # 一切时间必须带时区偏移或Z, 加载归一化为UTC(见04§5)
end_conditions:                  # 满足任一即结束, 由主席在每次Crisis Update后评估
  - type: story_time_reached
    at: "1962-11-01T00:00:00Z"
  - type: dm_judgement           # 自然语言条件, DM/主席判断
    desc: "核战争爆发, 或双方达成公开协议解除危机"
```

### venues.yaml
```yaml
venues:
  - id: soviet_politburo
    name: 苏共中央主席团
    kind: sub                    # main | sub (临时会场运行时创建, 不写在场景包)
    timezone: Europe/Moscow      # IANA时区名, 该会场的本地显示时区(见04§5; 内部一律UTC)
    presiding_seat: khrushchev   # 可选: 戏内主持席(见04§3). 不设则由中立主席Agent主持
    decision_rule:
      pass_threshold: majority   # majority | two_thirds | unanimous
      veto_seats: [khrushchev]   # 可为空
      # 计票口径(见04§3计票规则明细): 分母按"到会且投票"计, 弃权不入分母;
      # 平票/全体弃权不通过; veto席位投nay直接否决, 弃权不构成否决; 公开唱票.
    initial_agenda: 对美国海上封锁的回应
    initial_phase: ModeratedCaucus
    seats: [khrushchev, gromyko, malinovsky]
    clock_rate:                  # 前场活动消耗故事时间的默认速率(可省略用全局默认)
      per_mod_speech: 5m
      per_unmod_round: 15m
```

### seats/<seat_id>.yaml
```yaml
id: gromyko
name: 安德烈·葛罗米柯
venue: soviet_politburo
public:                          # 全体可见
  title: 苏联外交部长
  faction: 温和派
  stance: 主张外交解决, 避免直接军事对抗
private:                         # 仅本席位+主席团可见
  secret_goals:
    - 避免苏联在国际上颜面尽失的前提下促成撤弹
  relationships:
    - { seat: khrushchev, attitude: 忠诚但暗中担忧其冒进 }
  resources:
    - 与美国国务院的秘密沟通渠道
portfolio_powers:                # 个人指令合法性判定依据
  - power: 指挥苏联驻外使领馆进行外交接触
    limits: 不能代表苏共中央做最终承诺
persona:                         # 供代表Agent扮演
  personality: 谨慎、克制、精于辞令
  speech_style: 正式、外交辞令、少有情绪外露
  decision_tendency: 风险厌恶, 倾向拖延与模糊表态
  honesty: 0.7                   # 0~1, 见05中的prompt映射
```

### story-design.md (可选, 仅主席团可见)
剧情走向与时间线设计的人类可读版: 主要剧情走向(若干条参考线, 各含触发倾向/关键节拍/DM导航建议)、
时间线关键节点表、主席跳时指引. **是导航图不是剧本**——注入DM与中立主席的G段, 代表不可见.

### crisis_arcs.yaml (仅主席团可见)
```yaml
main_arc:
  - id: u2_shot_down
    trigger:
      type: story_time           # story_time | condition | manual
      at: "1962-10-27T10:00:00-04:00"  # type=story_time时; 必须带时区偏移, 可按当地时间书写
      condition: null            # type=condition时为自然语言条件, DM在每次弧线检查时评估
    content: |
      一架U-2侦察机在古巴上空被萨姆导弹击落, 飞行员安德森少校丧生...
    default_scope: global        # 播报建议, 主席可改
random_pool:                     # DM可在节奏需要时抽取
  - id: press_leak
    weight: 3
    content: 美国记者披露了海军拦截行动的细节...
timeline:                        # 故事时间关键节点(机器可读): 主席跳时依据, DM推算生效时刻的参照
  - at: "1962-10-24T10:00:00-04:00"
    label: 封锁线正式生效
    note: 在此之前抵近的船只将直接对峙
```

### stats.yaml
```yaml
mode: tags                       # none | tags | numeric (决策D2: 默认tags)
visibility: faction            # owner_only | faction | all_public; 默认faction(决策D15)
entities:
  - id: ussr_military
    label: 苏联军事力量
    owner: faction:苏联           # faction:<名> | seat:<id>
    tags: { 常规力量: 强, 核力量: 强, 古巴当地防空: 中 }
    # numeric模式则为 values: { 常规力量: 85, ... }
```

**`visibility`口径**(决定代表Agent上下文注入哪些条目, DM/主席团始终完整可见):

| 值 | 席位可见范围 | 例子 |
|---|---|---|
| `owner_only` | 仅`owner`匹配本席位的条目 | `owner: seat:gromyko`只有葛罗米柯可见 |
| `faction`(默认) | 本席位`public.faction`与`owner: faction:<名>`匹配的条目 + `owner: seat:<本席位>` | 苏联阵营三人共享`ussr_military`, 看不见美军条目 |
| `all_public` | 全部entities | 各方军力对所有人公开, 像Background Guide情报 |

省略`visibility`字段时按`faction`处理. 过滤在服务端`scenario.stats_for_seat(seat_id)`实现, 与`bus.query`同属视角隔离逻辑.

### references/index.yaml
```yaml
docs:
  - id: ref_001
    title: Essence of Decision (节选)
    source_url: https://...
    retrieved: "2026-07-11"
    original_file: raw/essence.pdf   # 无原始文件(网页抓取)则省略
    converted_by: mineru-online      # mineru-online | fetch_page | manual
    summary: 古巴导弹危机决策过程的经典分析
```

## 4. 可见性映射(文件→运行时)

| 文件/字段 | 注入对象 |
|---|---|
| `background.md`(摘要) | 所有Agent的固定层上下文 |
| `seats/*.yaml` public | 全体 |
| `seats/*.yaml` private/persona | 仅对应代表Agent + 主席团 |
| `crisis_arcs.yaml` | 仅DM与主席 |
| `stats.yaml` | DM/主席团完整可见; 代表按`visibility`过滤后注入L1(见上表) |
| `references/` | 设计阶段供设计Agent; 推演阶段默认不注入(避免上下文爆炸), DM判定时可按需检索 |

## 5. S8一致性检查清单
设计Agent逐项检查并生成报告(每项: 通过/警告/错误):

1. 引用完整性: 席位引用的venue存在; veto_seats/弧线中提到的席位存在; stats的owner存在;
2. 结构合理性: 每个会场≥2个席位; 至少一个会场; 决策规则与席位数不矛盾(如3席位配two_thirds);
3. 权力一致性: portfolio_powers与会场结构、其他席位权力无直接矛盾(如两人都"独家"指挥同一支部队);
4. 可推演性: 秘密目标不存在全体死锁(所有人的目标互斥到没有任何行动空间); 主线弧触发时间落在推演时间窗内;
5. 格式校验: 全部yaml通过schema校验(pydantic model); 一切时间字段必须带时区偏移或`Z`(裸时间串报错), venue的`timezone`必须是合法IANA名(见04§5); `stats.visibility`若存在必须是`owner_only|faction|all_public`之一.
