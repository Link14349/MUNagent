# LLM 模块使用说明

`src/llm/` 提供 OpenAI 兼容的异步 LLM 客户端,用于向配置的 provider 发送 `chat/completions` 请求.当前实现以**流式输出**为主:逐块返回 thinking 与正文,并支持随时停止.

配置读取由 `src/config/` 负责,默认从 `~/.munagent/config.yaml` 加载 API 地址与密钥.

## 依赖与运行环境

- Python 3.11+
- 运行时依赖:`httpx`,`pyyaml`(见仓库根目录 `pyproject.toml`)
- 开发/测试:`pytest`,`pytest-asyncio`

本地开发时,将 `src/` 加入模块搜索路径:

```bash
export PYTHONPATH=src
```

## 配置

### 配置文件位置

默认路径:`~/.munagent/config.yaml`

也可在构造 `LLM` 时传入 `config_path`,或在测试中注入 `AppConfig` 对象.

### 最小示例

```yaml
providers:
  deepseek:
    base_url: https://api.deepseek.com
    api_key: sk-你的密钥

# 以下可选;省略时使用内置默认值
default_provider: deepseek
default_model: deepseek-v4-flash
```

### 字段说明

| 字段 | 说明 |
|------|------|
| `providers.<name>.base_url` | Provider 根地址;模块会自动补全为 `{base_url}/v1/chat/completions` |
| `providers.<name>.api_key` | Bearer 令牌;为空或 `"none"` 时拒绝发起请求 |
| `default_provider` | 未显式指定 `LLM(provider=...)` 时使用的 provider 名 |
| `default_model` | 未显式指定 `LLM(model=...)` 时使用的模型名 |

### 环境变量覆盖

优先级:**环境变量 > YAML 文件 > 内置默认**.

| 变量 | 作用 |
|------|------|
| `MUNAGENT_API_KEY` | 覆盖 `providers.deepseek.api_key` |
| `MUNAGENT_BASE_URL` | 覆盖 `providers.deepseek.base_url` |

### 代码中加载配置

```python
from config import load_config

cfg = load_config()                          # ~/.munagent/config.yaml
cfg = load_config(path=Path("tests/fixtures/config.yaml"))
```

## 快速开始

### 流式消费增量

```python
import asyncio
from llm import ChatMessage, LLM, TextDelta, ThinkDelta

async def main() -> None:
    llm = LLM(
        provider="deepseek",
        model="deepseek-v4-flash",
        thinking=True,
    )
    messages = [ChatMessage(role="user", content="用一句话介绍雅尔塔会议.")]

    async for delta in llm.stream(messages):
        if isinstance(delta, ThinkDelta):
            print(f"[思考] {delta.text}", end="", flush=True)
        elif isinstance(delta, TextDelta):
            print(delta.text, end="", flush=True)

asyncio.run(main())
```

### 拼接完整正文

`complete()` 在内部消费流式响应,只拼接 `TextDelta`(thinking 不计入返回值):

```python
text = await llm.complete(messages, max_tokens=4096)
```

### 实时回调

`stream()` 与 `complete()` 均支持 `on_delta`,在每次产出增量时同步调用,适合刷 UI 或写日志:

```python
def on_delta(delta):
    if hasattr(delta, "text"):
        sys.stdout.write(delta.text)
        sys.stdout.flush()

await llm.complete(messages, on_delta=on_delta)
```

## 停止输出

任意时刻调用 `llm.stop()` 可中断当前流式请求.停止后,`stream()` / `complete()` 抛出 `LLMCancelledError`.

```python
import asyncio
from llm import ChatMessage, LLM, LLMCancelledError

async def main() -> None:
    llm = LLM()
    task = asyncio.create_task(
        llm.complete([ChatMessage(role="user", content="写一篇长文")])
    )
    await asyncio.sleep(2)
    llm.stop()
    try:
        await task
    except LLMCancelledError:
        print("已停止")

asyncio.run(main())
```

命令行测试中也可按 `Ctrl+C`;模块会调用 `stop()` 并退出.

### 重试策略

