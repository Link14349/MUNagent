#!/usr/bin/env python3
"""流式调用 LLM 并实时打印 — 验证 chat_stream 的三通道输出.

用法:
  python scripts/llm_stream_test.py                        # 默认 designer 角色, 演示 thinking+吐字
  python scripts/llm_stream_test.py --no-think             # 关 thinking
  python scripts/llm_stream_test.py --tools                # 演示 function calling(只打印调用, 不执行)
  python scripts/llm_stream_test.py -r delegate -p "你好"  # 指定角色与 prompt
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from munagent.config import load_config, mask_api_key
from munagent.llm import (
    ChatMessage,
    LLMClient,
    TextDelta,
    ThinkDelta,
    ToolCallDelta,
    UsageDelta,
)

DIM = "\033[2m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RESET = "\033[0m"

DEMO_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取场景包内的一个文件, 返回其文本内容",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "包内相对路径"}},
                "required": ["path"],
            },
        },
    }
]

TOOLS_PROMPT = "请读取 seats/premier.yaml, 告诉我总理这个席位的人格设定."
PLAIN_PROMPT = "用三句话介绍法国1848年二月革命的导火索。"


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-r", "--role", default="designer")
    ap.add_argument("-p", "--prompt", default=None)
    ap.add_argument("--tools", action="store_true", help="带上演示工具定义")
    ap.add_argument("--no-think", action="store_true", help="关闭 thinking")
    args = ap.parse_args()

    prompt = args.prompt or (TOOLS_PROMPT if args.tools else PLAIN_PROMPT)

    config = load_config()
    client = LLMClient(config)
    provider, base_url, model = client.resolve_route(args.role)
    key = config.providers[config.roles[args.role].provider].api_key
    print(f"role={args.role}  model={model}  provider={provider}")
    print(f"url={base_url}  key={mask_api_key(key)}  thinking={not args.no_think}")
    print(f"prompt: {prompt!r}")
    print("-" * 60)

    in_think = False
    async for delta in client.chat_stream(
        args.role,
        [ChatMessage(role="user", content=prompt)],
        tools=DEMO_TOOLS if args.tools else None,
        max_tokens=1024,
        thinking_enabled=not args.no_think,
    ):
        match delta:
            case ThinkDelta(text=t):
                if not in_think:
                    print(f"{DIM}[思考] ", end="")
                    in_think = True
                print(f"{DIM}{t}{RESET}", end="", flush=True)
            case TextDelta(text=t):
                if in_think:
                    print(RESET + "\n" + "-" * 60)
                    in_think = False
                print(t, end="", flush=True)
            case ToolCallDelta(id=cid, name=name, arguments=arguments):
                if in_think:
                    print(RESET + "\n" + "-" * 60)
                    in_think = False
                print(f"\n{YELLOW}[工具调用] id={cid} name={name}")
                print(f"           arguments={arguments}{RESET}")
            case UsageDelta() as u:
                print(
                    f"\n{CYAN}[用量] prompt={u.prompt_tokens} completion={u.completion_tokens} "
                    f"cache_hit={u.cache_hit_tokens} cache_miss={u.cache_miss_tokens}{RESET}"
                )
    print()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
