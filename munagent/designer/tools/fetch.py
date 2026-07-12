"""网页抓取与下载 — 下载落盘到场景包 references/."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field, HttpUrl

from munagent.designer.tools.base import ToolContext, ToolExecutionError, ToolResult, clip_summary
from munagent.designer.scenario import files as file_svc
from munagent.security.sanitize import sanitize_text

_MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
_CHARSET_META_RE = re.compile(
    r"<meta[^>]+charset\s*=\s*[\"']?([^\"'>\s;]+)",
    re.IGNORECASE,
)
_CHARSET_CT_RE = re.compile(r"charset=([^;\s]+)", re.IGNORECASE)
_CHARSET_ALIASES = {
    "gb2312": "gb18030",
    "gbk": "gb18030",
    "gb_2312": "gb18030",
    "utf8": "utf-8",
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = False
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "tr"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._chunks.append(data)

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "".join(self._chunks)).strip()


class FetchPageArgs(BaseModel):
    url: HttpUrl
    max_chars: int = Field(default=8000, ge=500, le=50000)


class DownloadFileArgs(BaseModel):
    url: HttpUrl
    path: str = Field(description="场景包内保存路径, 建议 references/raw/ 下")


def _normalize_charset(name: str) -> str:
    key = name.strip().strip("\"'").lower().replace("_", "")
    if key in _CHARSET_ALIASES:
        return _CHARSET_ALIASES[key]
    return name.strip().strip("\"'").lower()


def _detect_charset(content: bytes, content_type: str | None) -> str:
    """从 Content-Type 或 HTML meta 推断编码; 老中文站常见 GB2312/GBK."""
    if content_type:
        m = _CHARSET_CT_RE.search(content_type)
        if m:
            return _normalize_charset(m.group(1))
    head = content[:8192].decode("ascii", errors="ignore")
    m = _CHARSET_META_RE.search(head)
    if m:
        return _normalize_charset(m.group(1))
    try:
        content.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "gb18030"


def _decode_response_text(content: bytes, content_type: str | None) -> str:
    charset = _detect_charset(content, content_type)
    try:
        return content.decode(charset)
    except (UnicodeDecodeError, LookupError):
        return content.decode("utf-8", errors="replace")


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return parser.text()


def _safe_download_name(url: str, path: str) -> str:
    rel = path.strip().lstrip("/")
    if not rel:
        raise ToolExecutionError("path 不能为空")
    if ".." in PurePosixPath(rel).parts:
        raise ToolExecutionError(f"非法路径: {path}")
    if not rel.startswith("references/"):
        raise ToolExecutionError("download_file 仅允许写入 references/ 下")
    return rel


async def fetch_page(ctx: ToolContext, args: FetchPageArgs) -> ToolResult:
    del ctx
    url = str(args.url)
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "MUNagent-Designer/0.1"})
            resp.raise_for_status()
            raw = _decode_response_text(resp.content, resp.headers.get("content-type"))
    except httpx.HTTPError as exc:
        raise ToolExecutionError(sanitize_text(f"抓取失败: {exc}")) from exc
    text = _html_to_text(raw) if "<html" in raw.lower() else raw
    if len(text) > args.max_chars:
        text = text[: args.max_chars] + "\n…(已截断)"
    return ToolResult(
        ok=True,
        summary=clip_summary(f"抓取 {urlparse(url).netloc}, {len(text)} 字符"),
        data={"url": url, "text": text},
    )


async def download_file(ctx: ToolContext, args: DownloadFileArgs) -> ToolResult:
    rel = _safe_download_name(str(args.url), args.path)
    url = str(args.url)
    try:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "MUNagent-Designer/0.1"})
            resp.raise_for_status()
            data = resp.content
    except httpx.HTTPError as exc:
        raise ToolExecutionError(sanitize_text(f"下载失败: {exc}")) from exc
    if len(data) > _MAX_DOWNLOAD_BYTES:
        raise ToolExecutionError(f"文件过大: {len(data)} 字节, 上限 {_MAX_DOWNLOAD_BYTES}")
    try:
        file_svc.put_bytes(ctx.scenario_id, rel, data)
    except (PermissionError, ValueError) as exc:
        raise ToolExecutionError(str(exc)) from exc
    return ToolResult(
        ok=True,
        summary=clip_summary(f"下载到 {rel}, {len(data)} 字节"),
        data={"path": rel, "bytes": len(data), "url": url},
    )
