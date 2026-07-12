"""联网检索工具 — 配置见 AppConfig.tools.search."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, Field

from munagent.designer.tools.base import ToolContext, ToolExecutionError, ToolResult, clip_summary
from munagent.security.sanitize import sanitize_text


class WebSearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    max_results: int = Field(default=5, ge=1, le=10)


async def web_search(ctx: ToolContext, args: WebSearchArgs) -> ToolResult:
    cfg = ctx.config.tools.search
    if not cfg.api_key:
        raise ToolExecutionError("未配置 tools.search.api_key")
    try:
        items = await _dispatch_search(cfg.provider, cfg.api_key, args.query, args.max_results)
    except httpx.HTTPError as exc:
        raise ToolExecutionError(sanitize_text(f"搜索请求失败: {exc}")) from exc
    return ToolResult(
        ok=True,
        summary=clip_summary(f"搜索「{args.query}」得 {len(items)} 条"),
        data={"query": args.query, "results": items},
    )


async def _dispatch_search(
    provider: str, api_key: str, query: str, max_results: int
) -> list[dict[str, Any]]:
    if provider == "tavily":
        return await _search_tavily(api_key, query, max_results)
    if provider == "serper":
        return await _search_serper(api_key, query, max_results)
    if provider == "bocha":
        return await _search_bocha(api_key, query, max_results)
    raise ToolExecutionError(f"未知搜索 provider: {provider}")


async def _search_tavily(api_key: str, query: str, max_results: int) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": query, "max_results": max_results},
        )
        resp.raise_for_status()
        body = resp.json()
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("content", ""),
        }
        for r in body.get("results", [])
    ]


async def _search_serper(api_key: str, query: str, max_results: int) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": max_results},
        )
        resp.raise_for_status()
        body = resp.json()
    organic = body.get("organic", [])[:max_results]
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("link", ""),
            "snippet": r.get("snippet", ""),
        }
        for r in organic
    ]


async def _search_bocha(api_key: str, query: str, max_results: int) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.bochaai.com/v1/web-search",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"query": query, "count": max_results},
        )
        resp.raise_for_status()
        body = resp.json()
    raw = body.get("data", {}).get("webPages", {}).get("value", [])
    if not raw and isinstance(body.get("results"), list):
        raw = body["results"]
    return [
        {
            "title": r.get("name", r.get("title", "")),
            "url": r.get("url", ""),
            "snippet": r.get("snippet", r.get("summary", "")),
        }
        for r in raw[:max_results]
    ]
