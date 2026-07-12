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

    venue_timezone = scenario.venues[0].timezone

    def on_event(e):
        _print_event(e, timezone=venue_timezone)

    engine = Engine(
        scenario,
        config,
        master_seed=args.seed,
        max_steps=args.max_steps,
        db_path=args.db,
        on_event=on_event,
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


def _cmd_resume(args: argparse.Namespace) -> int:
    """断点续推: 从事件流重建状态, 继续推演."""
    from munagent.core.bus import EventBus
    from munagent.core.reducer import reduce
    from munagent.core.scenario import load_scenario

    config = load_config()
    scenario = load_scenario(args.scenario)

    async def run() -> int:
        bus = EventBus(args.db, args.session)
        await bus.init_db()
        session = await bus.get_session()
        if session is None:
            print(f"会话不存在: {args.session}", file=sys.stderr)
            return 1

        # 从事件流重建状态
        events = await bus.query("god")
        state = reduce(events, args.session)
        await bus.close()

        print(colorize(f"=== 续推: {session['id']} ===", "cyan"))
        print(colorize(f"已恢复 {len(events)} 事件, 状态: {state.session_status}", "dim"))
        for vid, v in state.venues.items():
            print(colorize(f"  会场 {vid}: {v.phase}, 发言{v.mod_speech_count}次, 指令队列{len(state.backroom_queue)}", "dim"))
        print()

        # 用已有的 master_seed 续推
        engine = Engine(
            scenario,
            config,
            master_seed=session.get("master_seed") or 0,
            max_steps=args.max_steps,
            db_path=args.db,
        )
        engine.session_id = args.session  # 复用同一会话 id
        result = await engine.run()
        print()
        print(colorize(f"=== 续推完成: +{result.total_steps} 步, {len(result.events)} 事件 ===", "cyan"))
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
        # 尝试从场景包获取时区
        from munagent.core.scenario import load_scenario
        from pathlib import Path
        tz = "UTC"
        # 从 sessions 表的 scenario_id 推断场景路径(简化: 用默认)
        events = await bus.query(args.viewpoint)
        for e in events:
            _print_event(e, timezone=tz)
        await bus.close()
        return 0

    return asyncio.run(run())


def _print_event(e, timezone: str = "UTC") -> None:
    """彩色输出单个事件, 按会场时区显示本地时间."""
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
        "motion": "green",
        "motion_ruling": "green",
    }
    color = color_map.get(e.type, "white")
    text = render(e, timezone=timezone)
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

    resume_parser = sub.add_parser("resume", help="断点续推")
    resume_parser.add_argument("session", help="会话 ID")
    resume_parser.add_argument("scenario", help="场景包目录路径")
    resume_parser.add_argument("--max-steps", type=int, default=20, help="续推最大步数")
    resume_parser.add_argument("--db", default="munagent.db", help="SQLite 路径")
    resume_parser.set_defaults(func=_cmd_resume)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
