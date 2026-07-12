# 场景包 (`scenario/package.py`)

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

# 设计器文件 (`scenario/files.py`)

| 函数 | 说明 |
|---|---|
| `get_file / put_file / delete_file / rename_file` | 单文件 CRUD; put/delete 返回 `validation` |
| `build_file_tree / scenario_design_meta` | 文件树(隐藏 chats/.history/) + 校验 issues |
| `validate_package_issues(root)` | 软校验, 供顶栏 chip |

# 历史快照 (`scenario/history.py`)

| 函数 | 说明 |
|---|---|
| `create_snapshot` | manual/auto/restore_backup |
| `list_snapshots / history_diff / restore_snapshot / delete_snapshot` | 历史面板 |

# chats (`scenario/chats.py`)

| 函数 | 说明 |
|---|---|
| `list_chats / create_chat / get_chat_records / rename_chat / delete_chat` | JSONL 对话文件(无 Agent) |

HTTP 路由见 `docs/api/server.md` 设计器一节.
