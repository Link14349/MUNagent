"""MUNagent 本地会议服务与命令行客户端。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config.load import load_config
from engine.end_conditions import LLMTextEndConditionEvaluator
from llm import LLM
from service import MeetingRun, VenueEventConsoleReporter, create_http_server


DEFAULT_URL = "http://127.0.0.1:8765"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="munagent",
        description="启动 MUNagent 单会场服务，或从命令行查询运行状态。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="加载场景并启动本地会议服务")
    serve.add_argument("scenario", type=Path, help="场景包目录")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--seed", default=None, help="DM 投点种子；省略时安全随机生成")
    serve.add_argument("--provider", default=None, help="LLM provider 名")
    serve.add_argument("--model", default=None, help="代表、主席、DM 与终局裁判模型")
    serve.add_argument("--config", type=Path, default=None, help="配置文件路径")
    serve.add_argument(
        "--thinking",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="代表、主席和 DM 是否启用 thinking",
    )
    serve.add_argument(
        "--no-llm",
        action="store_true",
        help="不连接模型，仅用于服务和存档冒烟测试",
    )

    for command, help_text in (
        ("status", "查看会场当前状态"),
        ("events", "查看公开会场事件"),
        ("watch", "持续查看状态和新增公开事件"),
        ("stop", "停止推演但保留状态服务"),
        ("shutdown", "停止推演并关闭状态服务"),
    ):
        sub = subparsers.add_parser(command, help=help_text)
        sub.add_argument("--url", default=DEFAULT_URL)
        if command in {"status", "events"}:
            sub.add_argument("--json", action="store_true", help="输出完整 JSON")
        if command in {"events", "watch"}:
            sub.add_argument("--venue", default=None, help="会场 ID")
            sub.add_argument("--after", type=int, default=-1, help="仅返回此事件 ID 之后")
        if command == "events":
            sub.add_argument("--limit", type=int, default=100)
        if command == "watch":
            sub.add_argument("--interval", type=float, default=1.0)

    return parser


def main() -> None:
    try:
        code = _main()
    except KeyboardInterrupt:
        code = 130
    except (HTTPError, URLError, OSError, RuntimeError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        code = 2
    raise SystemExit(code)


def _main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        return _serve(args)
    if args.command == "status":
        payload = _request_json(args.url, "/api/status")
        _print_json(payload) if args.json else _print_status(payload)
        return 0
    if args.command == "events":
        payload = _request_json(
            args.url,
            "/api/events",
            query={
                "venue": args.venue,
                "after": args.after,
                "limit": args.limit,
            },
        )
        _print_json(payload) if args.json else _print_events(payload)
        return 0
    if args.command == "watch":
        return _watch(args)
    if args.command == "stop":
        _print_json(_request_json(args.url, "/api/stop", method="POST"))
        return 0
    if args.command == "shutdown":
        _print_json(_request_json(args.url, "/api/shutdown", method="POST"))
        return 0
    raise RuntimeError(f"未知命令: {args.command}")


def _serve(args: argparse.Namespace) -> int:
    scenario_path = args.scenario.expanduser().resolve()
    if not scenario_path.is_dir():
        raise ValueError(f"场景包目录不存在: {scenario_path}")

    llm_factory = None
    chair_llm_factory = None
    dm_llm_factory = None
    evaluator = None
    runtime_config: dict[str, object] = {"llm_enabled": not args.no_llm}
    if not args.no_llm:
        config_path = args.config.expanduser() if args.config is not None else None
        config = load_config(path=config_path)
        provider = args.provider or config.default_provider
        model = args.model or config.default_model
        provider_config = config.providers.get(provider)
        if provider_config is None:
            known = ", ".join(sorted(config.providers)) or "(无)"
            raise ValueError(f"未知 provider {provider!r}，可选：{known}")
        if not provider_config.api_key or provider_config.api_key == "none":
            raise ValueError(
                f"provider {provider!r} 未配置 api_key；请设置配置文件或 "
                "MUNAGENT_API_KEY"
            )

        def make_llm(_subject: object) -> LLM:
            return LLM(
                provider=provider,
                model=model,
                thinking=args.thinking,
                config=config,
            )

        llm_factory = make_llm
        chair_llm_factory = make_llm
        dm_llm_factory = make_llm
        evaluator = LLMTextEndConditionEvaluator(
            LLM(
                provider=provider,
                model=model,
                thinking=False,
                config=config,
            )
        )
        runtime_config.update(
            {
                "provider": provider,
                "model": model,
                "thinking": bool(args.thinking),
                "text_end_condition_judge": True,
            }
        )
    else:
        runtime_config["text_end_condition_judge"] = False

    meeting = MeetingRun(
        scenario_path,
        seed=args.seed,
        llm_factory=llm_factory,
        chair_llm_factory=chair_llm_factory,
        dm_llm_factory=dm_llm_factory,
        text_end_condition_evaluator=evaluator,
        runtime_config=runtime_config,
    )
    server = create_http_server(meeting, host=args.host, port=args.port)
    event_reporter = VenueEventConsoleReporter(meeting.scenario)
    bound_host, bound_port = server.server_address[:2]
    base_url = f"http://{bound_host}:{bound_port}"
    try:
        meeting.start()
        print(f"MUNagent 服务已启动：{base_url}")
        print(f"运行种子：{meeting.seed}")
        print(f"运行存档：{meeting.run_dir}")
        print("会场事件将直接输出到本终端：")
        print(f"状态命令：python src/main.py status --url {base_url}")
        print(f"持续观察：python src/main.py watch --url {base_url}")
        if args.no_llm:
            print("注意：--no-llm 模式不会运行 Agent 或判断文本终局条件。")
        event_reporter.start()
        server.serve_forever(poll_interval=0.25)
    finally:
        if not meeting.done:
            meeting.stop("service_shutdown")
            meeting.wait(timeout=meeting.simulator.shutdown_grace_s + 1.0)
        meeting.persist_archive()
        event_reporter.stop()
        event_reporter.join(timeout=1.0)
        server.server_close()
    return 0


def _watch(args: argparse.Namespace) -> int:
    if args.interval <= 0:
        raise ValueError("interval 必须大于 0")
    after = args.after
    previous_state: str | None = None
    while True:
        status = _request_json(args.url, "/api/status")
        state = str(status.get("state"))
        if state != previous_state:
            _print_status(status)
            previous_state = state
        payload = _request_json(
            args.url,
            "/api/events",
            query={"venue": args.venue, "after": after, "limit": 500},
        )
        events = payload.get("events", [])
        if isinstance(events, list) and events:
            _print_events(payload)
            ids = [event.get("id") for event in events if isinstance(event, dict)]
            numeric_ids = [event_id for event_id in ids if isinstance(event_id, int)]
            if numeric_ids:
                after = max(numeric_ids)
        if state in {"ended", "stopped", "failed"}:
            return 0 if state != "failed" else 1
        time.sleep(args.interval)


def _request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    query: dict[str, object | None] | None = None,
) -> dict[str, Any]:
    from urllib.parse import urlencode

    url = base_url.rstrip("/") + path
    if query:
        encoded = urlencode(
            {key: value for key, value in query.items() if value is not None}
        )
        if encoded:
            url += "?" + encoded
    request = Request(url, method=method)
    try:
        with urlopen(request, timeout=10.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("服务返回值不是 JSON 对象")
    return payload


def _print_status(payload: dict[str, Any]) -> None:
    scenario = payload.get("scenario") or {}
    print(
        f"[{payload.get('state', 'unknown')}] "
        f"{scenario.get('title', '')}  run={payload.get('run_id')}"
    )
    print(f"剧情时间：{payload.get('story_time')}")
    print(f"随机种子：{payload.get('seed')}")
    for venue in payload.get("venues", []):
        agenda = venue.get("current_agenda") or {}
        print(
            f"会场 {venue.get('id')}：phase={venue.get('phase')} "
            f"agenda={agenda.get('id')} events={venue.get('event_count')} "
            f"pending={venue.get('pending_event_ids')}"
        )
    end_condition = payload.get("end_condition")
    if end_condition:
        print(
            f"终局条件 #{end_condition.get('condition_index')}："
            f"{end_condition.get('reason')}"
        )
    if payload.get("failure"):
        print(f"故障：{payload['failure']}")
    if payload.get("end_condition_warning"):
        print(f"终局裁判警告：{payload['end_condition_warning']}")
    print(f"存档：{payload.get('archive_path')}")


def _print_events(payload: dict[str, Any]) -> None:
    events = payload.get("events", [])
    if not events:
        print("没有符合条件的公开事件。")
        return
    for event in events:
        print(
            f"#{event.get('id')} {event.get('time')} "
            f"[{event.get('type')}/{event.get('status')}] "
            f"{event.get('content')}"
        )


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
