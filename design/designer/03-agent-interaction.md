# 03 对话面板、交互协议与前端架构

对话面板是两种模式共用的核心部件(02§2-3). 本文定义消息渲染、agent 任务的流式协议、API 契约与前端代码组织.

## 1. 对话面板结构

```
┌ 头部(编辑模式形态): 当前对话标题 ▾ | [+ 新对话]      ┐
│ 消息流(.chats/<id>.jsonl 记录的直接渲染, 见 §2)      │
│ …                                                │
│ ┌ 生成中: agent 正在工作… (工具 4 次) [中止] ┐      │ ← 任务运行时替换输入框
│ 快捷 chips(§4)                                    │
│ ┌ 输入框 (Enter 发送 / Shift+Enter 换行) ┐         │
└──────────────────────────────────────────────────┘
```

## 2. 消息渲染: jsonl 记录 → UI

渲染就是把 01§2.2 的记录类型逐条映射, **不另设前端消息模型**:

| 记录 | 渲染 |
|---|---|
| `user_message` | 右对齐气泡 |
| `agent_text` | 左对齐, Markdown 渲染; 流式时先渲染增量, `task_finished` 后以落盘记录为准 |
| `tool_call` | 紧凑单行卡: 图标 + `args_summary`, 运行中转圈/完成对勾/失败红叉; 点击展开 `result_summary`. 同一轮连续 ≥3 个折叠为聚合卡(`调用了 5 次工具 ▾`) |
| `file_edit` | **编辑卡**: `✎ seats/louis_blanc.yaml (+41)` 增删行数徽标; 点击展开内嵌 diff(unified 渲染, 绿加红减); 卡上动作: `[查看文件]`(编辑模式打开/对话模式右栏预览)、`[撤销]`(01§3 语义, 冲突时弹对照) |
| `system` | 居中灰色短行(中止/错误/撤销说明); error 附 `[重试]`(把上一条 user_message 重发) |
| `usage` | 不占消息位, 聚合进该轮尾部的小字(`本轮 18.2k→2.1k tokens · 3 次工具`) |
| `todo` | 流内渲染成清单卡片: `[x]` 行划线打勾、`[ ] ` 行空框; 同时更新输入区上方的"当前计划"折叠条(见下) |

- 对话历史来自 `GET chat 详情`(全量记录), 打开对话时渲染一次; 之后只靠 SSE 增量追加;
- **思考块**: 任务运行中收到 `think_delta` 时, 在该轮当前位置渲染一个可折叠的灰色"思考中…"块, 流式追加; 一旦开始收到 `text_delta`/工具事件即自动折叠. 思维链不落盘(§7.4), 刷新页面后历史消息里没有思考块是预期行为;
- **当前计划条**: 对话面板输入区上方常驻一条可折叠的"当前计划"提示(如 `2/5 ▾`), 内容 = 该 chat 最新的 `todo` 记录(01§2.4); 打开对话时取自 `GET chat 详情` 的派生 `todo` 字段, 之后随 `record_appended(todo)` 事件实时刷新; 无 todo 记录时不显示; 只读, 用户不能直接编辑;
- 长对话虚拟滚动 v1 不做, 超过 500 条记录提示"建议开新对话"(也顺便控制 agent 上下文长度).

## 3. agent 任务生命周期与 SSE 协议

发消息 = 启动一个 agent 任务. 全场景并发为 1(01§4), 任务归属某个 chat:

```
POST /api/scenarios/{id}/chats/{chat_id}/messages  {text}
  → 202 {task_id}   (另有任务在跑: 409, 前端提示"另一对话正在生成")
  → 后端: 追加 user_message 记录 → agent 工具循环(读文件/搜索/下载/MinerU/写文件)
         → 过程记录逐条落盘并经 SSE 推送 → 任务结束
POST /api/scenarios/{id}/design/abort   (幂等; 中止后已落盘的编辑保留)
```

SSE: `GET /api/scenarios/{id}/design/events`, 进入设计器即连接、常驻(不分对话, 事件带 chat_id):

