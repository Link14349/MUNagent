# Server

| 入口 | 说明 |
|---|---|
| `create_app() -> FastAPI` | 应用工厂, 挂载 `/api` + 静态 SPA |
| `munagent serve [--host] [--port] [--reload]` | 启动 uvicorn |

REST 见 `server/routes.py`: `/api/scenarios`, `/api/config`, `/api/config/test`

约束: `GET /api/config` 仅返回掩码 key; SPA 回退 `web/dist/index.html`.
