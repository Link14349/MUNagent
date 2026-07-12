# 01 场景包与 chats/ 数据设计

细化 [index.md](index.md)「场景包数据设计」一节. 核心原则: **场景包文件是唯一事实源, chats/ 是绑定在包内的对话历史**——agent 做过什么、改过什么, 都能在 chats/ 里查到, 但场景内容本身永远以包内文件为准.

## 1. 场景包结构(含 chats/)

以 `scenarios/cabinet-crisis/` 为格式参考, 增加 chats/:

```
<scenario_id>/
├── manifest.yaml
├── background.md
├── story-design.md
├── venues.yaml
├── crisis_arcs.yaml
├── stats.yaml
├── seats/
│   └── <seat_id>.yaml
├── references/              # 资料(agent 检索或用户添加), 结构沿用 introduction.md
│   ├── index.yaml
│   ├── <doc_id>.md
│   └── raw/
├── chats/                   # 本场景的全部 agent 对话
│   └── <chat_id>.jsonl      # 一个对话一个文件, 一行一条记录
└── .history/                # 版本快照(见 §5)
    └── <snap_id>/           # 每份快照 = 场景内容文件的一份完整拷贝 + meta.yaml
```

- **chats/ 与 .history/ 不进导出**: 导出 zip 恒剔除这两者, `references/raw/` 默认剔除(可选包含); 场景分享的是设定, 不是设计过程;
- **chats/ 与 .history/ 不进文件树**: 前端文件树不显示它们, 分别由对话 UI 与历史版本面板专管(见 02); 但它们就是普通文件, 用户在文件系统里能看能删, 删了只丢历史不伤场景;
- 没有 `chats/index.yaml`: 对话清单由后端扫描 `chats/*.jsonl` 生成(标题等元信息在每个文件的首行 meta 记录里), 避免索引与文件不同步的经典 bug.

## 2. chat 文件格式(JSONL)

选 JSONL 的理由: agent 回合是流式追加的(文本段/工具调用/文件编辑交错), 追加写一行一条最自然, 中途崩溃最多丢最后一行, 不会损坏整个文件.

`chat_id` 格式: `<yyyymmddHHMMSS>-<4位随机>`(如 `20260712143005-a3f1`), 生成后不变; 排序用文件内时间戳.

### 2.1 首行 meta

```json
{"type": "meta", "v": 1, "id": "20260712143005-a3f1", "title": "初始场景生成", "created_at": "2026-07-12T14:30:05+08:00"}
```

- `title` 默认取首条用户消息前 30 字, 用户可改名(改名 = 重写首行);
- `v` 是 chat 格式版本号, 将来变更格式时做迁移判断.

### 2.2 记录行

meta 之后每行一条记录, 公共字段: `seq`(文件内自增, 从 1 起)、`ts`(ISO 时间)、`turn`(第几轮用户↔agent 交换, 用户每发一条消息 turn+1, 该轮 agent 产生的所有记录共享同一 turn)、`type` + 各类型载荷:

| type | 载荷字段 | 说明 |
|---|---|---|
| `user_message` | `text` | 用户发送的消息 |
| `agent_text` | `text` | agent 的一段完整回复文本(一轮内可多段, 与工具/编辑交错; 流式增量不落盘, 只落最终整段) |
| `tool_call` | `tool`, `args_summary`, `status: ok\|error`, `result_summary` | 一次工具调用(web_search / fetch_page / download_file / mineru_convert / read_file / list_files …). args/result 只存**摘要**(单行, ≤200 字), 完整结果不落 chat——大体积产物应落 references/ |
| `file_edit` | `path`, `op: create\|modify\|delete`, `diff` | agent 对场景包文件的一次编辑; `diff` 为 unified diff 全文(create 时 old 为空, delete 时 new 为空), 这是"看 agent 改了什么"和"撤销这次编辑"的数据基础 |
| `system` | `kind: aborted\|error\|revert`, `text` | 中止、脱敏后的错误、用户撤销某次编辑(`text` 注明撤销的 seq) |
| `usage` | `model`, `input_tokens`, `output_tokens`, `tool_calls` | 每轮结束追加一条, 记本轮消耗, 供 UI 显示与统计 |

一轮典型序列:

```jsonl
{"seq":7,"turn":3,"ts":"…","type":"user_message","text":"给临时政府再加两个左翼席位"}
{"seq":8,"turn":3,"ts":"…","type":"agent_text","text":"好的, 我先看一下现有席位构成…"}
{"seq":9,"turn":3,"ts":"…","type":"tool_call","tool":"list_files","args_summary":"seats/","status":"ok","result_summary":"7 个席位文件"}
{"seq":10,"turn":3,"ts":"…","type":"file_edit","path":"seats/louis_blanc.yaml","op":"create","diff":"--- /dev/null\n+++ seats/louis_blanc.yaml\n@@ …"}
{"seq":11,"turn":3,"ts":"…","type":"file_edit","path":"seats/albert.yaml","op":"create","diff":"…"}
{"seq":12,"turn":3,"ts":"…","type":"agent_text","text":"已新增路易·布朗与阿尔贝两个席位, 立场为…"}
{"seq":13,"turn":3,"ts":"…","type":"usage","model":"deepseek-v4-pro","input_tokens":18234,"output_tokens":2110,"tool_calls":3}
```

