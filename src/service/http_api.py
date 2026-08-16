"""仅使用标准库实现的本地只读状态 HTTP API。"""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from urllib.parse import parse_qs, urlparse

from service.meeting_service import MeetingRun


class MeetingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        meeting: MeetingRun,
    ) -> None:
        self.meeting = meeting
        super().__init__(server_address, MeetingRequestHandler)


class MeetingRequestHandler(BaseHTTPRequestHandler):
    server: MeetingHTTPServer

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/health":
                self._json(HTTPStatus.OK, {"ok": True})
                return
            if parsed.path == "/api/status":
                self._json(HTTPStatus.OK, self.server.meeting.snapshot())
                return
            if parsed.path == "/api/events":
                query = parse_qs(parsed.query)
                venue = _single(query, "venue")
                after = _parse_int(_single(query, "after"), default=-1, field="after")
                limit = _parse_int(_single(query, "limit"), default=100, field="limit")
                events = self.server.meeting.public_events(
                    venue_id=venue,
                    after=after,
                    limit=limit,
                )
                self._json(
                    HTTPStatus.OK,
                    {"events": events, "count": len(events)},
                )
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})
        except (TypeError, ValueError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if parsed.path == "/api/stop":
            state = self.server.meeting.stop("api_stop")
            self._json(HTTPStatus.ACCEPTED, {"ok": True, "state": state.value})
            return
        if parsed.path == "/api/shutdown":
            state = self.server.meeting.stop("api_shutdown")
            self._json(HTTPStatus.ACCEPTED, {"ok": True, "state": state.value})
            threading.Thread(
                target=self.server.shutdown,
                name="http-shutdown",
                daemon=True,
            ).start()
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})

    def log_message(self, format: str, *args: object) -> None:
        # 会场事件由结构化存档记录，避免终端被每次轮询刷屏。
        return

    def _json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def create_http_server(
    meeting: MeetingRun,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> MeetingHTTPServer:
    if not host.strip():
        raise ValueError("host 不能为空")
    if port < 0 or port > 65_535:
        raise ValueError("port 必须位于 0..65535")
    return MeetingHTTPServer((host, port), meeting)


def _single(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    if len(values) != 1:
        raise ValueError(f"查询参数 {key} 不能重复")
    value = values[0].strip()
    return value or None


def _parse_int(value: str | None, *, default: int, field: str) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"查询参数 {field} 须为整数") from exc
