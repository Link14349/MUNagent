# 本地会议服务与运行存档

`src/main.py` 同时提供本地 HTTP 服务和命令行客户端。默认只监听
`127.0.0.1:8765`，启动后会议在线程中运行，服务进程继续保留，便于在会议自动结束后
查询最终状态和存档位置。

`serve` 所在终端会直接按事件 ID 输出每个 Venue 的 `EventList`。新增事件使用
`[事件]`，同一事件后续被编辑或裁定时使用 `[更新]`；输出包括时间、类型、状态、
scope 和正文，但不显示 Agent 的内部思考。这里是本机管理员视图，可能出现私密事件。
正常启动时第一条输出是引擎生成的 `meeting_start#0`：无主持/自由讨论阶段由它唤醒
全体代表，有主持/休会阶段由它只唤醒主席，从程序上避免所有角色互相等待。

## 1. 启动

先在 `~/.munagent/config.yaml` 配置 provider，或设置 `MUNAGENT_API_KEY`。然后运行：

```bash
python src/main.py serve scenario-template
```

常用参数：

```bash
python src/main.py serve scenario-template \
  --host 127.0.0.1 \
  --port 8765 \
  --provider deepseek \
  --model deepseek-v4-flash \
  --seed replay-001
```

- 省略 `--seed` 时，每次运行生成一个新的 128 位十六进制种子；
- 传入相同 `--seed`、会场 ID、指令事件 ID 和提交正文，可复现 DM 的指令骰点；
- `--no-llm` 只用于检查加载、服务和存档，不运行代表、主席、DM，也不判断文本终局条件；
- 默认地址没有认证，只应监听本机回环地址。不要把服务直接暴露到公网。

安装项目后也可将 `python src/main.py` 替换为 `munagent`。

## 2. 命令行观察

```bash
# 当前状态
python src/main.py status

# 当前全部公开事件
python src/main.py events

# 从事件 #12 之后持续观察
python src/main.py watch --after 12

# 停止会议，但保留 HTTP 服务供查询
python src/main.py stop

# 停止会议并关闭服务
python src/main.py shutdown
```

服务使用其他地址时，为客户端命令传入
`--url http://127.0.0.1:<port>`。`status` 和 `events` 支持 `--json` 输出完整 JSON；
`events` / `watch` 可用 `--venue` 指定会场。

## 3. HTTP API

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/health` | 服务存活检查 |
| `GET` | `/api/status` | 运行状态、剧情时间、会场阶段、议题、线程、错误和终局原因 |
| `GET` | `/api/events?after=-1&limit=100&venue=<id>` | 公开会场事件增量 |
| `POST` | `/api/stop` | 协作停止本次推演，服务继续运行 |
| `POST` | `/api/shutdown` | 停止推演并关闭 HTTP 服务 |

HTTP 事件接口只返回 `scope` 等于全体会场席位的公开事件。私密纸条、私聊、秘密指令
和分层危机更新不会从该接口泄露。

## 4. 自动终局

`Simulator` 启动独立终局监视线程：

- `time` 条件直接比较权威剧情时间，不调用模型；
- `text` 条件只在事件新建、编辑或裁定后检查；一次请求批量判断所有文本终局条件，
  不按固定短周期反复请求模型；
- 文本裁判只能报告真假、理由和证据事件 ID，不能修改会场；证据不足时必须返回未成立；
- 任一条件成立后，引擎向会场提交 `meeting_ended` 阶段事件，再协作取消全部 Agent 和
  VenueEngine 线程；
- 文本裁判临时失败会显示在 `end_condition_warning`，会议继续运行并在退避后重试；
  时间截止条件仍然有效。

## 5. 运行存档

每次运行在 `<scenario>/simulation/<run_id>/` 下生成：

```text
<run_id>/
├── run.json       # 种子、模型配置、当前/最终状态、终局证据和线程错误
├── events.jsonl   # 全量权威事件审计，每行一个 JSON 对象
├── _manifest.yaml
├── reps/
└── submissions/
```

服务运行期间每 0.5 秒原子刷新存档，结束时先写最终状态再让 `MeetingRun.wait()` 返回。
同一分钟重复启动时，后续目录自动增加 `-1`、`-2` 等后缀。

`events.jsonl` 是系统管理员级审计记录，包含私密事件的正文和 scope；运行目录已经由
`.gitignore` 排除，不应提交、公开或发送给无权查看角色秘密的人。