```ts
type DesignerEvent =
  | { seq; type: "task_started";  chat_id; task_id; turn }
  | { seq; type: "think_delta";   chat_id; delta: string }        // 思维链增量(仅实时展示, 不落盘, 见 §7.4)
  | { seq; type: "text_delta";    chat_id; delta: string }        // agent_text 的流式增量
  | { seq; type: "record_appended"; chat_id; record: ChatRecord } // 除增量外, 每条落盘记录原样推一份
  | { seq; type: "task_finished"; chat_id; result: "done" | "aborted" | "failed"; error: string | null }
  | { seq; type: "chat_renamed"; chat_id; title: string }         // 首轮结束后自动概括标题
  | { seq; type: "files_changed"; paths: string[] }               // 触发文件树/编辑器/校验 chip 刷新
```

- `seq` 为 SSE 流内自增, 重连带 `Last-Event-ID` 重放; 重放窗口不足时前端全量刷新当前对话与文件列表——**服务端永远是事实源, 前端疑惑就重拉**;
- 刷新页面后若任务仍在跑: `GET 设计器状态`(§4 表)返回 `active_task`, 前端重连 SSE 续显; 后端进程重启则任务消失, 对话尾部由后端补一条 `system/error("任务中断")`;
- 事件与记录中的 error 一律脱敏后下发(安全红线).

## 4. 输入区与快捷 chips

- 输入框上方一行**上下文提示**: 编辑模式下显示 `📎 当前文件: seats/premier.yaml`(agent 收到消息时附带该路径, 用户说"把这个写完整"时指代明确); 可点 × 去掉;
- 快捷 chips(预填输入框, 可编辑后发送): 空场景首对话给"从主题生成整套场景"类起手; 常驻给"检查一致性"、"继续完善当前文件"; chips 是纯前端文案配置, 不做服务端下发;
- 新场景对话空态: 引导文案(模板, 不耗 LLM)说明 agent 能做什么(检索资料/生成与修改任意场景文件/一致性检查).

## 5. REST 契约汇总(前端视角)

| 方法与路径 | 用途 |
|---|---|
| `GET  /api/scenarios/{id}/design` | 设计器初始化状态: `{active_task, chats: ChatMeta[], validation: Issue[]}` |
| `GET  /api/scenarios/{id}/chats/{chat_id}` | 对话全量记录 + 派生 `todo` 字段(最后一条 todo 记录的 text, 无则 `null`; 见 01§2.4) |
| `POST /api/scenarios/{id}/chats` | 新建对话 → ChatMeta |
| `PATCH/DELETE /api/scenarios/{id}/chats/{chat_id}` | 重命名 / 删除 |
| `POST /api/scenarios/{id}/chats/{chat_id}/messages` | 发消息(启动任务) |
| `POST /api/scenarios/{id}/design/abort` | 中止当前任务 |
| `POST /api/scenarios/{id}/chats/{chat_id}/revert/{seq}` | 撤销某次 file_edit; 409=内容已漂移, 带前后对照 |
| `GET/PUT/DELETE /api/scenarios/{id}/files/{path}` | 单文件读写删(文件树与编辑器用; PUT 响应带最新 validation) |
| `POST /api/scenarios/{id}/files/{path}/rename` | 重命名/移动 |
| `POST /api/scenarios/{id}/export` | 导出 zip(query: include_raw) |
| `POST /api/scenarios/{id}/duplicate` | 另存为副本(内置场景进设计器的通路) |
| `GET  /api/scenarios/{id}/history` | 快照列表(meta 数组, 时间倒序) |
| `POST /api/scenarios/{id}/history` | 创建 manual 快照, body: `{note?}` |
| `GET  /api/scenarios/{id}/history/{snap_id}/diff` | 与当前版本对比: 文件级变更清单 + 各文件 unified diff |
| `POST /api/scenarios/{id}/history/{snap_id}/restore` | 恢复(语义见 01§5.4); 有任务在跑: 409 |
| `DELETE /api/scenarios/{id}/history/{snap_id}` | 删除快照(仅 manual; auto: 403) |

