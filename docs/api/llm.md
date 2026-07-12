# LLM

| 类/函数 | 说明 |
|---|---|
| `LLMClient(config, usage_sink=None)` | OpenAI 兼容 chat 客户端 |
| `LLMClient.chat(role, messages, thinking_enabled=True, ...)` | 非流式调用: 角色路由 + thinking 参数 + 重试 |
| `LLMClient.chat_stream(role, messages, tools=None, ...)` | 流式调用, 异步生成 `StreamDelta`; 支持 function calling |
| `LLMClient.resolve_route(role)` | 返回 (provider, base_url, model) |
| `ChatMessage` | 消息体; role 含 `tool`, 可带 `tool_calls`/`tool_call_id` 回喂 function calling |
| `stream.py: ThinkDelta/TextDelta/ToolCallDelta/UsageDelta` | 类型化增量, 上层不接触原始 chunk |
| `UsageRecord` / `UsageCollector` | 用量记录结构 |

约束: 错误信息经 `sanitize_text` 脱敏后再抛出; usage 含 `cache_hit_tokens` / `thinking_enabled`; `chat_stream` 只在首个增量前重试(已吐字断流直接抛错, 见 design/designer/03§7.3); tool_calls 参数碎片在 llm 层拼装, 完整才交付.
