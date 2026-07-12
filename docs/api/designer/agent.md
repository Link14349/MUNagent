# 设计 Agent loop (`designer/agent.py`)

占位, 尚无公开接口(空壳模块). 实现时对应 [design/designer/03-agent-interaction.md](../../../design/designer/03-agent-interaction.md) §7 的 loop 设计: 原生 function calling + 流式三通道(reasoning_content/content/tool_calls), 终止条件为响应无 tool_calls, 单轮工具调用上限 30 次.
