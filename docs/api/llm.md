# llm 模块 API

## `LLMClient(config, ...)`
OpenAI 兼容异步客户端. 经 `resolve_role` 路由 provider/model; 按 role+task 开关 thinking.

## `LLMClient.chat(request: ChatRequest) -> str`
发起补全. 5xx/超时指数退避重试(默认 3 次). 错误信息经 `sanitize_text` 脱敏.

## `LLMClient.test_provider(provider_name=None) -> UsageRecord`
最小连通性测试(约 1 token).

## `resolve_thinking(role, task, *, phase, scope) -> bool`
Thinking 开关纯函数, 见 `05-agent-harness.md` §5.

## `UsageRecord`
用量记录字段: `prompt_tokens`, `completion_tokens`, `cache_hit_tokens`, `cache_miss_tokens`, `thinking_enabled`.