- 仅在**尚未产出任何增量**时,对网络错误与 5xx 进行指数退避重试(默认最多 3 次).
- 一旦开始吐字,中途断流**不会**静默重试,直接抛出 `RuntimeError`,避免上层已展示的内容与重试结果不一致.

## 命令行

模块自带简易 CLI,用于本地连通性测试:

```bash
PYTHONPATH=src python -m llm.llm "用一句话介绍雅尔塔会议."
PYTHONPATH=src python -m llm.llm "..." --model deepseek-v4-pro --no-thinking
PYTHONPATH=src python -m llm.llm "..." --provider deepseek --max-tokens 2048
```

参数:

| 参数 | 说明 |
|------|------|
| `prompt` | 用户消息;省略时使用默认提示 |
| `--provider` | 覆盖 config 中的默认 provider |
| `--model` | 模型名,如 `deepseek-v4-flash`,`deepseek-v4-pro` |
| `--thinking` / `--no-thinking` | 是否向 API 发送 `thinking: enabled` |
| `--max-tokens` | 单次 completion 上限,默认 `4096` |

终端输出规则:thinking 以灰色显示,正文正常输出,末尾打印 token 用量.

也可在代码中调用 `run_interactive()`:

```python
from llm import LLM, run_interactive

llm = LLM(model="deepseek-v4-flash")
await run_interactive(llm, "你好", system="你是模联推演助手.")
```

## API 参考

### 公开导出(`from llm import ...`)

| 名称 | 说明 |
|------|------|
| `LLM` | 异步客户端 |
| `ChatMessage` | 对话消息 |
| `ThinkDelta` | thinking 增量 |
| `TextDelta` | 正文增量 |
| `UsageDelta` | 流末尾用量 |
| `StreamDelta` | 上述三种增量的联合类型 |
| `LLMCancelledError` | 用户主动停止 |
| `run_interactive` | 流式打印到 stdout 的辅助函数 |

### `LLM`

```python
LLM(
    *,
    provider: str | None = None,
    model: str | None = None,
    thinking: bool = True,
    config: AppConfig | None = None,
    config_path: Path | None = None,
    timeout_s: float = 120.0,
    stream_read_timeout_s: float = 60.0,
    max_retries: int = 3,
    transport: httpx.AsyncBaseTransport | None = None,
)
```

| 参数 | 说明 |
|------|------|
| `provider` | provider 名,对应 config 中 `providers` 的键 |
| `model` | 模型 ID,原样写入请求体 `model` 字段 |
| `thinking` | `True` 时发送 `{"thinking": {"type": "enabled"}}`;`False` 为 `disabled` |
| `config` | 注入完整配置,跳过磁盘读取(测试常用) |
| `config_path` | 指定 YAML 路径 |
| `stream_read_timeout_s` | 相邻 SSE 行之间的读超时(秒) |
| `transport` | 注入 `httpx` transport,用于 mock 测试 |

#### `async stream(messages, *, max_tokens=4096, tools=None, tool_choice=None, on_delta=None)`

异步迭代 `StreamDelta`.请求始终带 `stream: true` 与 `stream_options.include_usage: true`.
传入 `tools` 时写入请求体,并可选用 `tool_choice`(`auto` / `none` / `required` 或 OpenAI 对象形式).

#### `async complete(messages, *, max_tokens=4096, tools=None, tool_choice=None, on_delta=None) -> str`

消费 `stream()` 并返回拼接后的正文(不含 thinking / tool_call 增量).

#### `stop() -> None`

设置停止标志;可在另一协程或线程中调用.

### `ChatMessage`

```python
ChatMessage(role="user", content="...")
ChatMessage(role="system", content="...")
ChatMessage(role="assistant", content="...")
ChatMessage(
    role="assistant",
    content="",
    tool_calls=[ToolCall(id="call_1", name="send_message", arguments='{"content":"hi"}')],
)
ChatMessage(role="tool", content="执行结果", tool_call_id="call_1", name="send_message")
```

### `ToolSpec`

发给模型的 function tool 定义:

