# Server

| 入口 | 说明 |
|---|---|
| `create_app() -> FastAPI` | 应用工厂, 挂载 `/api` + 静态 SPA |
| `munagent serve [--host] [--port] [--reload]` | 启动 uvicorn |

REST 见 `server/routes.py`: `/api/scenarios`, `/api/config`, `/api/config/test`

设计器 REST 见 `server/design_routes.py`(前缀 `/api/scenarios/{id}/`):

| 路径 | 说明 |
|---|---|
| `GET .../design` | 初始化: file_tree, validation, chats |
| `GET/PUT/DELETE .../files/{path}` | 单文件读写删 |
| `POST .../files/{path}/rename` | 重命名 |
| `POST .../duplicate` | 另存为副本 |
| `POST .../export` | 下载 zip |
| `GET/POST .../history` | 快照列表 / 手动存档 |
| `GET .../history/{snap}/diff` | 版本对比 |
| `POST .../history/{snap}/restore` | 恢复 |
| `DELETE .../history/{snap}` | 删除 manual 快照 |
| `GET/POST/PATCH/DELETE .../chats[/{chat_id}]` | 对话 JSONL; `GET .../chats/{id}` 返回 `{records, todo}` |
| `POST .../chats/{chat_id}/messages` | 发消息启动 Agent 任务 → 202 `{task_id}`; 并发冲突 409 |
| `GET .../design/events` | SSE 推送(`task_started` / `think_delta` / `text_delta` / `record_appended` / `task_finished` / `chat_renamed` / `files_changed`); 支持 `?after=` 与 `Last-Event-ID` 重放 |
| `POST .../design/abort` | 中止当前任务(幂等) |
| `POST .../chats/{chat_id}/revert/{seq}` | 撤销 file_edit; 409 返回漂移对照 |

Agent 任务编排见 `server/design_task.py`: 全场景单任务、`Agent.loop` 驱动、事件经 SSE 广播.

约束: `GET /api/config` 仅返回掩码 key; SPA 回退 `web/dist/index.html`.