### 2.3 硬约束

- **key 与配置永不入 chat**(全局安全红线): tool_call 摘要与 error 文本落盘前脱敏;
- **思维链不落 chat**: reasoning_content 只做实时展示(03§7.4), 不回喂模型上下文, 也不落盘——chat 记录重放即可完整重建 agent 上下文, 思维链不在其中;
- chat 记录**只追加不改写**(meta 行改名除外); 撤销编辑不是删掉 file_edit 行, 而是追加一条 `system/revert` + 实际反向写文件;
- agent 对话上下文由后端从 jsonl 重建(user_message/agent_text/工具与编辑的摘要), 前端渲染与 agent 上下文共用同一份记录, 不存在第二份"给模型看的历史".

## 3. 编辑的应用与撤销语义

- agent 的文件编辑**直接落盘**(Cursor agent 式), 不做"待确认补丁"——单机单人, 撤销比确认流更顺手; 每次编辑都有 file_edit 记录兜底;
- **撤销一次编辑**: 对该 file_edit 的 diff 做反向应用. 仅当文件当前内容与 diff 的"编辑后"一致时可直接撤销; 已被后续修改覆盖时, 前端提示冲突并给出该次编辑前后的对照, 由用户手工处理(v1 不做三方合并);
- 用户手工编辑不产生 chats/ 记录(chats 只记对话轮次内发生的事); 手工改动与整体回滚的安全网是版本快照(§5), **不用 git**——目标用户不应被要求理解或安装版本管理工具; 高级用户自行对场景目录 `git init` 与本机制互不干扰.

## 4. 对话清单与生命周期

- `GET chats 列表` = 扫描目录, 每项: `{id, title, created_at, updated_at(文件 mtime), turns}`;
- 新建对话: 建空 jsonl(只有 meta 行); 删除对话: 删文件(二次确认); 重命名: 重写 meta;
- 一个场景可有任意多个对话; **同一场景同一时刻只允许一个对话在跑 agent 任务**(全局并发=1, 场景文件是共享资源);
- 内置(readonly)场景不可开对话——先"另存为副本"到用户目录再设计(见 02§1).

## 5. 版本快照(.history/)

给非技术用户的"文档历史版本"心智: 不引 git(二进制或 dulwich 都不引), 快照就是场景内容文件的**完整目录拷贝**——傻、稳、可被用户在文件管理器里直接理解.

### 5.1 快照内容与存储

```
.history/<snap_id>/
├── meta.yaml        # {id, created_at, kind, reason, chat_id?, turn?, note?}
└── …                # 场景内容文件的原样拷贝(目录结构保持)
```

- **拷贝范围**: 场景包全部内容文件, **不含** `chats/`、`.history/` 自身、`references/raw/`(转换后的 references/*.md 与 index.yaml 包含在内——它们是场景内容);
- `snap_id` 格式: `<yyyymmddHHMMSS>-<kind>`; 场景包全文本、单份快照通常几百 KB 级, 直接 copytree, 不做增量/压缩;
- `kind` 三种: `auto`(agent 任务前自动)、`manual`(用户存档点, 可附 `note`)、`restore_backup`(执行恢复前对当前状态的自动兜底快照).

### 5.2 触发时机

| 时机 | kind | reason 示例 |
|---|---|---|
| 每次 agent 任务启动前(即将写文件的唯一入口) | auto | `对话「席位扩充」第 3 轮之前` |
| 用户点"保存版本" | manual | 用户填写的 note, 如 `改弧线前` |
| 用户执行"恢复到某版本"前 | restore_backup | `恢复到 07-12 14:30 之前的自动备份` |

- 手工编辑不逐次触发快照(否则每 800ms 自动保存都产生一份); 手滑场景由"恢复到上一份 auto/manual 快照"兜住, 粒度足够;
- 连续 agent 轮次间若场景文件无任何变化(纯问答轮), 跳过本次 auto 快照, 避免刷屏.

### 5.3 保留策略

- `auto` 与 `restore_backup` 滚动保留最近 **30** 份(合并计数), 超出删最旧;
- `manual` 不参与滚动淘汰, 只能用户显式删除;
- 删除快照只影响 .history/, 与场景内容和 chats/ 零耦合.

### 5.4 恢复语义

恢复到快照 S = 原子地把场景内容文件区**整体替换**为 S 的内容: S 里有的文件写回, 当前有而 S 里没有的删除(chats/、.history/、references/raw/ 不动). 执行顺序:

1. 有 agent 任务在跑则拒绝(先中止);
2. 自动创建 `restore_backup` 快照;
3. 替换文件区, 触发结构校验刷新;
4. 恢复操作永远可反悔——刚才的状态就躺在第 2 步的快照里.

恢复不改写 chats/: 对话历史里的 file_edit 记录可能因此与文件现状脱节, 这是预期行为(那些记录描述的是"当时发生过什么", 不是"现在文件长什么样"); 受影响的只是"撤销该编辑"可能报内容漂移冲突, 已有冲突路径兜住(§3).
