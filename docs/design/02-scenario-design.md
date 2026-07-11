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
| `web_search` | `(query, top_k=8) -> [{title,url,snippet}]` | 搜索引擎API, provider可配置 |
| `fetch_page` | `(url) -> markdown` | 抓取网页正文并转markdown |
| `download_file` | `(url) -> local_path` | 下载文件到`references/raw/`, 限制单文件大小(默认100MB)与总量 |
| `pdf_to_markdown` | `(local_path) -> markdown` | 调用**在线MinerU服务**, 见下 |

工作流: 围绕主题与切入点生成检索计划(若干query) → 搜索并筛选(相关性+来源可信度) → 网页直接抓取、PDF下载后转换 → 每份资料生成一句话摘要 → 写入`references/index.yaml` → 呈现清单给用户增删.

### MinerU调用约定
接口细节见[docs/tools/agent-api-pdf-to-markdown-guide.md](../tools/agent-api-pdf-to-markdown-guide.md). 本项目约定:

- 服务地址从配置`tools.mineru.base_url`读取(环境变量`MUNAGENT_MINERU_URL`可覆盖), 见[08-config.md](08-config.md);
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
start_story_time: "1962-10-16T09:00:00"
end_conditions:                  # 满足任一即结束, 由主席在每次Crisis Update后评估
  - type: story_time_reached
    at: "1962-11-01T00:00:00"
  - type: dm_judgement           # 自然语言条件, DM/主席判断
    desc: "核战争爆发, 或双方达成公开协议解除危机"
```

### venues.yaml
```yaml
venues:
  - id: soviet_politburo
    name: 苏共中央主席团
    kind: sub                    # main | sub (临时会场运行时创建, 不写在场景包)
    decision_rule:
      pass_threshold: majority   # majority | two_thirds | unanimous
      veto_seats: [khrushchev]   # 可为空
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

### crisis_arcs.yaml (仅主席团可见)
```yaml
main_arc:
  - id: u2_shot_down
    trigger:
      type: story_time           # story_time | condition | manual
      at: "1962-10-27T10:00:00"  # type=story_time时
      condition: null            # type=condition时为自然语言条件, DM在每次弧线检查时评估
    content: |
      一架U-2侦察机在古巴上空被萨姆导弹击落, 飞行员安德森少校丧生...
    default_scope: global        # 播报建议, 主席可改
random_pool:                     # DM可在节奏需要时抽取
  - id: press_leak
    weight: 3
    content: 美国记者披露了海军拦截行动的细节...
```

### stats.yaml
```yaml
mode: tags                       # none | tags | numeric (决策D2: 默认tags)
entities:
  - id: ussr_military
    label: 苏联军事力量
    owner: faction:苏联           # faction:<名> | seat:<id>
    tags: { 常规力量: 强, 核力量: 强, 古巴当地防空: 中 }
    # numeric模式则为 values: { 常规力量: 85, ... }
```

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
| `stats.yaml` | DM完整可见; 各席位仅见自己owner的条目(设计可配) |
| `references/` | 设计阶段供设计Agent; 推演阶段默认不注入(避免上下文爆炸), DM判定时可按需检索 |

## 5. S8一致性检查清单
设计Agent逐项检查并生成报告(每项: 通过/警告/错误):

1. 引用完整性: 席位引用的venue存在; veto_seats/弧线中提到的席位存在; stats的owner存在;
2. 结构合理性: 每个会场≥2个席位; 至少一个会场; 决策规则与席位数不矛盾(如3席位配two_thirds);
3. 权力一致性: portfolio_powers与会场结构、其他席位权力无直接矛盾(如两人都"独家"指挥同一支部队);
4. 可推演性: 秘密目标不存在全体死锁(所有人的目标互斥到没有任何行动空间); 主线弧触发时间落在推演时间窗内;
5. 格式校验: 全部yaml通过schema校验(pydantic model).
