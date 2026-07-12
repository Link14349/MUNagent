# MUNagent 分阶段开发计划

> 本文件是[docs/design/10-roadmap.md](docs/design/10-roadmap.md)的可执行任务分解. 每阶段: 目标→任务清单→验收标准→风险. 任务后括号标注对应设计文档章节. 完成一项勾一项; 阶段内任务大体按依赖排序.
>
> 每阶段: 目标 → 任务清单 → 验收标准. 任务后括号标注对应设计文档章节. 完成一项勾一项.
>
> 全局完成定义(DoD): 代码有类型标注与测试 / 相关设计文档已同步 / 不违反 AGENTS.md 不变量.

## P0 - 项目脚手架 ✅(2026-07-12)

**目标**: 空仓库 → 可安装、可配置、可调通一次 LLM 的骨架.

- [x] pyproject.toml: 包名 munagent, Python 3.11+, 依赖(fastapi, uvicorn, pydantic v2, pydantic-settings, httpx, pyyaml, aiosqlite, pytest, pytest-asyncio)
- [x] 按模块图建包骨架, 全部空模块 + docstring (01#代码模块划分)
- [x] 配置系统: pydantic-settings 三层加载(env > ~/.munagent/config.yaml > 默认), chmod 600 写入 (08§1-2)
- [x] LLM 调用层: OpenAI 兼容异步客户端, provider 档案 + 角色路由, thinking 按角色/task 开关(05§5), 重试/超时, usage 记录接口(含 cache_hit/miss_tokens/thinking_enabled) (05§5, 08§2, 11§5)
- [x] key 脱敏工具函数: 日志/异常文本过滤器, 单元测试 (08§3)
- [x] CLI 入口: `munagent config-test`(provider 连通性), `munagent version`
- [x] pytest 骨架 + LLM mock fixture (AGENTS.md 测试要求)
- [x] .gitignore 补全: config.local.yaml, .env, *.db, debug_prompts/

**验收**: `pip install -e .` 后 `munagent config-test` 对真实 DeepSeek key 返回成功; 全部测试绿.

## P1 - 网页 GUI 骨架 [= 前端基础设施] ✅(2026-07-12)

**目标**: 浏览器能打开应用, 完成配置与场景包库管理, 为设计工作台与推演大厅打底.

- [x] FastAPI 应用骨架 + CORS/静态托管 (09§2)
- [x] 前端脚手架(Vue3 + Vite + TypeScript), 构建产物由 FastAPI 托管
- [x] 设置页: providers/roles/tools 编辑(key 掩码只写不读) + 测试连接 (08§3-4, 09§2)
- [x] 首页: 场景包库列表(内置示例 + 用户目录) + 新建设计/开始推演入口占位 (09§1)
- [x] REST: `GET/POST /api/scenarios`, `GET/PUT/DELETE /api/scenarios/{id}`, `GET/PUT /api/config`, `POST /api/config/test` (09§2)
- [x] `core/scenario.py`: 场景包加载 + pydantic 校验 + 保存(不含设计 Agent, 先支持手工/示例场景) (02§3)
- [x] 内置示例场景 `scenarios/cabinet-crisis/` 可被 API 列出并读取
- [x] CLI: `munagent serve` 一键拉起后端 + 静态前端

**验收**: 浏览器打开首页可见示例场景; 设置页写入 key 并测试连接成功; 无需推演引擎即可浏览场景包各文件.

## P2 - 会场设计器 [= 原 M5, 提前]

**目标**: 从一句话主题经设计 Agent 产出可校验、可推演的场景包, 并在设计工作台中完成人机协作.

- [ ] tools/: web_search + fetch_page + download_file(大小限制) (02§2)
- [ ] MinerU 客户端: /health 检查, 异步任务 + 轮询, 并发 ≤4, 失败标记不阻塞 (02§2, docs/tools/)
- [ ] DesignerAgent: 工具调用循环(function calling, 单步骤上限 30 次) (05§1, §3.5)
- [ ] 设计步骤 S1~S8 各自的 task 与产出写入; `.design_state.yaml` 断点续做 (02§1)
- [ ] references/ 管理: index.yaml, raw/ 隔离, 导出时剔除 raw 与 design_state (02§3)
- [ ] 一致性检查五类 + 报告 (02§5)
- [ ] 场景包导入/导出(zip)
- [ ] REST: `POST /api/scenarios/{id}/design/{step}`, `POST .../export`, `POST .../import` (09§2)
- [ ] 设计工作台前端: 步骤导航 / 表单编辑 + 草稿 diff / Agent 对话栏 / S2 资料清单 (09§1)

**验收**: 浏览器中从一句话主题出发, 30 分钟内(含人工确认)产出通过校验且字段完整的场景包; references ≥5 份转换成功.

## P3 - 最小推演内核(CLI) [= 原 M1]

**目标**: 单会场 · 三席位 · 手写或 P2 产出场景, CLI 跑通「点名发言 → 个人指令 → 判定 → Crisis Update」闭环.

- [ ] Event 模型 + 六级 scope + visible_to 物化规则 (03§2-4)
- [ ] EventBus: stage/commit_step/rollback_step 单写者串行化/seq 全序/query(viewer)/subscribe (03§5, 决策 D12)
- [ ] SQLite 持久化: sessions/events/llm_usage 三表, 事务按最小步提交 (03§6, 07§2)
- [ ] 事件渲染器 render(event): 纯函数, golden 字节级测试 (11§4)
- [ ] 可见性过滤矩阵测试: 6 scope × {代表本人/其他代表/主席团/god} (03§4)
- [ ] BaseAgent 循环: 上下文组装 + json 解析 + 修复重试 + fallback 表 (05§1)
- [ ] DelegateAgent 最小版: turn 任务(speech/write_directive/pass), inner_thought 拆 self 事件 (05§3.1, 03§3)
- [ ] ChairAgent 最小版: next_speaker + broadcast_decision 简化版 (05§3.2)
- [ ] DMAgent 最小版: 判定五步中的 ②④(LLM) + ③ 程序掷骰(seed=hash(master_seed, directive_id)) (06§3)
- [ ] 单会场状态机: Opening → ModCaucus → Adjourned, 点名 + 保底轮询 (04§3)
- [ ] CLI 运行器: `munagent run <scenario> --max-steps N [--seed <int>]`, 彩色输出事件流
- [ ] 回放脚本: `munagent replay <session> --viewpoint seat:x|god` (03§8)

**验收**: 全 AI 跑 ≥3 轮闭环; 回放按视角过滤正确; 同一 master_seed 两次运行掷骰结果一致.

## P4 - 完整会议机制 [= 原 M2]

**目标**: 单会场下所有会议机制完整可用, 断点续推可靠.

- [ ] 前场状态机完整: 全状态 + 转移表, 主席 phase_decision (04§3)
- [ ] 戏内主持席: DelegateAgent 主持任务 + ChairAgent appeal 终裁 + presiding_change 事件 (04§3, 05§3.1-3.2, D15)
- [ ] Voting 子流程: 动议 → 受理 → 冻结 → 逐席位投票 → decision_rule 计票(veto) → 返回原阶段 (04§3)
- [ ] Unmod: initial_grouping → 小轮并行 → next_move 收集 → 屏障固定顺序结算 (04§3)
- [ ] 闭门小组: closed 标记, quick_decide, join_request/decision 事件 (04§3, 05§3.1)
- [ ] 四类指令全生命周期 + directive_status 事件 (06§1-2)
- [ ] 草案线模型: 编号/fork/diff/superseded (06§2, D16)
- [ ] 判定流水线完整五步 + 危机笔记送达与截获 (06§3, §5)
- [ ] RecorderAgent: 章节追加摘要 + 纪元机制 (05§3.4, 11§3)
- [ ] G 段拆分与预热; llm_usage 命中率 per role (11§2, §5-6)
- [ ] 推演时钟: clock_rate 累加 / clock_advance / takes_effect_at (04§5)
- [ ] 阶段预算 + 会话 token 熔断 + 单 Agent 连续失败暂停 (04§6, 07§5)
- [ ] core/reducer.py: RuntimeState + apply/reduce, 断点续推 (03§7, 07§2)
- [ ] reducer 确定性测试 + Prompt 质量改进(见 prompt-analysis.md)
- [ ] 时区本地显示: story_time 按 venue.timezone 渲染 (04§5)

**验收**: 手写或 P2 产出场景全 AI 推演 30 分钟不失控; kill 进程后续推无缝衔接; 第二纪元起缓存命中率 >60%(记录基线).

## P5 - 多会场 [= 原 M3]

**目标**: 双会场并行 + 跨会场交互, 古巴导弹危机示例跑通.

- [ ] 多 venue_loop 并行 + 跨会场共享状态免锁规则 (07§1, §3)
- [ ] backroom_loop / interrupt_loop 独立协程化 (07§1)
- [ ] 临时会场: 创建/借出/归还/解散 (04§1)
- [ ] Crisis Update 按会场定制/延迟/扣发 (05§3.2, 06§2)
- [ ] 危机弧线: story_time 触发 + condition 型 DM 评估 + 随机事件池 (04§4, 02§3)
- [ ] 时序冲突对抗性复判 (06§4)
- [ ] end_conditions 评估 (07§7)
- [ ] 手写古巴导弹危机场景包(双会场, P6 精修)

**验收**: 双会场完整危机推演, 含 ≥1 次跨会场指令与 ≥1 次临时会场谈判; god/单席位双视角回放正确.

## P6 - 推演 GUI [= 原 M4 推演侧, 接在引擎之后]

**目标**: 把 P3~P5 的推演能力接入浏览器: 观察 → 复盘 → 导演 → 玩家.

- [ ] REST: sessions CRUD + control(run/pause/step/end) + events 拉取 + export.md (09§2)
- [ ] WS 协议: subscribe / event 推送 / action_request / session_state / 断线 since_seq 补拉 (09§3)
- [ ] 推演大厅-观察模式: 时间线/会场标签/席位列表/指令追踪/时钟与用量 (09§1)
- [ ] Unmod 分组视图 (09§1)
- [ ] 复盘页: seq 拖动/视角切换/指令链路/导出 markdown (09§1)
- [ ] 导演模式: 主席团控制台 + draft_review 草稿审改 (09§1, §3)
- [ ] 玩家模式: HumanProvider + 超时 fallback; 视角锁定 (07§4, 09§3-4)
- [ ] 用量面板: token/费用/缓存命中率曲线 per role (11§5)

**验收**: 浏览器观察一场全 AI 推演并复盘导出 md; 人类接管 1 席位完整打完一场.

## P7 - 打磨发布 [= 原 M6]

**目标**: 新用户 10 分钟跑起示例.

- [ ] 内置精修示例场景 ×2(古巴导弹危机/法国1848)
- [ ] 可观测面板: 解析失败率 per role, 命中率异常告警 (07§6, 11§5)
- [ ] 首次启动引导(配 key → 测试 → 设计或跑示例)
- [ ] README 重写: 安装/快速开始/截图; 文档与实现对齐
- [ ] 同步修订 introduction.md 与 10-roadmap.md(开发顺序变更)

**验收**: 干净机器从 clone 到「设计一个场景」或「观看示例推演」≤10 分钟.

## 里程碑依赖

```
P0 → P1 → P2 ─────────────────────────────→ P7
              ↘
               P3 → P4 → P5 → P6 ────────────↗
```

- **P1/P2** 可并行少量 P0 收尾, 但 LLM 层与 scenario 校验应在 P2 前就绪.
- **P3** 依赖 P0; 场景包可用 P2 产出或 `scenarios/cabinet-crisis/`.
- **P6** 依赖 P4(至少 P3 最小闭环); **P5** 可与 P6 部分并行.
- **P7** 收尾, 依赖 P2 + P6 至少各完成验收.

## 全程风险清单

| 风险 | 缓解 |
|---|---|
| 设计器先做、场景包格式后期变动 | P2 验收即冻结 v1 schema; P3 起改动走版本号 + 迁移 |
| flash 结构化输出失败率高 | P2/P3 起建立解析失败率统计; 高则简化 schema 或升 pro |
| 推演质量「演不像」 | P4 起留人工评估; 调 persona 与 honesty 映射 |
| 缓存命中率不及预期 | P4 验收记录基线; golden 测试护住 render 确定性 |
| Unmod 屏障时序 bug | 屏障结算纯函数化 + property-based 测试 |
| 前端工作量失控 | P1 只读库 + 设置; P2 设计台; P6 再接推演交互, 逐模式加 |
