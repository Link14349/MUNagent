# 安全

| 函数 | 说明 |
|---|---|
| `sanitize_text(text) -> str` | 脱敏日志/异常中的 api key |
| `sanitize_exception(exc) -> str` | 异常转安全字符串 |

约束: key 不进事件日志; LLM 层抛错前必须过脱敏.
