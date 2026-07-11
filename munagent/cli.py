"""MUNagent 命令行入口."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from munagent import __version__
from munagent.config import load_config
from munagent.core.render import render
from munagent.engine import ANSI_COLORS, Engine, colorize


def _cmd_version(_: argparse.Namespace) -> int:
    print(f"munagent {__version__}")
    return 0


def _cmd_config_test(args: argparse.Namespace) -> int:
    config = load_config()
    from munagent.llm import LLMClient

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
    except Exception as exc:  # noqa: BLE001
        print(f"连接测试失败: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    from munagent.core.scenario import load_scenario

    config = load_config()
    scenario = load_scenario(args.scenario)

    engine = Engine(
        scenario,
        config,
        master_seed=args.seed,
        max_steps=args.max_steps,
        db_path=args.db,
        on_event=_print_event,
    )

    async def run() -> int:
        print(colorize(f"=== 推演开始: {scenario.manifest.title} ===", "cyan"))
        print(colorize(f"会场: {scenario.venues[0].name}", "dim"))
        print(colorize(f"席位: {', '.join(s.name for s in scenario.seats_of(scenario.venues[0].id))}", "dim"))
        print()
        result = await engine.run()
        print()
        print(colorize(f"=== 推演完成: {result.session_id} ({result.total_steps} 步, {len(result.events)} 事件) ===", "cyan"))
        print(colorize(f"master_seed: {engine.master_seed}", "dim"))
        print(colorize(f"回放: munagent replay {result.session_id} --viewpoint god --db {args.db}", "dim"))
        return 0

    return asyncio.run(run())


def _cmd_replay(args: argparse.Namespace) -> int:
    from munagent.core.bus import EventBus

    async def run() -> int:
        bus = EventBus(args.db, args.session)
        await bus.init_db()
        session = await bus.get_session()
        if session is None:
            print(f"会话不存在: {args.session}", file=sys.stderr)
            return 1
        print(colorize(f"=== 回放: {session['id']} ===", "cyan"))
        print(colorize(f"场景: {session['scenario_id']}", "dim"))
        print(colorize(f"master_seed: {session['master_seed']}", "dim"))
        print()
        events = await bus.query(args.viewpoint)
        for e in events:
            _print_event(e)
        await bus.close()
        return 0

    return asyncio.run(run())


def _print_event(e) -> None:
    """彩色输出单个事件."""
    color_map = {
        "speech": "white",
        "speech_thought": "dim",
        "phase_change": "magenta",
        "crisis_update": "yellow",
        "adjudication": "cyan",
        "directive_submitted": "green",
        "directive_status": "green",
        "clock_advance": "dim",
        "vote_call": "magenta",
        "vote_cast": "white",
        "vote_result": "magenta",
    }
    color = color_map.get(e.type, "white")
    text = render(e)
    print(colorize(text, color))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="munagent", description="MUNagent CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    version_parser = sub.add_parser("version", help="显示版本号")
    version_parser.set_defaults(func=_cmd_version)

    test_parser = sub.add_parser("config-test", help="测试默认 provider 连通性")
    test_parser.add_argument("--provider", default=None, help="provider 名称")
    test_parser.set_defaults(func=_cmd_config_test)

    run_parser = sub.add_parser("run", help="运行推演")
    run_parser.add_argument("scenario", help="场景包目录路径")
    run_parser.add_argument("--max-steps", type=int, default=20, help="最大步数")
    run_parser.add_argument("--seed", type=int, default=None, help="master_seed(可复现)")
    run_parser.add_argument("--db", default="munagent.db", help="SQLite 路径")
    run_parser.set_defaults(func=_cmd_run)

    replay_parser = sub.add_parser("replay", help="回放会话")
    replay_parser.add_argument("session", help="会话 ID")
    replay_parser.add_argument(
        "--viewpoint",
        default="god",
        help="视角: god | seat:<id>",
    )
    replay_parser.add_argument("--db", default="munagent.db", help="SQLite 路径")
    replay_parser.set_defaults(func=_cmd_replay)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
