"""CLI 入口."""

from __future__ import annotations

import argparse
import asyncio
import sys

from munagent import __version__
from munagent.config import load_config, mask_api_key
from munagent.llm import ChatMessage, LLMClient
from munagent.security import sanitize_text


def _cmd_version(_: argparse.Namespace) -> int:
    print(f"munagent {__version__}")
    return 0


async def _test_provider(config, role: str = "delegate") -> tuple[bool, str]:
    """发 1 token 补全验证连通性."""
    try:
        client = LLMClient(config)
        provider_name, base_url, model = client.resolve_route(role)
        key = config.providers[config.roles[role].provider].api_key
        if not key or key == "none":
            return False, "未配置 api_key (设置 MUNAGENT_API_KEY 或 ~/.munagent/config.yaml)"
        await client.chat(
            role,
            [ChatMessage(role="user", content="回复 ok")],
            max_tokens=16,
            thinking_enabled=False,
        )
        return True, f"provider={provider_name} model={model} url={base_url} key={mask_api_key(key)}"
    except Exception as exc:
        return False, sanitize_text(str(exc))


def _cmd_config_test(args: argparse.Namespace) -> int:
    try:
        config = load_config()
    except ValueError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 1

    ok, detail = asyncio.run(_test_provider(config, role=args.role))
    if ok:
        print(f"连接成功: {detail}")
        return 0
    print(f"连接失败: {detail}", file=sys.stderr)
    return 1


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from munagent.config import load_config
    from munagent.server.app import WEB_DIST

    config = load_config()
    host = args.host or config.server.host
    port = args.port or config.server.port
    if not WEB_DIST.is_dir():
        print(
            f"警告: 前端未构建 ({WEB_DIST}), 仅 API 可用。请执行: cd munagent/web && npm install && npm run build",
            file=sys.stderr,
        )
    print(f"MUNagent 服务: http://{host}:{port}")
    if args.reload:
        uvicorn.run(
            "munagent.server.app:create_app",
            host=host,
            port=port,
            reload=True,
            factory=True,
        )
    else:
        from munagent.server.app import create_app

        uvicorn.run(create_app(), host=host, port=port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="munagent", description="MUNagent CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version", help="显示版本号").set_defaults(func=_cmd_version)

    p_test = sub.add_parser("config-test", help="测试默认 LLM provider 连通性")
    p_test.add_argument("--role", default="delegate", help="用于路由的 Agent 角色名")
    p_test.set_defaults(func=_cmd_config_test)

    p_serve = sub.add_parser("serve", help="启动 Web 服务(FastAPI + 静态前端)")
    p_serve.add_argument("--host", default=None, help="监听地址(默认读配置)")
    p_serve.add_argument("--port", type=int, default=None, help="端口(默认读配置)")
    p_serve.add_argument("--reload", action="store_true", help="开发热重载(仅后端)")
    p_serve.set_defaults(func=_cmd_serve)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
