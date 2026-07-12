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

约束: `GET /api/config` 仅返回掩码 key; SPA 回退 `web/dist/index.html`.
