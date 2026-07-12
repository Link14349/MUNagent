# engine 模块 API

## `engine.Engine(scenario, config, *, master_seed, max_steps, db_path)`
P1 推演引擎: 单会场 + 三 Agent 闭环.

- `run() -> RunResult`: 执行推演, 返回全部事件
- `RunResult(session_id, total_steps, events)`

## CLI
- `munagent run <scenario> --max-steps N [--seed <int>] [--db <path>]`
- `munagent replay <session> --viewpoint god|seat:<id> [--db <path>]`

## 运行时 stats
- `Engine._stats`: 从场景包 `stats.yaml` 初始化的当前值; DM 判定的 `stat_changes` 经 `_apply_stat_changes` 落在这里
- `_format_stats(entity_ids=None)`: 渲染为 prompt 文本; None=全量(DM 判定上下文用)
- `_stats_for_seat_text(seat_id)`: 按场景包 visibility 过滤后的该席位可见 stats(进代表 L4)
- DM 的 `assess_feasibility` 上下文含全量 stats——解职/政变/弹劾类行动的概率档位由"议会支持/军队掌控"等数值支撑, 不再凭空拍

## 草案线(D16, 见设计06§2)
- `Engine._agenda_no` / `_line_seq`: 当前正式 Mod 议程序号与递交序; 每次从 Unmod(或 Opening)进入 Mod 时 `_on_enter_moderated_caucus` 更新(表决/Voting 中断恢复不换序号)
- `Engine._doc_lines`: "D1.2" -> {status: active|merged|rejected|superseded, versions:[...]}; 启动时从存档回灌
- `_assign_doc_number(draft, author)`: 线号/版本分配与修订/分叉判定——提交者在最新版联署名单内且线 active → 同线新版本; 否则 fork 新线(forked_from)
- `_resolve_doc_ref(ref)`: 编号/版本号/标题 → (线号, 版本info); 动议表决的 motion_target 由此解析
- `_diff_summary(old, new)`: 确定性 diff 摘要, 提交时算好存 payload(render 保持纯函数)
- `_supersede_other_lines(...)`: 一版通过, 同议程其余 active 线批量发 superseded 事件
- 联合指令/公报 directive_id = "D<议程>.<递交序>-v<版本>"; 个人指令/危机笔记保留内部 id, 不进公开编号
- `_docs_dossier(seat_id)`: 该席位可见现行文件的原文档案(已通过/待决当前版/本人私密指令/本人收到的已送达危机笔记), 注入 turn/vote 上下文的<当前有效文件>区; delivered 标记随 note_delivered 事件持久化并在续推时回灌

## 时间推进
- `_pending_effect_times` / `_format_pending_effects`: 从 `adjudication` 事件汇总在途 `takes_effect_at`(故事时间尚未到达)
- `_validate_clock_advance(current, target, max_jump_hours=24, pending_effect_times=...) -> str | None`: 主席跳时校验(只向前/限步长/不得越过在途生效点/归一化 UTC Z)
- 危机更新播报后引擎调 `chair.clock_decision(...)`; 合法则 `sm.advance_clock_to` + `clock_advance` 事件(actor=chair, 带 reason)
- `adjudication` payload 含 `takes_effect_at`(UTC Z)
- 续推: `VenueStateMachine.replay_from_events` 从已落库事件恢复 phase/时钟; 有历史事件时跳过 Opening `phase_change`
- DM 判定(`assess_feasibility`/`write_result`)传入 `story_time`; 场景包加载时 `start_story_time`/timeline/arc trigger 归一化为 UTC Z