快照的创建(auto/restore_backup)是后端在任务启动/恢复流程内部完成的, 前端不单独调用; 历史列表不做实时推送, 打开面板时拉取即可. 恢复成功后后端经 SSE 发 `files_changed`(全部受影响路径), 前端复用既有刷新路径.

P1 已有的整包读写接口保留给场景详情页; 设计器一律走单文件接口, 避免整包 PUT 覆盖 agent 并发写入.

## 6. 前端代码组织

```
src/
├── api.ts                          # 追加上表调用与类型(snake_case 与后端对齐)
├── router/index.ts                 # 追加 /design/:id
├── views/DesignerView.vue          # 外壳: 顶栏 + 模式布局切换(只摆积木, 无业务)
├── components/designer/
│   ├── FileTree.vue                # 两种模式共用(紧凑形态用 prop 区分)
│   ├── EditorPane.vue              # 多 tab 编辑器(含冲突条)
│   ├── PreviewPane.vue             # 只读预览(md 渲染/yaml 高亮)
│   ├── ChatPanel.vue               # 对话面板(头部/消息流/输入区)
│   ├── ChatMessage.vue             # 记录渲染分发(含编辑卡/工具卡/diff)
│   ├── ChatListPane.vue            # 对话模式左栏
│   └── ValidationChip.vue          # 顶栏校验状态 + 问题抽屉
└── composables/
    ├── useDesigner.ts              # 单例 store: 状态镜像 + 全部动作, provide/inject 共享
    └── useSse.ts                   # SSE 连接/Last-Event-ID 重连封装
```

- 状态管理不引 pinia: `useDesigner(scenarioId)` 单例 composable, 持有 `{chats, activeChat, records, activeTask, fileTree, openFiles, validation, mode}`; 一切变更动作先调 API, 以响应/SSE 回填, 本地只做乐观回显(用户消息、编辑中文本);
- **依赖纪律**(引任何一个前先问用户): 编辑器建议 CodeMirror 6(yaml/md 高亮 + 大文件性能, 自写 textarea 高亮不值得), Markdown 渲染建议 `marked` + 自配白名单转义, YAML 前端仅做展示不做解析(结构校验在后端), diff 渲染自实现(输入已是 unified diff 文本, 只是着色排版, ~60 行);
- 测试(vitest): diff 着色解析、SSE 重连 seq 续传、file_edit 撤销的可行性判断三处纯逻辑; 组件测试 v1 不做.

## 7. 设计 Agent loop 与 LLM 流式约定

### 7.1 Agent loop: 原生 function calling

**不自定义 JSON 信封, 不用 `<think>/<tool>` 标签协议**——工具通过请求体的 `tools` 参数声明(OpenAI 兼容协议原生 function calling, DeepSeek 完整支持), 模型的文本回复与工具调用由协议分在 `content` / `tool_calls` 两个字段, 天然支持流式且不需要自写解析器.

一次用户消息触发的任务 = 一个 loop, 每步一次 LLM 调用:

```
messages = [system(角色与纪律), 上下文(文件清单+manifest 摘要+📎当前文件), …对话历史, user 消息]
重复(工具调用累计 ≤50 次):
    流式调用 chat/completions(tools=工具定义, stream=True)
    逐增量分发: reasoning_content → think_delta / content → text_delta / tool_calls → 按 index 拼参数
    若无 tool_calls: 本段 content 落盘为 agent_text, 任务结束(即"最终回复")
    否则: content 段(若有)落盘 agent_text; 逐个执行工具, 落 tool_call/file_edit 记录并推事件;
          messages 追加 assistant(content+tool_calls) 与各 tool 结果, 进入下一步
```

