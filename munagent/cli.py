"""MUNagent 命令行入口."""

from __future__ import annotations

import argparse
import asyncio
import sys

from munagent import __version__
from munagent.config import load_config
from munagent.llm import LLMClient


def _cmd_version(_: argparse.Namespace) -> int:
    print(f"munagent {__version__}")
    return 0


def _cmd_config_test(args: argparse.Namespace) -> int:
    config = load_config()
    client = LLMClient(config)

    async def run() -> None:
        record = await client.test_provider(args.provider)
        provider_name = args.provider or config.default_provider_name()
        print("连接测试成功")
        print(f"  provider: {provider_name}")
        print(f"  model: {record.model}")
        print(f"  prompt_tokens: {record.prompt_tokens}")
        print(f"  completion_tokens: {record.completion_tokens}")

    try:
        asyncio.run(run())
    except Exception as exc:  # noqa: BLE001 — CLI 需友好报错
        print(f"连接测试失败: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="munagent", description="MUNagent CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    version_parser = sub.add_parser("version", help="显示版本号")
    version_parser.set_defaults(func=_cmd_version)

    test_parser = sub.add_parser("config-test", help="测试默认 provider 连通性")
    test_parser.add_argument(
        "--provider",
        default=None,
        help="provider 名称(默认 deepseek)",
    )
    test_parser.set_defaults(func=_cmd_config_test)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
