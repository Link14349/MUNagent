#!/usr/bin/env python3
"""直接调用 LLM 并打印响应 — 用法: python scripts/llm_smoke_test.py"""

from __future__ import annotations

import asyncio
import sys

from munagent.config import load_config, mask_api_key
from munagent.llm import ChatMessage, LLMClient


async def main() -> None:
    role = sys.argv[1] if len(sys.argv) > 1 else "delegate"
    prompt = sys.argv[2] if len(sys.argv) > 2 else "用一句话介绍古巴导弹危机。"

    config = load_config()
    client = LLMClient(config)

    provider, base_url, model = client.resolve_route(role)
    key = config.providers[config.roles[role].provider].api_key
    print(f"role={role}  model={model}  provider={provider}")
    print(f"url={base_url}  key={mask_api_key(key)}")
    print(f"prompt: {prompt!r}")
    print("-" * 40)

    text = await client.chat(
        role,
        [ChatMessage(role="user", content=prompt)],
        max_tokens=256,
        thinking_enabled=False,
    )

    print("响应:")
    print(text)


if __name__ == "__main__":
    asyncio.run(main())
