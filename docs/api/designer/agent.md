# 设计 Agent loop (`designer/agent.py`)

对应 [design/designer/03-agent-interaction.md](../../../design/designer/03-agent-interaction.md) §7.

## 公开类型

| 符号 | 说明 |
|---|---|
| `Agent` | 绑定 `scenario_id` + `chat_id`; 维护 `LLMClient` 与 `messages` |
| `LoopResult` | `done` / `aborted` / `failed` |
| `AgentEventSink` | 可选回调: `on_think_delta` / `on_text_delta` / `on_record_appended` |

## Agent 主要方法

| 方法 | 说明 |
|---|---|
| `async loop(user_prompt, max_steps=50) -> LoopResult` | 主循环: 流式 LLM + function calling, 工具上限 50, 单工具超时 600s |
| `add_message(msg, chat_record=?)` | 同步更新 `messages` 与 JSONL(有别名 `addMessage`) |
| `get_chat_messages() -> list[ChatMessage]` | system 段(G + 动态上下文) + JSONL 历史(有别名 `getChatMessages`) |

动态上下文(L 段)见 `designer/prompt.py` 的 `build_L`: 文件清单 + `manifest.yaml`/`venues.yaml` 全文 + 📎当前文件 + 最新 todo(有则); 每步 LLM 调用前刷新 L; 拼接顺序 G → H → L → 对话历史.

JSONL 回放: `tool_call`/`file_edit`/`todo` 以 **user 角色摘要**注入(前缀 `(历史…)`), 避免模型模仿 `[工具 xxx]` 正文格式; 若本轮输出含伪工具行且无 `tool_calls`, loop 会拦截并要求改用 function calling.

约束: `reasoning_content` 只推事件不落盘; tool_call JSONL 只存终态摘要; `write_file` 成功时由 loop 生成 `file_edit` unified diff.
