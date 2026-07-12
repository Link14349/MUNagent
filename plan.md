# MUNagent 分阶段开发计划

> 本文件是[docs/design/10-roadmap.md](docs/design/10-roadmap.md)的可执行任务分解. 每阶段: 目标→任务清单→验收标准→风险. 任务后括号标注对应设计文档章节. 完成一项勾一项; 阶段内任务大体按依赖排序.
>
> 全局完成定义(DoD): 代码有类型标注与测试 / 相关设计文档已同步 / 不违反AGENTS.md不变量.

## P0 - 项目脚手架 ✅(2026-07-12)

**目标**: 空仓库 → 可安装、可配置、可调通一次LLM的骨架.

- [x] pyproject.toml: 包名munagent, Python 3.11+, 依赖(fastapi, uvicorn, pydantic v2, pydantic-settings, httpx, pyyaml, pytest, pytest-asyncio)
- [x] 按模块图建包骨架, 全部空模块+docstring (01#代码模块划分)
- [x] 配置系统: pydantic-settings三层加载(env > ~/.munagent/config.yaml > 默认), chmod 600写入 (08§1-2)
- [x] LLM调用层: OpenAI兼容异步客户端, provider档案+角色路由, thinking按角色/task开关(05§5), 重试/超时, usage记录接口(含cache_hit/miss_tokens/thinking_enabled字段) (05§5, 08§2, 11§5)
- [x] key脱敏工具函数: 日志/异常文本过滤器, 单元测试 (08§3)
- [x] CLI入口: `munagent config-test`(provider连通性), `munagent version`
- [x] pytest骨架 + LLM mock fixture (AGENTS.md测试要求)
- [x] .gitignore补全: config.local.yaml, .env, *.db, debug_prompts/

**验收**: `pip install -e .`后`munagent config-test`对真实DeepSeek key返回成功; 全部测试绿.

## P1 - 最小推演内核(CLI) [=M1] ✅(2026-07-12)

**目标**: 单会场·三席位·硬编码场景, CLI跑通"点名发言→个人指令→判定→Crisis Update"闭环.

- [x] Event模型 + 六级scope + visible_to物化规则 (03§2-4)
- [x] EventBus: stage/commit_step/rollback_step单写者串行化/seq全序/query(viewer)/subscribe (03§5, 决策D12)
- [x] SQLite持久化: sessions/events/llm_usage三表, 事务按最小步提交 (03§6, 07§2)
- [x] 事件渲染器render(event): 纯函数, golden字节级测试 (11§4)
- [x] 可见性过滤矩阵测试: 6 scope × {代表本人/其他代表/主席团/god} (03§4)
- [x] BaseAgent循环: 五段上下文组装(G/L1/L2stub/L3/L4)+json解析+修复重试+fallback表 (05§1-2)
- [x] DelegateAgent最小版: turn任务(speech/write_directive/pass), inner_thought拆self事件 (05§3.1, 03§3)
- [x] ChairAgent最小版: next_speaker + broadcast_decision简化版 (05§3.2)
- [x] DMAgent最小版: 判定五步中的②④(LLM)+③程序掷骰(seed=hash(master_seed, directive_id), margin分档) (06§3)
- [x] 单会场状态机: 仅Opening→ModCaucus→Adjourned, 点名+保底轮询 (04§3)
- [x] 手写迷你场景包(1会场3席位, 虚构三人内阁危机, yaml), scenario.py加载+pydantic校验 (02§3)
- [x] CLI运行器: `munagent run <scenario> --max-steps N [--seed <int>]`, 彩色输出事件流
- [x] 回放脚本: `munagent replay <session> --viewpoint seat:x|god` (03§8)

**验收**: 全AI跑≥3轮闭环; 回放按视角过滤正确; 同一master_seed两次运行掷骰结果一致.

## P2 - 完整会议机制 [=M2] ✅(2026-07-12)

**目标**: 单会场下所有会议机制完整可用, 断点续推可靠.

**P1 兼容性改动(已在 P1 收尾时完成)**:
- [x] VenueSpec 加 presiding_seat 可选字段(仅 schema, 引擎不路由) (02§3, D15)
- [x] render() 加 presiding_change/motion_ruling 渲染分支 (03§3)
- [x] D15/D16 编号冲突修正 (01)

**P2 正式任务**:
- [x] 前场状态机完整: 全状态+转移表, 主席phase_decision (04§3)
- [x] 戏内主持席完整: DelegateAgent 加 next_speaker/motion_ruling/caucus_switch 主持任务(带人格卡/inner_thought); ChairAgent 加 appeal_ruling; 引擎按 presiding_seat 路由(有则调对应 DelegateAgent, 无则调 ChairAgent); appeal 动议交戏外主席终裁; presiding_change 事件与主持权易手 (04§3, 05§3.1-3.2, D15)
- [x] Voting子流程: 动议→受理→冻结→逐席位投票→decision_rule计票(veto)→返回原阶段 (04§3)
- [x] Unmod: initial_grouping→小轮并行(asyncio)→next_move收集→屏障固定顺序结算 (04§3)
- [x] 闭门小组: closed标记, quick_decide轻量调用, join_request/decision事件 (04§3, 05§3.1) — schema已就位, 引擎Unmod基础版暂未启用屏障结算, 留P3完善
- [x] 四类指令全生命周期状态机+directive_status事件 (06§1-2)
- [x] 草案线模型: 编号程序分配/版本链/fork判定/diff摘要/表决用编号/superseded批量作废 (06§2, D16)
- [x] 判定流水线完整五步: 合法性(程序+LLM)/可行性/掷骰/结果撰写/上报 (06§3)
- [x] 危机笔记送达与截获判定 (06§5)
- [x] RecorderAgent: venue/私人/dm-only三层摘要 (05§3.4)
- [x] 纪元机制: L3按epoch_l3_max_tokens触发切换, 摘要更新与缓存失效绑定 (11§3)
- [x] G段拆分与预热请求; llm_usage面板数据(命中率per role) (11§2, §5-6)
- [x] 推演时钟: clock_rate累加/clock_advance/takes_effect_at (04§5) — 累加+clock_advance已实现, takes_effect_at时序裁定留P3
- [x] 阶段预算+会话token熔断+单Agent连续失败暂停 (04§6, 07§5)
- [x] core/reducer.py: RuntimeState模型 + apply/reduce双接口, 引擎在线维护与续推重建共用apply (03§7)
- [x] 断点续推: reducer从事件流重建全部运行时状态, 从安全点继续 (03§7-8, 07§2)
- [x] reducer确定性测试: 同一事件流reduce两次结构级相等 + 属性测试(任意前缀reduce = 逐事件apply) (03§7)
- [x] Prompt质量改进: G段补充动议类型说明/指令区别/appeal用法; DM加概率档位指引与结果档位叙述风格; L4的directive schema补全co_sponsors/recipient; 详见 docs/design/prompt-analysis.md
- [x] 时区本地显示: story_time按venue.timezone渲染本地时间(04§5)

**验收**: 手写场景全AI推演30分钟不失控(预算内/无解析死循环); kill进程后续推无缝衔接; 缓存命中率在第二纪元起>60%(实测记录基线).

## P3 - 多会场 [=M3]

**目标**: 双会场并行+跨会场交互, 古巴导弹危机示例跑通.

- [ ] 多venue_loop并行 + 跨会场共享状态只在backroom/interrupt协程修改的免锁规则 (07§1, §3)
- [ ] backroom_loop/interrupt_loop独立协程化 (07§1)
- [ ] 临时会场: 创建/借出(原会场标记离场)/归还/解散, 默认无投票权 (04§1)
- [ ] Crisis Update按会场定制文本/延迟/扣发(withheld补播) (05§3.2, 06§2)
- [ ] 危机弧线: story_time型引擎触发 + condition型DM评估 + 随机事件池 (04§4, 02§3)
- [ ] 时序冲突: 对抗性复判(播报前) + 不回滚圆场原则(播报后) (06§4)
- [ ] end_conditions评估(每次Crisis Update后) (07§7)
- [ ] 手写古巴导弹危机场景包(双会场, 后续M6精修)

**验收**: 双会场完整危机推演, 含≥1次跨会场指令传达与≥1次临时会场谈判; 全程事件日志可god/单席位双视角回放.

## P4 - Web GUI(推演侧) [=M4]

**目标**: 浏览器中观察/导演/参与推演. 依次: 观察→复盘→导演→玩家.

- [ ] FastAPI应用骨架 + REST路由表 (09§2)
- [ ] WS协议: subscribe(视角服务端过滤)/event推送/session_state/断线since_seq补拉 (09§3)
- [ ] 前端脚手架(Vue3+Vite+TypeScript, 定稿不再摇摆), FastAPI静态托管
- [ ] 推演大厅-观察模式: 时间线/会场标签页/席位列表/指令追踪面板/时钟与用量条 (09§1)
- [ ] Unmod分组视图(组卡片+串门可视化) (09§1)
- [ ] run/pause/step控制 (07§4)
- [ ] 复盘页: seq拖动/视角切换/指令链路追溯/导出markdown (09§1, 03§8)
- [ ] 导演模式: 主席团控制台(强切阶段/注入事件/dm-only面板) + draft_review草稿审改流 (09§1, §3)
- [ ] 玩家模式: HumanProvider经WS的action_request/submit + 超时fallback; 视角锁定 (07§4, 09§3-4)
- [ ] 用量面板: token/费用/缓存命中率曲线per role (11§5)

**验收**: 浏览器观察一场全AI推演并复盘导出md; 人类接管1席位完整打完一场(含发言/换组/投票/写指令).

## P5 - 会场设计器 [=M5]

**目标**: 从一句话主题到可推演场景包.

- [ ] tools/: web_search + fetch_page + download_file(大小限制) (02§2)
- [ ] MinerU客户端: /health检查, 异步任务+轮询, 并发≤4, 失败标记不阻塞 (02§2, docs/tools/)
- [ ] DesignerAgent: 工具调用循环(function calling, 单步骤上限30次) (05§1, §3.5)
- [ ] 设计步骤S1~S8各自的task与产出写入; .design_state.yaml断点续做 (02§1)
- [ ] references/管理: index.yaml, raw/隔离, 导出时剔除raw与design_state (02§3)
- [ ] 一致性检查五类+报告 (02§5)
- [ ] 场景包导入导出(zip)
- [ ] 设计工作台前端: 步骤导航/表单编辑+草稿diff/Agent对话栏/S2资料清单 (09§1)

**验收**: 一句话主题→30分钟内(含人工确认)产出通过校验且可直接推演的场景包, references≥5份转换成功.

## P6 - 打磨发布 [=M6]

**目标**: 新用户10分钟跑起示例.

- [ ] 设置页: providers/roles/tools编辑(key掩码只写不读)+测试连接 (08§3-4, 09§2)
- [ ] 内置精修示例场景×2(古巴导弹危机/法国1848)
- [ ] 可观测面板: 解析失败率per role, 命中率异常告警 (07§6, 11§5)
- [ ] 首次启动引导(配key→测试→跑示例)
- [ ] README重写: 安装/快速开始/截图; 文档过一遍与实现对齐
- [ ] 一键启动: `munagent serve`拉起后端+静态前端

**验收**: 干净机器从clone到观看示例推演≤10分钟.

## 里程碑依赖与并行机会

```
P0 → P1 → P2 → P3 → P4 → P6
                 ↘ P5 ──↗        (P5只依赖P2的场景包格式冻结, 可与P3/P4部分并行)
```

## 全程风险清单

| 风险 | 缓解 |
|---|---|
| flash模型结构化输出失败率高 | P1就建立解析失败率统计; 高则简化schema或该任务升pro |
| 推演质量"演不像"(发言空洞/满场背刺) | P2起每阶段留人工评估环节; 调persona模板与honesty映射 |
| 缓存命中率不及预期, 成本超估 | P2验收强制记录基线; 命中率进CI冒烟(对mock计算前缀稳定性) |
| Unmod并发+屏障的时序bug | 屏障结算纯函数化, property-based测试(随机moves→不变量: 席位不重不漏) |
| 场景包格式后期大改 | P2结束前冻结v1格式; 之后改动走版本号+迁移函数 |
| 前端工作量失控 | P4先做只读观察模式立住闭环, 交互模式逐个加 |
