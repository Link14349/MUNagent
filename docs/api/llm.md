# LLM

| 类/函数 | 说明 |
|---|---|
| `LLMClient(config, usage_sink=None)` | OpenAI 兼容 chat 客户端 |
| `LLMClient.chat(role, messages, thinking_enabled=True, ...)` | 角色路由 + thinking 参数 + 重试 |
| `LLMClient.resolve_route(role)` | 返回 (provider, base_url, model) |
| `UsageRecord` / `UsageCollector` | 用量记录结构 |

约束: 错误信息经 `sanitize_text` 脱敏后再抛出; usage 含 `cache_hit_tokens` / `thinking_enabled`.