```python
ToolSpec(
    name="send_message",
    description="以本代表身份公开发言",
    parameters={
        "type": "object",
        "properties": {"content": {"type": "string"}},
        "required": ["content"],
    },
)
```

### 流式增量类型

| 类型 | 字段 | 含义 |
|------|------|------|
| `ThinkDelta` | `text` | 模型 reasoning 片段;仅展示,不回喂上下文 |
| `TextDelta` | `text` | 可见回复正文 |
| `ToolCallDelta` | `index`, `id`, `name`, `arguments` | 流式 tool_call 片段;`arguments` 为本次增量 |
| `ToolCallsDelta` | `calls` | 流结束时组装出的完整 `ToolCall` 元组 |
| `UsageDelta` | `prompt_tokens`, `completion_tokens`, `finish_reason` | 流结束时的用量汇总 |

判断方式:

```python
match delta:
    case ThinkDelta(text=t):
        ...
    case TextDelta(text=t):
        ...
    case ToolCallDelta() as tc:
        ...
    case ToolCallsDelta(calls=calls):
        ...
    case UsageDelta() as u:
        ...
```

或使用 `isinstance()`.

### 工具调用流式示例

```python
tools = [
    ToolSpec(
        name="send_message",
        description="公开发言",
        parameters={
            "type": "object",
            "properties": {"content": {"type": "string"}},
            "required": ["content"],
        },
    )
]

async for delta in llm.stream(messages, tools=tools, tool_choice="auto"):
    if isinstance(delta, ToolCallsDelta):
        for call in delta.calls:
            # 执行工具后,把结果以 role=tool 的 ChatMessage 回喂下一轮
            ...
```

`stream(..., tools=...)` 会把 tools 写入请求体;流中先产出零到多个 `ToolCallDelta`,结束时若拼出完整调用再产出 `ToolCallsDelta`.

## 请求体约定

模块向 provider 发送的 POST 体核心字段:

```json
{
  "model": "deepseek-v4-flash",
  "messages": [{"role": "user", "content": "..."}],
  "max_tokens": 4096,
  "stream": true,
  "stream_options": {"include_usage": true},
  "thinking": {"type": "enabled"},
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "send_message",
        "description": "...",
        "parameters": {"type": "object", "properties": {}}
      }
    }
  ],
  "tool_choice": "auto"
}
```

`tools` / `tool_choice` 仅在调用方传入时写入.

兼容 OpenAI Chat Completions 流式 SSE 格式:每行 `data: {...}`,结束为 `data: [DONE]`.

## 错误处理

| 异常 | 典型原因 |
|------|----------|
| `KeyError` | `provider` 名在 config 中不存在 |
| `ValueError` | 对应 provider 未配置 `api_key`,或只传了 `tool_choice` 未传 `tools` |
| `LLMCancelledError` | 调用了 `stop()` 或 CLI 收到中断信号 |
| `RuntimeError` | HTTP 失败,读超时,或已开始吐字后的断流 |

HTTP 4xx/5xx 响应体前 500 字符会附加在错误信息中,便于排查.

## 测试

单元测试位于 `tests/test_llm.py`,通过 `httpx.MockTransport` mock 响应,**不消耗真实 API**.

```bash
PYTHONPATH=src pytest tests/test_llm.py -v
```

测试覆盖:流式增量解析,thinking 开关,自定义模型,中途 `stop()`,正文拼接.

注入 mock 配置示例:

```python
from config.models import AppConfig, ProviderConfig
from llm import LLM
import httpx

config = AppConfig(
    providers={"deepseek": ProviderConfig(
        base_url="https://api.deepseek.com",
        api_key="test-key",
    )},
)
llm = LLM(config=config, transport=httpx.MockTransport(handler))
```

## 当前边界

以下能力**尚未**实现,调用方请勿假设存在:

- 非流式(一次性 JSON)请求模式
- 多 provider 角色路由(如 chair,delegate 分模型)
- Token 用量持久化与计费统计
- 自动把 thinking 内容写回对话历史
- Agent 层自动执行 tool 并回喂(本模块只负责请求/解析)

如需上述能力,应在引擎层或扩展本模块时同步更新本文档.
