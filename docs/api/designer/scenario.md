# 设计器场景包 (`designer/scenario/`)

场景包在磁盘上的全部领域逻辑, 归属设计子系统. 推演侧将来通过只读加载消费已导出的场景包, 不直接依赖本模块.

# 场景包 (`package.py`)

| 函数 | 说明 |
|---|---|
| `list_scenarios() -> list[ScenarioSummary]` | 扫描内置 + 用户目录 |
| `load_scenario(id) -> ScenarioDetail` | 校验并加载全部文本文件 |
| `create_scenario(body) -> ScenarioDetail` | 在用户目录创建空白包 |
| `save_scenario_files(id, files) -> ScenarioDetail` | 更新用户场景文件(整包) |
| `delete_scenario(id)` | 删除用户场景(内置只读) |
| `duplicate_scenario(id, new_id, new_title)` | 另存为副本到用户目录 |
| `export_scenario_zip(id, include_raw=False) -> bytes` | 导出 zip(剔除 chats/.history/) |

路径: 内置 `scenarios/`, 用户 `~/.munagent/scenarios/`

**Manifest 字段**: `id` `title` `start_story_time`(必填); `description`(≤100字) `content`(≤500字); `end_conditions` 已迁至 `crisis_arcs.yaml`.

**CrisisArcsFile**: `main_arc` `random_pool` `end_conditions` — 见 [design/designer/01-data-chats.md](../../../design/designer/01-data-chats.md) §1.3.

**VenuesFile / SeatFile**: `venues.yaml` 会场与 `seats` 清单、`seats/<id>.yaml` 角色卡 — 见 §1.1–1.2; `validate_package_issues` 校验两处 id/name 一致.

# 单文件与文件树 (`files.py`)

| 函数 | 说明 |
|---|---|
| `get_file / put_file / delete_file / rename_file` | 单文件 CRUD; put/delete 返回 `validation` |
| `build_file_tree / scenario_design_meta` | 文件树(隐藏 chats/.history/) + 校验 issues |
| `list_package_files / read_bytes / put_bytes` | Agent 工具用: 含二进制清单与读写 |
| `validate_package_issues(root)` | 软校验, 供顶栏 chip |

# 历史快照 (`history.py`)

| 函数 | 说明 |
|---|---|
| `create_snapshot` | manual/auto/restore_backup |
| `list_snapshots / history_diff / restore_snapshot / delete_snapshot` | 历史面板 |

# chats (`chats.py`)

| 函数 | 说明 |
|---|---|
| `list_chats / create_chat / get_chat_records / rename_chat / delete_chat` | JSONL 对话文件(无 Agent) |
| `derive_todo(records) -> str \| None` | 取最后一条 `type:todo` 的 text |
| `get_chat_detail(id, chat_id) -> (records, todo)` | 全量记录 + 派生 todo |
| `append_chat_record(id, chat_id, record, turn=?)` | 追加一条记录(Agent/SSE 用) |

HTTP 路由见 `docs/api/server.md` 设计器一节. `GET .../chats/{chat_id}` 响应 `{records, todo}`.
