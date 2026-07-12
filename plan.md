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
- [x] `designer/scenario/`: 场景包加载 + pydantic 校验 + 保存(不含设计 Agent, 先支持手工/示例场景) (02§3)
- [x] 内置示例场景 `scenarios/cabinet-crisis/` 可被 API 列出并读取
- [x] CLI: `munagent serve` 一键拉起后端 + 静态前端

**验收**: 浏览器打开首页可见示例场景; 设置页写入 key 并测试连接成功; 无需推演引擎即可浏览场景包各文件.

## P2 - 会场设计器

**目标**: 从一句话主题经设计 Agent 产出可校验、可推演的场景包, 并在设计工作台中完成人机协作.

- [x] 全部前端页面设计,待用户验收
- [x] 后端文件处理管理
- [x] 后端Agent工具实现
- [x] 后端Agent prompt设计管理
- [x] 补全Agent类
- [ ] 后端Agent处理(待设计)