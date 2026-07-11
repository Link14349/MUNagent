# engine 模块 API

## `engine.Engine(scenario, config, *, master_seed, max_steps, db_path)`
P1 推演引擎: 单会场 + 三 Agent 闭环.

- `run() -> RunResult`: 执行推演, 返回全部事件
- `RunResult(session_id, total_steps, events)`

## CLI
- `munagent run <scenario> --max-steps N [--seed <int>] [--db <path>]`
- `munagent replay <session> --viewpoint god|seat:<id> [--db <path>]`
