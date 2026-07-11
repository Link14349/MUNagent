# security 模块 API

## `sanitize_text(text) -> str`
剥离日志/异常中的 api key、Bearer token 等敏感片段. **事件落地与 LLM 报错必须先过此函数.**
