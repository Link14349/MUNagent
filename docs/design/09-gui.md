# 09 - 网页GUI与前后端协议

> 上级文档: [index.md](index.md) | 相关: [03-event-model.md](03-event-model.md)(视角过滤), [07-engine.md](07-engine.md)(人类挂点)

## 1. 页面结构

```
首页(场景包库) ─┬→ 设计工作台(向导S1~S8)
               ├→ 新建推演(选场景包+模式+模型配置) → 推演大厅
               ├→ 会话列表 → 推演大厅(续推) / 复盘页(已结束)
               └→ 设置页(providers/roles/tools/engine)
```

### 设计工作台
- 左侧: S1~S8步骤导航(状态: 未开始/进行中/已确认/needs_review);
- 中间: 当前步骤的结构化编辑表单(直接编辑yaml对应字段) + 草稿diff视图;
- 右侧: 设计Agent对话栏(重生成/修改指示); S2步骤中间区为资料清单(勾选增删, 显示转换状态);
- 底部: 上一步/确认进入下一步; S8显示一致性检查报告.

### 推演大厅
- 顶部: 故事时钟 + 当前阶段徽章 + 各会场标签页 + token/费用实时用量;
- 中间: 当前会场时间线(按视角过滤的事件流, 见§3); Unmod时切换为分组视图(各组卡片, 可见组成员与"谁在串门", 内容仅所在组可见);
- 右侧: 席位列表(在场/离场/发言中) + 指令追踪面板(生命周期状态, 见06§2);
- 底部(玩家模式): 行动区——发言输入/动议按钮/指令编辑器(四类模板)/投票按钮/换组选择; 显示超时倒计时;
- 导演模式追加"主席团控制台": run/pause/step控制、强切阶段、注入危机事件、AI草稿审改队列、dm-only信息面板(弧线进度/未播报结果);
- 观察模式: 仅视角切换器(上帝/任一席位)+播放控制.

### 复盘页
时间轴拖动跳转任意seq、视角切换、指令链路追溯(指令→判定→播报的关联跳转)、per-role解析失败率与用量统计、导出markdown会议记录.

## 2. REST API草案

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/api/scenarios` | 列出/新建场景包 |
| GET/PUT/DELETE | `/api/scenarios/{id}` | 读取/更新/删除 |
| POST | `/api/scenarios/{id}/design/{step}` | 触发某设计步骤的Agent草稿生成 |
| POST | `/api/scenarios/{id}/export` `/api/scenarios/import` | 导出zip/导入 |
| GET/POST | `/api/sessions` | 会话列表/创建(scenario_id+mode+config覆盖) |
| GET | `/api/sessions/{id}` | 会话详情(状态/用量) |
| POST | `/api/sessions/{id}/control` | `{action: run\|pause\|step\|end}` |
| GET | `/api/sessions/{id}/events?viewpoint=&since_seq=` | 拉取历史事件(复盘/断线重连) |
| GET | `/api/sessions/{id}/export.md?viewpoint=` | 导出会议记录 |
| GET/PUT | `/api/config` | 配置读写(key只写不读, 返回掩码) |
| POST | `/api/config/test` | 连接测试(见08§4) |

## 3. WebSocket协议

连接: `WS /api/sessions/{id}/ws`. 消息一律JSON `{type, ...}`.

### 客户端 → 服务端
| type | 字段 | 说明 |
|---|---|---|
| `subscribe` | `viewpoint: god \| seat:<id>` | 声明视角; god仅观察/导演模式允许 |
| `action_submit` | `request_id, action` | 应答action_request(人类行动, schema同05§3.1) |
| `director_control` | `op: force_phase\|inject_crisis\|edit_draft, ...` | 导演干预 → human_control事件 |

### 服务端 → 客户端
| type | 字段 | 说明 |
|---|---|---|
| `event` | Event对象 | **按订阅视角过滤后**实时推送(过滤在服务端, 见03§4) |
| `action_request` | `request_id, seat, task, schema, timeout_s` | 请求人类行动(玩家/导演审改) |
| `session_state` | `phase per venue, clock, running/paused` | 状态快照(连接时+变化时) |
| `budget_warning` | `kind, detail` | 用量/熔断告警 |
| `draft_review` | `request_id, role, draft` | 导演模式: AI草稿待审改 |

断线重连: 重连后用`since_seq`经REST补拉遗漏事件, WS只负责增量.

## 4. 视角安全

- 服务端是唯一的过滤点: `event`推送与`/events`拉取都经`bus.query(viewer)`;
- 玩家模式下`viewpoint`锁定为其席位, 不可切换god;
- 单机单人(决策D1)不做鉴权, 但视角过滤逻辑仍严格实现——它同时是Agent上下文隔离的同一套代码, 错了会泄密给AI.
