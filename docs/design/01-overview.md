# 01 - 总览与核心概念

> 上级文档: [index.md](index.md) | 顶层概览: [introduction.md](../../introduction.md)

## 项目定位
MUNagent是基于LLM Agent的自动化模拟联合国场景设计&推演工具, 主要针对模联**历史委员会(危机联动)**场景. Python实现, 网页GUI交互, LLM默认走DeepSeek(OpenAI兼容协议, 可换任意兼容端点).

两大核心能力:

1. **会场设计**: 从历史主题出发, 设计Agent辅助生成完整会场设定, 导出可复用、可分享的**场景包**. 详见[02-scenario-design.md](02-scenario-design.md).
2. **会场推演**: 加载场景包, 代表Agent扮演席位开会, 主席团Agent控场与裁决, 完成完整危机联动推演. 支持纯AI观察模式与人类混合参与. 详见[04-state-machine.md](04-state-machine.md)、[07-engine.md](07-engine.md).

## 术语表

| 术语 | 英文/代码名 | 含义 |
|---|---|---|
| 场景包 | Scenario | 一次推演所需全部设定的自包含目录(yaml+md) |
| 会场 | Venue | 一个议事空间(总会场/分会场/临时会场), 各持一个状态机 |
| 席位 | Seat | 一个可扮演的角色(历史人物), 由代表Agent或人类扮演 |
| 代表Agent | DelegateAgent | 扮演席位的LLM Agent |
| 主席团 | Presidium | 主席(Chair)+DM+书记(Recorder)三个控场Agent, 即introduction中的"推演Agent" |
| 主持席 | presiding seat | 可选的**戏内**会议主持, 由某代表席位担任(如总理/议长), 带立场主持程序, 允许偏心; 与戏外中立主席分离, 见04§3 |
| DM | DMAgent | 危机导演, 处理指令判定与结果撰写 |
| 前场轨 | frontstage | 会场内的辩论状态机(主持磋商⇄非正式磋商, 投票为子流程) |
| 后场轨 | backroom | 持续运行的指令判定流水线(队列) |
| Crisis Update | crisis_update | 主席插入的广播中断, 可抢占前场任意阶段 |
| 小轮/屏障 | mini-round / barrier | 非正式磋商的调度单位; 屏障处统一结算换组 |
| 事件 | Event | 系统中一切行为的统一记录单位, 带可见范围 |
| 可见范围 | scope | global/venue/group/private/dm-only/self六级 |
| 推演时钟 | story clock | 故事内时间, 与真实时间解耦 |
| 指令 | directive / personal / communique / crisis_note | 代表的四类行动文书, 见[06-directives-adjudication.md](06-directives-adjudication.md) |
| 权力清单 | Portfolio Powers | 席位凭个人身份可动用的权力, 个人指令合法性依据 |
| 诚信倾向 | honesty | 人格卡参数(0~1), 控制该Agent说谎/背刺的倾向 |

## 已定决策(设计约束)

| # | 决策 | 影响 |
|---|---|---|
| D1 | v1单机单人(一人可控多席位), 不做多人在线 | 无用户/席位认领机制, 无鉴权体系 |
| D2 | 数值体系默认"粗粒度标签+DM裁量", 精确数值为可选模式 | stats.yaml的`mode`字段, 见02/06 |
| D3 | 允许代表Agent说谎/隐瞒, 人格卡带诚信倾向参数 | seat schema含`honesty`, 见05 |
| D4 | 非正式磋商用"小轮+屏障"动态分组, 含闭门小组 | 见04 |
| D5 | 前场/后场双轨模型, Crisis Update为中断事件 | 见04 |
| D6 | LLM评概率+写叙述, 程序掷骰子 | 见06 |
| D7 | 事件溯源: 事件日志即存档, 回放不重调LLM | 见03 |
| D8 | PDF转Markdown用在线MinerU服务, 本地部署留作后续 | 见02/08 |
| D9 | 不引入LangChain等重框架, 自研轻量Agent循环 | 见05 |
| D10 | 上下文组装以前缀缓存命中为一等约束: 五段结构+纪元机制+渲染确定性 | 见11 |
| D11 | 故事时间内部一律UTC单轴, 会场`timezone`仅作本地渲染 | 见04§5 |
| D12 | 事件`emit`在最小步内缓冲, 步结束`commit`落库 | 见03§5, 07§2 |
| D13 | V4 Thinking按角色/task开关(代表Unmod组内关, `write_directive`一律开) | 见05§5 |
| D14 | 公报一律需投票; `master_seed`默认随机, CLI可`--seed`复现 | 见06§1, 07§7 |
| D15 | 戏内主持席与戏外主席分离: `presiding_seat`可选、允许偏心、appeal由戏外主席终裁、主持权可易手 | 见04§3 |
| D16 | 联合指令/公报按"草案线"管理(git式): 编号程序分配、修订权=联署集团、外人修订自动fork、表决用编号、一版通过同议程其余superseded | 见06§2 |
| D17 | stats席位可见性可配置, 默认`faction`(同阵营共享) | 见02§3 stats.yaml |

## 技术选型

| 层 | 选型 | 说明 |
|---|---|---|
| 后端 | Python 3.11+, FastAPI + WebSocket | 事件实时推送, asyncio驱动Agent并发 |
| 前端 | Vue3 + Vite + TypeScript SPA | 构建产物由FastAPI静态托管 |
| 持久化 | SQLite | 单文件零部署; 核心是事件日志表 |
| LLM | OpenAI兼容客户端 | 默认`deepseek-v4-flash`/`deepseek-v4-pro`, Provider档案+角色路由, 见[08-config.md](08-config.md) |
| Agent | 自研轻量循环 | 复杂度在编排(状态机+事件总线)而非单Agent推理 |
| 工具 | 联网搜索/下载/在线MinerU | 仅设计Agent使用, 见02 |

## 代码模块划分

```
munagent/
├── core/
│   ├── events.py        # 事件模型与事件总线(scope过滤、持久化)     → 03
│   ├── reducer.py       # RuntimeState + 事件折叠(在线维护/续推重建) → 03§7
│   ├── state_machine.py # 会场状态机(前场轨)                        → 04
│   ├── clock.py         # 推演时钟(故事内时间)                      → 04
│   └── scenario.py      # 场景包的加载/校验/保存                    → 02
├── agents/
│   ├── base.py          # Agent基类: 上下文组装、结构化输出、重试    → 05
│   ├── delegate.py      # 代表Agent                                → 05
│   ├── chair.py         # 主席Agent                                → 05
│   ├── dm.py            # DM Agent(判定流水线)                     → 05/06
│   ├── recorder.py      # 书记Agent(滚动摘要)                      → 05
│   └── designer.py      # 会场设计Agent                            → 02
├── llm/                 # OpenAI兼容客户端、模型路由、用量统计       → 08
├── tools/               # 联网搜索、文件下载、MinerU客户端           → 02/08
├── engine.py            # 推演引擎: 主循环、并发调度、人类挂点       → 07
├── server/              # FastAPI: REST + WebSocket                → 09
└── web/                 # 前端                                     → 09
```

箭头指向对应设计文档编号.
