# core 模块 API

## `core.events`
- `Event(BaseModel)`: 事件模型, 含 scope/visible_to/payload/rng 字段
- `Event.is_visible_to(viewer) -> bool`: 单事件可见性判定. **viewer 用 canonical 形式**: `seat:<id>` / `chair` / `dm` / `recorder` / `god`
- `canonical_viewer(v) -> str`: 裸席位 id 归一化为 `seat:<id>`
- `materialize_visible_to(scope, ...) -> list[str] | None`: 按 scope 计算 visible_to, 成员自动经 canonical_viewer 归一化

## `core.bus.EventBus`
- `stage(event, ...) -> Event`: 暂存事件到步缓冲, 补全 seq 与 visible_to
- `commit_step() -> list[Event]`: SQLite 事务批量落库, 推给订阅者
- `rollback_step()`: 丢弃步缓冲
- `query(viewer, ...) -> list[Event]`: 查询 viewer 可见事件(含已 commit + 缓冲). `group=` 过滤只排除其他组的组内事件, venue/global 事件保留
- `subscribe(viewer, callback)`: 注册订阅者
- `create_session(scenario_id, master_seed, config)`: 创建会话
- `record_usage(UsageRecord)`: 记录 LLM 用量

## `core.render.render(event) -> str`
纯函数, 字节级确定. 修改渲染模板 = 破坏性变更.

## `core.scenario.load_scenario(path) -> Scenario`
从目录加载场景包, pydantic 校验. 含 `stats_for_seat(seat_id)` 按 visibility 过滤.

## `core.state_machine.VenueStateMachine`
单会场前场状态机. `phase`, `advance_clock()`, `transition(to)`, `floor_rotation_due`.
- `seat_status: dict[seat, "active"|"suspended"|"removed"]` — 席位状态(解职/被捕/死亡即失活)
- `active_seat_ids` — 在席席位; 点名/轮询/分组/投票/事件可见名单一律用它, 不用 `seat_ids`
- `set_seat_status(seat, status)` — 主持席失活时 `presiding_seat` 自动回落 None(中立主席)
