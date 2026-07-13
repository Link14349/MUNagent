"""Google 风格 PDF 直链检索 — 查询自动追加 filetype:pdf, 复用 tools.search."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from munagent.designer.tools.base import ToolContext, ToolExecutionError, ToolResult, clip_summary
from munagent.designer.tools.search import dispatch_web_search
from munagent.security.sanitize import sanitize_text

_PDF_URL_RE = re.compile(r"\.pdf(?:$|[?#])", re.I)


class SearchWebPdfArgs(BaseModel):
    query: str = Field(min_length=1, max_length=500, description="主题关键词; 工具会自动追加 filetype:pdf")
    max_results: int = Field(default=5, ge=1, le=10)
    site: str | None = Field(
        default=None,
        description="可选站点限制, 如 un.org; 默认不限站点",
    )


def build_pdf_query(query: str, site: str | None) -> str:
    q = query.strip()
    if "filetype:pdf" not in q.lower():
        q = f"{q} filetype:pdf"
    if site:
        token = f"site:{site.strip()}"
        if token.lower() not in q.lower():
            q = f"{q} {token}"
    return q


def _looks_like_pdf_url(url: str) -> bool:
    if not url:
        return False
    path = urlparse(url).path.lower()
    return path.endswith(".pdf") or bool(_PDF_URL_RE.search(url))


async def search_web_pdf(ctx: ToolContext, args: SearchWebPdfArgs) -> ToolResult:
    cfg = ctx.config.tools.search
    if not cfg.api_key:
        raise ToolExecutionError("未配置 tools.search.api_key")
    search_query = build_pdf_query(args.query, args.site)
    try:
        hits = await dispatch_web_search(cfg.provider, cfg.api_key, search_query, args.max_results)
    except httpx.HTTPError as exc:
        raise ToolExecutionError(sanitize_text(f"搜索请求失败: {exc}")) from exc

    results: list[dict[str, Any]] = []
    for item in hits:
        url = item.get("url", "")
        if not _looks_like_pdf_url(url):
            continue
        results.append(
            {
                "title": item.get("title", ""),
                "pdf_url": url,
                "snippet": item.get("snippet", ""),
            }
        )

    return ToolResult(
        ok=True,
        summary=clip_summary(
            f"PDF 搜索「{args.query}」得 {len(results)} 条直链"
            + (f" (site:{args.site})" if args.site else "")
        ),
        data={
            "query": args.query,
            "search_query": search_query,
            "results": results,
            "raw_hit_count": len(hits),
        },
    )
