# MUNagent：模拟联合国历史委员会推演 Agent

MUNagent 是一个使用 Python 开发的历史委员会模拟推演项目。系统加载场景包后，为每名代表创建一个独立 Agent，由主席团/引擎推进会议、校验行动、投递外部事件并记录结局。

项目把“场景内容设计”与“通用推演引擎”分开：历史背景、角色目标、会场配置和外部剧情由场景包维护；动作校验、状态转换、Agent 调度、信息可见性、时钟、终局判定与存档由引擎统一实现。场景包可交由 Codex、Claude 等通用 Agent 在 `AGENTS.md` 约束下协助制作。

## 当前阶段

当前只实现单会场：

- 一个场景只有一个正式谈判会场；
- 一名历史代表对应一个独立 Agent；
- 先打通角色发言、完整提案、签署、外部事件和结束条件；
- 多会场、跨会场通信和危机联动留到单会场闭环稳定后再设计。

目前仓库中的 `src/main.py` 仍是引擎入口骨架；`scenario-template/` 已先做成一份完整的单会场场景包，用它反推最小加载和运行接口。

## 场景包结构

```text
scenario-template/
├── AGENTS.md                # 场景包内容与 schema 的编辑约束
├── index.yaml                 # 场景元数据与资料来源
├── background.md              # 所有代表都能获得的公开背景
├── venues/
│   └── main.yaml              # 会场、主席、代表列表和议程
├── reps/
│   ├── winston_churchill.yaml # 一份文件只定义一个独立代表
│   ├── joseph_stalin.yaml
│   ├── anthony_eden.yaml
│   └── vyacheslav_molotov.yaml
├── storyline.yaml             # 会议目标、外部事件与结束条件
├── mechanism.py               # 当前为空的预留文件，不参与加载
└── simulation/                # 推演运行目录；initialize 时按日期时间新建子目录
```

角色卡分为 `public` 与 `private`。引擎必须在构建代表上下文前完成可见性过滤，不能把所有秘密交给 Agent 后再要求它“假装不知道”。

运行时 `simulation/` 中的工作文件与提交副本同样受程序可见性约束：`reps/` 由 `scope`/`owner` 控制；`submissions/` 不对代表直接开放列表，代表只能通过 `EventList` 里对其可见、并绑定了对应 `File` 的事件间接获知 submission。运行时事件的剧情时间不在构造时传入，而由 `EventList.add_event` 按当前时钟盖戳。

两个区块内都使用局部字段名 `target`，即 `public.target` 与 `private.target`。可见性已经由父级区块表达，不再使用 `public_target`、`private_target` 或 `priorities` 等重复命名。

代表 ID 直接由角色文件名派生，例如 `reps/winston_churchill.yaml` 对应 `winston_churchill`；加载器直接扫描 `reps/`，不再通过 index 重复索引代表。venue 同理由加载器扫描 `venues/` 发现。

`storyline.yaml` 中的事件只描述代表无法直接控制的外部变化，例如战线报告、外国政府来函或时间压力。代表的发言、提案、签署与命令属于运行时行动，不预写为剧情事件。

`mechanism.yaml` 不属于场景包设计。`mechanism.py` 当前只保留为空占位文件，不参与加载，也不承载任何规则。比例校验、草案版本、签署状态、时间推进和终局检查属于所有场景共享的推演能力，应在 `src/` 的通用引擎中实现。

## 当前模板场景

模板采用“雅尔塔会议预备会：莫斯科‘百分比协定’”。正式历史背景是 1944 年第四次莫斯科会议（TOLSTOY）；“雅尔塔会议预备会”是便于模联理解的场景化标题，不是历史上的正式会议名称。

四名代表均为独立 Agent：

- 温斯顿·丘吉尔：英国最终政治签署人；
- 约瑟夫·斯大林：苏联最终政治签署人；
- 安东尼·艾登：英国执行条款谈判者和独立副署人；
- 维亚切斯拉夫·莫洛托夫：苏联执行条款谈判者和独立副署人。

两位首脑共同签署可以形成政治谅解；只有两位外长也副署同一版本，才形成满足完整结束条件的可执行草案。这样四个 Agent 都拥有改变结局的实际权力。

## 建议的最小运行闭环

1. 按固定文件名加载 `index.yaml`、`background.md`、`storyline.yaml`，并扫描 `venues/*.yaml` 与 `reps/*.yaml`；
2. 由通用引擎建立会议时钟、草案、签署和事件记录等运行时状态；
3. 为四张角色卡分别构建经过可见性过滤的 Agent 上下文；
4. 主席团按轮次接收发言或结构化行动；
5. 通用引擎校验并执行提案、认可、撤回和时间推进；
6. 按 `storyline.yaml` 的条件投递外部事件；
7. 通用引擎检查结束条件，结束推演并生成会议总结。

完整字段定义见 [`docs/scenario-schema.md`](docs/scenario-schema.md)。实现引擎前先阅读根目录 `AGENTS.md`；编辑模板场景时还必须阅读 `scenario-template/AGENTS.md`。场景 schema 调整时，需要同步更新字段文档、模板和受影响的项目概览。
