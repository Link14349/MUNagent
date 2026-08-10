# AGENTS.md — 场景包设计约定

本文件适用于 `scenario-template/` 及其全部子目录，并在根目录 `AGENTS.md` 基础上追加场景包专属规则。字段定义以 `../docs/scenario-schema.md` 为准。

## 场景包职责

该目录既是单会场标准场景包，也是加载器和后续场景作者的示例。它只负责描述历史口径、会场、代表、外部事件和预期终局，不负责实现动作校验、状态转换、Agent 调度、存档或 LLM 客户端。

当前模板固定为一个会场、四名代表、每名代表一个独立 Agent。不得在本目录中提前设计多会场联动。

## 文件职责

```text
index.yaml                 场景元数据与资料来源
background.md              所有代表共享的公开背景
venues/<venue_id>.yaml     会场、主席、代表列表与议程
reps/<rep_id>.yaml         单个代表的公开/私密角色卡
storyline.yaml             目标、外部事件与结束条件
mechanism.py               预留空文件；当前不加载、不实现任何机制
```

不要把角色秘密写入 `background.md` 或会场文件。`mechanism.yaml` 不属于场景包设计，禁止创建；`mechanism.py` 仅保留为 0 字节占位文件，当前不得写入代码，也不由加载器读取。比例校验、签署、时钟和终局判定由通用推演引擎实现。

## 标识与引用

- 机器标识统一使用稳定的 ASCII `snake_case`，显示名称和正文使用简体中文；
- 一个代表文件只定义一个代表；代表 ID 唯一取自 YAML 文件名（不含 `.yaml`），角色文件内不得重复声明 `id`；
- venue 由加载器扫描 `venues/*.yaml` 发现，代表由扫描 `reps/*.yaml` 发现；`index.yaml` 不维护二者的重复索引；
- `background.md` 与 `storyline.yaml` 使用固定文件名；
- 所有时间使用带 UTC 偏移的 ISO 8601 字符串，会场同时声明 IANA 时区；
- YAML 字段名使用英文；禁止同时保留同义的新旧字段。

## 角色卡与信息边界

- 角色卡必须分为 `public` 和 `private`；
- 两个区块内的目标字段都叫 `target`：使用 `public.target` 和 `private.target`，禁止使用 `public_target`、`public_targets`、`private_target`、`private_targets` 或 `priorities`；
- `public` 可被全部会场 Agent 获知，`private` 只对对应代表 Agent 和必要的主席/裁定组件可见；
- `private` 中可以写真实底线、谈判空间、秘密信息和对其他代表的判断；
- 引擎必须先过滤可见性再组装上下文，不能把秘密全部注入后要求 Agent “假装不知道”。

## 历史与架空边界

- 历史事实、合理推断和玩法虚构必须可区分；
- `background.md` 记录历史范围和必要的口径说明，`index.yaml.sources` 记录资料来源；
- 不把开场时间之后发生的事实写入角色已知信息；
- 场景允许改写历史，但推演分支不能被表述为真实历史。

## 会场规则与剧情

- venue 的 `chair` 只能是 `none` 或一个代表 ID；`none` 表示使用系统中立主席；
- venue 的 `seats` 只能是代表 ID 列表，不重复保存代表团、职务或其他角色信息；
- venue 不声明 procedure、允许动作、决议文件或信息策略；会议流程和动作规则由引擎实现；
- `storyline.yaml` 只放代表无法直接控制的外部事件。发言、提案、让步、签署和命令属于运行时行动；
- 事件不直接修改场景自定义数值；当前 schema 不使用 `effects`；
- 每个 event 使用 `condition`，其中只能有 `type` 和 `content`；`type` 仅允许 `time_reached` 或 `text`；
- `time_reached` 的 `content` 是带 UTC 偏移的 ISO 8601 时间，`text` 的 `content` 是交给 LLM 判断真假的自然语言条件；
- event 自身只包含 `id`、`condition`、`content`；不要添加与 content 重复的解释字段；
- `end_conditions[]` 每项也只能包含 `type` 和 `content`，并使用同一套条件类型；
- 场景内容不能要求 LLM 自行心算比例、决定签署是否有效或随意判定终局；这些都由未来的通用引擎统一处理。

## 修改同步要求

修改字段名、类型、可见性或引用关系时，必须同步：

1. `docs/scenario-schema.md`；
2. 所有使用该字段的模板文件；
3. `introduction.md` 中受影响的顶层说明；
4. 相应的解析和跨文件一致性验证。

## 验证基线

- 所有 YAML 均可解析；
- `background.md`、`storyline.yaml`、至少一个 venue 文件和至少一个代表文件存在；
- reps 文件名派生出的 ID、venue 席位和角色文件一一对应；
- chair 为 `none` 或 seats 中存在的代表 ID，seats 每项都是字符串代表 ID；
- 每张角色卡同时且仅使用 `public.target`、`private.target` 表达目标；
- 跨文件 ID 引用一致；
- event 不使用 `trigger`，其 `condition` 只包含合法的 `type` 和 `content`；
- event 不使用 `historicity` 或 `scope`；
- event 顶层恰好只包含 `id`、`condition` 和 `content`；
- 每个 end condition 恰好只包含 `type` 和 `content`；
- 不存在 `mechanism.yaml`，且 `mechanism.py` 保持 0 字节；
- 私密目标没有泄漏到公开背景或其他代表角色卡。
