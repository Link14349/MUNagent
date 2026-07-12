# AGENTS.md — 对AI编码Agent的约束

本文件约束一切在本仓库工作的AI Agent. 与用户明确指示冲突时以用户指示为准, 其余情况本文件必须遵守.

## 项目一句话
MUNagent: 基于LLM Agent的模拟联合国历史委员会(危机联动)场景设计&推演工具. Python + FastAPI + SQLite + 网页GUI, LLM走OpenAI兼容协议(默认DeepSeek).

## 文档体系与优先级

```
introduction.md          顶层概览(给人快速了解用)
docs/design/index.md     设计文档索引 ← 动手前从这里进
docs/design/01~11-*.md   分主题详细设计 ← 唯一权威
plan.md                  分阶段开发计划(可执行任务清单)
docs/api/                各模块接口文档(随代码维护, 见"API文档维护")
docs/tools/*.md          外部工具服务的调用文档
```

- **冲突时以`docs/design/`为准**, 并回头修订introduction.md;
- 写任何代码前, 先读index.md中对应主题的设计文档; 实现与设计不一致时, 停下来问用户, 不要自作主张二选一;
- 修改设计时**必须同步**: 相关设计文档 + index.md(若结构变化) + introduction.md(若顶层概览受影响) + plan.md(若任务受影响).

## 不可擅自违反的已定决策(D1~D17)
完整表见[docs/design/01-overview.md](docs/design/01-overview.md). 速记: 单机单人 / 数值默认粗粒度标签 / stats可见性默认faction可配 / 允许说谎但有honesty参数 / Unmod小轮+屏障 / 前后场双轨 / LLM不掷骰 / 事件溯源 / 在线MinerU / 不用LangChain / 缓存优先的上下文组装 / UTC单轴+会场timezone / 最小步事件缓冲提交 / Thinking按task开关 / 公报一律投票+master_seed可--seed / 戏内主持席与戏外主席分离(允许偏心, appeal终裁, 主持权可易手) / 指令草案线模型(编号程序分配, 外人修订自动fork, 一版通过其余作废). **变更任何一条需用户明确确认.**

## 跨文档不变量(写代码时的硬约束)
1. **一切皆事件, 事件即存档**: 任何运行时状态必须可由事件流重建; 引擎禁止持有不落事件的隐藏状态;
2. **可见性过滤只有一份实现**: Agent上下文与前端推送共用`bus.query(viewer)`, 过滤在服务端; scope共六级(global/venue/group/private/dm-only/self), self事件连主席团Agent都不可见;
3. **LLM不掷骰子**: 一切随机性走程序RNG, seed可复现并记入事件;
4. **key不进事件日志、不回传前端**: 错误信息落地前脱敏; 场景包/存档导出与配置系统零代码交集;
5. **人类与AI走同一个ActionProvider抽象**: 不为人类单开分支逻辑;
6. **prompt只从尾部生长**: 易变内容只许在L4任务段; 事件渲染`render(event)`是纯函数且字节级确定, 改渲染模板=破坏性变更, 需golden测试护住.
7. **最小步事件缓冲提交**: `stage`在步内缓冲, `commit_step`批量落库; 步失败`rollback_step`, 禁止孤儿事件.

## 代码规范
- Python 3.11+, 类型标注全覆盖, pydantic v2做一切schema(事件/配置/Agent输出/场景包);
- asyncio并发; 模块划分严格按[01-overview.md](docs/design/01-overview.md)的目录图, 不擅自新建顶层模块;
- **模块化与解耦**: 按功能域切分为共享层(config/security/llm/scenario) + 两个子系统(designer/deducer), 各模块职责单一、边界清晰, 模块间只通过显式接口(公开函数/类/事件总线)交互, 禁止跨模块伸手拿内部状态; 依赖方向: **designer 与 deducer 互不依赖**, 两者都只依赖共享层; deducer 内部 server→engine→agents→core; 反向禁止; 能通过事件总线解耦的交互不要直接函数调用耦合;
- 不引入LangChain/LlamaIndex等重框架; 新增第三方依赖前先问用户;
- 注释与文档字符串写"为什么", 不写"是什么"; 保持与现有代码风格一致.

## API文档维护
- `docs/api/`下按模块维护接口文档(如`docs/api/core-events.md`), **简要**记录该模块/文件对外暴露的主要接口: 签名、一句话功能、关键约束(如"emit必须经单写者"); 不复制实现细节, 不与docstring逐字重复;
- 新增/修改/删除公开接口时, 同一次提交内同步对应api文档; 只有内部实现变化则不用动;
- api文档是"地图"不是"说明书"——让下一个Agent能在30秒内知道该调哪个函数、去哪个文件看细节.

## 进度确认
- 完成plan.md中的一项任务, 就在对应复选框打勾(`- [x]`), 与代码同一次提交;
- 一个阶段全部任务勾完且验收标准通过后, 在该阶段标题后追加`✅(日期)`; 验收未过不许标记;
- 发现plan.md任务与实际实现出现偏差时, 更新任务描述并在旁注明原因, 不要默默跳过.

## 测试要求
- 事件渲染: golden字节级比对测试;
- reducer(事件流→状态)与掷骰: 给定seed的确定性回归测试;
- 可见性过滤: 每种scope×每类viewer的矩阵用例(泄漏=最高级bug);
- 结构化输出解析: 各Agent输出schema的合法/非法样例;
- LLM调用一律mock, 测试不打真实API.

## 安全与卫生
- 严禁提交: api key、`config.local.yaml`、`~/.munagent/`内容、`.env`、真实推演存档中含key的任何东西;
- MinerU等内网服务地址不硬编码, 走配置(见[08-config.md](docs/design/08-config.md));
- debug落盘的完整prompt(含席位私密信息)默认关闭, 且路径在.gitignore内.

## 文风约定
- 文档/注释使用中文, 半角标点(遵循现有文档风格);
- 提交信息: 一行中文概括, 说明动了哪个模块/文档;
- 用户可见的字符串(GUI/CLI输出)使用中文.
