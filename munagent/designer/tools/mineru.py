"""MinerU 文档→Markdown — 见 docs/tools/agent-api-pdf-to-markdown-guide.md."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from pydantic import BaseModel, Field

from munagent.designer.tools.base import ToolContext, ToolExecutionError, ToolResult, clip_summary
from munagent.designer.scenario import files as file_svc
from munagent.security.sanitize import sanitize_text

_POLL_INTERVAL_S = 3.0
_ASYNC_TIMEOUT_S = 7200.0

_SUPPORTED_SUFFIXES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".epub": "application/epub+zip",
    ".mobi": "application/x-mobipocket-ebook",
}


class MineruConvertArgs(BaseModel):
    path: str = Field(description="场景包内文档路径(pdf/epub/mobi)")
    output_path: str | None = Field(default=None, description="输出 md 路径, 默认 references/<stem>.md")


def _mineru_base(config_url: str) -> str:
    base = config_url.rstrip("/")
    if not base:
        raise ToolExecutionError("未配置 tools.mineru.base_url")
    return base


def _mime_for_path(path: str) -> str:
    suffix = Path(path).suffix.lower()
    mime = _SUPPORTED_SUFFIXES.get(suffix)
    if mime is None:
        supported = ", ".join(sorted(_SUPPORTED_SUFFIXES))
        raise ToolExecutionError(f"mineru_convert 仅支持 {supported}")
    return mime


async def mineru_convert(ctx: ToolContext, args: MineruConvertArgs) -> ToolResult:
    base = _mineru_base(ctx.config.tools.mineru.base_url)
    rel = args.path.strip().lstrip("/")
    mime = _mime_for_path(rel)
    try:
        doc_data = file_svc.read_bytes(ctx.scenario_id, rel)
    except FileNotFoundError as exc:
        raise ToolExecutionError(str(exc)) from exc
    except ValueError as exc:
        raise ToolExecutionError(str(exc)) from exc
    except PermissionError as exc:
        raise ToolExecutionError(str(exc)) from exc

    stem = Path(rel).stem
    out_rel = (args.output_path or f"references/{stem}.md").strip().lstrip("/")
    if ".." in Path(out_rel).parts:
        raise ToolExecutionError(f"非法输出路径: {out_rel}")

    try:
        md = await _convert_document(base, Path(rel).name, doc_data, mime=mime)
    except httpx.HTTPError as exc:
        raise ToolExecutionError(sanitize_text(f"MinerU 请求失败: {exc}")) from exc
    except TimeoutError as exc:
        raise ToolExecutionError("MinerU 转换超时") from exc

    file_svc.put_file(ctx.scenario_id, out_rel, md)
    return ToolResult(
        ok=True,
        summary=clip_summary(f"转换 {rel} → {out_rel}, {len(md)} 字符"),
        data={"source": rel, "output": out_rel, "chars": len(md), "format": Path(rel).suffix.lower().lstrip(".")},
    )


async def _convert_document(base: str, filename: str, data: bytes, *, mime: str) -> str:
    form = {
        "backend": "pipeline",
        "parse_method": "auto",
        "lang_list": "ch",
        "return_md": "true",
        "return_middle_json": "false",
        "return_images": "false",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        files = {"files": (filename, data, mime)}
        resp = await client.post(f"{base}/tasks", files=files, data=form)
        resp.raise_for_status()
        body = resp.json()
        if body.get("status") == "completed":
            return _extract_md(body)
        task_id = body["task_id"]
        return await _poll_task(client, base, task_id)


async def _poll_task(client: httpx.AsyncClient, base: str, task_id: str) -> str:
    status_url = f"{base}/tasks/{task_id}"
    result_url = f"{base}/tasks/{task_id}/result"
    elapsed = 0.0
    while elapsed < _ASYNC_TIMEOUT_S:
        s = await client.get(status_url, timeout=30.0)
        s.raise_for_status()
        status = s.json().get("status")
        if status == "completed":
            r = await client.get(result_url, timeout=120.0)
            r.raise_for_status()
            return _extract_md(r.json())
        if status == "failed":
            raise ToolExecutionError(sanitize_text(s.json().get("error", "MinerU 任务失败")))
        await asyncio.sleep(_POLL_INTERVAL_S)
        elapsed += _POLL_INTERVAL_S
    raise TimeoutError()


def _extract_md(body: dict) -> str:
    results = body.get("results", {})
    if not results:
        raise ToolExecutionError("MinerU 响应无 results")
    first = next(iter(results.values()))
    md = first.get("md_content", "")
    if not md:
        raise ToolExecutionError("MinerU 响应 md_content 为空")
    return md
