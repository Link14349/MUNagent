"""MinerU PDF→Markdown — 见 docs/tools/agent-api-pdf-to-markdown-guide.md."""

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


class MineruConvertArgs(BaseModel):
    path: str = Field(description="场景包内 PDF 路径")
    output_path: str | None = Field(default=None, description="输出 md 路径, 默认 references/<stem>.md")


def _mineru_base(config_url: str) -> str:
    base = config_url.rstrip("/")
    if not base:
        raise ToolExecutionError("未配置 tools.mineru.base_url")
    return base


async def mineru_convert(ctx: ToolContext, args: MineruConvertArgs) -> ToolResult:
    base = _mineru_base(ctx.config.tools.mineru.base_url)
    rel = args.path.strip().lstrip("/")
    if not rel.lower().endswith(".pdf"):
        raise ToolExecutionError("mineru_convert 仅支持 PDF")
    try:
        pdf_data = file_svc.read_bytes(ctx.scenario_id, rel)
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
        md = await _convert_pdf(base, Path(rel).name, pdf_data)
    except httpx.HTTPError as exc:
        raise ToolExecutionError(sanitize_text(f"MinerU 请求失败: {exc}")) from exc
    except TimeoutError as exc:
        raise ToolExecutionError("MinerU 转换超时") from exc

    file_svc.put_file(ctx.scenario_id, out_rel, md)
    return ToolResult(
        ok=True,
        summary=clip_summary(f"转换 {rel} → {out_rel}, {len(md)} 字符"),
        data={"source": rel, "output": out_rel, "chars": len(md)},
    )


async def _convert_pdf(base: str, filename: str, pdf_data: bytes) -> str:
    form = {
        "backend": "pipeline",
        "parse_method": "auto",
        "lang_list": "ch",
        "return_md": "true",
        "return_middle_json": "false",
        "return_images": "false",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        files = {"files": (filename, pdf_data, "application/pdf")}
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