- **终止条件 = 响应无 tool_calls**; 工具调用累计超 50 次则任务以 `failed` 结束并落 system 记录;
- **回喂纪律**: assistant 消息只回喂 `content` + `tool_calls`, `reasoning_content` 一律不回喂(协议要求, 塞回去会报错);
- `write_file` 是全量内容写入; .chats/ 里 file_edit 记录的 unified diff 由后端对比新旧内容生成, 模型不需要产出 diff 格式;
- 每步之间检查中止标志(abort 接口置位), 中止时已落盘的记录与编辑保留.

### 7.2 流式三通道 → SSE 事件映射

| LLM 流式增量 | SSE 事件 | 前端呈现 |
|---|---|---|
| `delta.reasoning_content` | `think_delta` | 可折叠思考块, 实时追加 |
| `delta.content` | `text_delta` | 正文气泡逐字渲染 |
| `delta.tool_calls`(分片) | 无逐字事件 | 参数碎片由后端拼装, 拼完执行时以 `record_appended(tool_call)` 推完整卡片(running→ok/error 两次推送) |

### 7.3 对 llm 模块的要求

- 在 `LLMClient` 上新增 `chat_stream()` **异步生成器**, 与现有非流式 `chat()` 并存(推演侧不强制流式); 请求带 `"stream": true` + `"stream_options": {"include_usage": true}`, 用 `httpx` 的 `client.stream()` 逐行读 SSE(`data: {...}`, 以 `data: [DONE]` 结尾);
- 产出**类型化增量**(ThinkDelta / TextDelta / ToolCallDelta / UsageDelta 联合类型), 这是 llm 层与 agent loop 的模块边界——loop 不碰原始 chunk, 测试用 mock 增量序列驱动;
- usage 取末 chunk(含 cache hit/miss), 复用现有 `_record_usage` 逻辑;
- **重试只在首个增量到达之前**: 已开始吐字后中途断流不得静默重试(前端文本会回退), 直接抛错由 loop 决定整步重试或落 system 错误记录;
- 超时拆分 connect/read: 整体超时不设或放宽, 相邻增量间隔超过阈值(如 60s)判定断流.

### 7.4 其余前端可见约定

- agent 的工具面(9 个): `read_file / write_file / list_files / web_search / fetch_page / download_file / mineru_convert / check_todo / edit_todo`, 全部限制在本场景包目录内(路径逃逸后端拒绝); 前端工具卡图标按此枚举;
- agent 每轮开场自动获得: 场景包文件清单 + manifest 摘要 + 当前文件(若有 📎)——用户不需要手动"给上下文"; **todo 注入 L 段(动态上下文, 不影响 G 段缓存)**, 见下条;
- **`check_todo` / `edit_todo`**(01§2.4 的数据层): `ToolContext` 除 `scenario_id + AppConfig` 外还需 `chat_id`(这两个工具是 chat 级, 不是场景级——loop 本来就知道当前跑在哪个 chat 上, 传入即可); `check_todo` 无参数, 返回当前 todo 全文(无则 `"(暂无 todo)"`); `edit_todo(todo: string)` 是**全量替换**: 先校验每个非空行以 `[ ] `/`[x] ` 开头(不合规返回业务错误字符串让模型自纠, 不抛异常), 校验通过后追加一条 `todo` 记录并推 `record_appended`, 工具返回值就是刚写入的全文(模型不需要紧接着再调一次 check_todo 确认);
- **todo 不进 G 静态段, 但每步刷新 L 段**: 最新 todo 全文写入动态 L 段(与文件清单同段, 每步 loop 重建), 避免多步任务内忘记勾项; 另在每次 `write_file` 成功且清单仍有未完成项时, loop 注入一条 ephemeral 系统提醒(不落盘); 纪律见 system prompt「todo 纪律」;
- **thinking 纪律(设计器)**: 思维链实时推前端(think_delta)但**不落 .chats/**——它不进模型上下文、不影响可复现性, 落盘只占体积; 刷新后思考块消失是预期. 注意这与推演侧纪律相反(代表 Agent 的思维链对其他席位保密), 两侧各自成立, 不要互相"统一".
