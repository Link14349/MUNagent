# 场景包

| 函数 | 说明 |
|---|---|
| `list_scenarios() -> list[ScenarioSummary]` | 扫描内置 + 用户目录 |
| `load_scenario(id) -> ScenarioDetail` | 校验并加载全部文本文件 |
| `create_scenario(body) -> ScenarioDetail` | 在用户目录创建空白包 |
| `save_scenario_files(id, files) -> ScenarioDetail` | 更新用户场景文件 |
| `delete_scenario(id)` | 删除用户场景(内置只读) |

路径: 内置 `scenarios/`, 用户 `~/.munagent/scenarios/`
