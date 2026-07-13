"""Wikipedia 检索 — MediaWiki API, 落盘 references/ 并返回摘要/正文与外链 PDF."""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from pydantic import BaseModel, Field

from munagent.designer.scenario import files as file_svc
from munagent.designer.tools.base import ToolContext, ToolExecutionError, ToolResult, clip_summary
from munagent.security.sanitize import sanitize_text

_USER_AGENT = "MUNagent-Designer/0.1 (design-agent; +https://github.com/local/munagent)"
_WIKI_API = "https://{lang}.wikipedia.org/w/api.php"
_PDF_URL_RE = re.compile(r"\.pdf(?:$|[?#])", re.I)
_PAGE_DELAY_S = 0.4


class SearchWikipediaArgs(BaseModel):
    query: str = Field(min_length=1, max_length=200, description="检索词, 如 Suez Crisis")
    lang: str = Field(default="en", min_length=2, max_length=12, description="维基语言代码, 默认 en")
    max_results: int = Field(default=3, ge=1, le=5, description="返回条目数上限")
    include_full_text: bool = Field(
        default=False,
        description="工具返回值是否含全文(截断); 全文仍会写入 references/",
    )
    max_text_chars: int = Field(default=12000, ge=500, le=50000, description="返回正文字段最大字符数")
    max_pdf_links: int = Field(default=5, ge=0, le=10, description="每条目最多返回几条外链 PDF")


def _wiki_url(lang: str, title: str) -> str:
    return f"https://{lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'), safe='/')}"


def _slugify(title: str, pageid: str) -> str:
    slug = re.sub(r"\s+", "_", title.strip())
    slug = re.sub(r"[^\w\-_.]", "", slug, flags=re.UNICODE)
    slug = slug.strip("._")[:80]
    return slug or f"page_{pageid}"


def _reference_path(lang: str, title: str, pageid: str) -> str:
    return f"references/wikipedia/{lang}_{_slugify(title, pageid)}.md"


def _render_reference_md(*, title: str, url: str, query: str, lang: str, body: str) -> str:
    return (
        f"# {title}\n\n"
        f"> 来源: {url}\n"
        f"> 检索词: {query} | 语言: {lang}\n"
        f"> 由 search_wikipedia 自动整理\n\n"
        f"{body.rstrip()}\n"
    )


def _looks_like_pdf(url: str) -> bool:
    if not url:
        return False
    path = urlparse(url).path.lower()
    return path.endswith(".pdf") or bool(_PDF_URL_RE.search(url))


def _strip_html_snippet(snippet: str) -> str:
    return re.sub(r"<[^>]+>", "", snippet).strip()


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n…(已截断)"


async def _wiki_get(client: httpx.AsyncClient, lang: str, **params: Any) -> dict[str, Any]:
    params.setdefault("format", "json")
    url = _WIKI_API.format(lang=lang)
    for attempt in range(4):
        resp = await client.get(url, params=params)
        if resp.status_code == 429:
            await asyncio.sleep(2**attempt)
            continue
        resp.raise_for_status()
        return resp.json()
    raise ToolExecutionError("Wikipedia API 请求过于频繁(429), 请稍后重试")


async def _search_titles(
    client: httpx.AsyncClient, query: str, *, lang: str, limit: int
) -> list[dict[str, str]]:
    body = await _wiki_get(
        client,
        lang,
        action="query",
        list="search",
        srsearch=query,
        srlimit=limit,
        srprop="snippet",
    )
    hits = body.get("query", {}).get("search", [])
    return [
        {
            "title": h.get("title", ""),
            "pageid": str(h.get("pageid", "")),
            "snippet": _strip_html_snippet(h.get("snippet", "")),
        }
        for h in hits
        if h.get("title")
    ]


async def _page_extract(
    client: httpx.AsyncClient, title: str, *, lang: str, sentences: int | None
) -> str:
    params: dict[str, Any] = {
        "action": "query",
        "prop": "extracts",
        "titles": title,
        "explaintext": 1,
        "exsectionformat": "plain",
    }
    if sentences is not None:
        params["exsentences"] = sentences
    body = await _wiki_get(client, lang, **params)
    pages = body.get("query", {}).get("pages", {})
    for page in pages.values():
        return (page.get("extract") or "").strip()
    return ""


async def _page_pdf_links(client: httpx.AsyncClient, title: str, *, lang: str) -> list[str]:
    body = await _wiki_get(client, lang, action="parse", page=title, prop="externallinks")
    links = body.get("parse", {}).get("externallinks") or []
    seen: set[str] = set()
    pdfs: list[str] = []
    for raw in links:
        u = str(raw).strip()
        if _looks_like_pdf(u) and u not in seen:
            seen.add(u)
            pdfs.append(u)
    return pdfs


async def search_wikipedia(ctx: ToolContext, args: SearchWikipediaArgs) -> ToolResult:
    lang = args.lang.strip().lower()
    saved_paths: list[str] = []
    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            hits = await _search_titles(client, args.query, lang=lang, limit=args.max_results)
            pages: list[dict[str, Any]] = []
            for hit in hits:
                title = hit["title"]
                pageid = hit["pageid"]
                url = _wiki_url(lang, title)
                await asyncio.sleep(_PAGE_DELAY_S)
                summary = await _page_extract(client, title, lang=lang, sentences=3)
                await asyncio.sleep(_PAGE_DELAY_S)
                full_text = await _page_extract(client, title, lang=lang, sentences=None)
                body_for_file = full_text or summary
                ref_path = _reference_path(lang, title, pageid)
                try:
                    file_svc.put_file(
                        ctx.scenario_id,
                        ref_path,
                        _render_reference_md(
                            title=title,
                            url=url,
                            query=args.query,
                            lang=lang,
                            body=body_for_file,
                        ),
                    )
                except (FileNotFoundError, ValueError, PermissionError) as exc:
                    raise ToolExecutionError(str(exc)) from exc
                saved_paths.append(ref_path)

                response_text = summary
                if args.include_full_text:
                    response_text = _truncate_text(body_for_file, args.max_text_chars)

                pdf_urls: list[str] = []
                if args.max_pdf_links > 0:
                    await asyncio.sleep(_PAGE_DELAY_S)
                    pdf_urls = (await _page_pdf_links(client, title, lang=lang))[: args.max_pdf_links]
                pages.append(
                    {
                        "title": title,
                        "pageid": pageid,
                        "url": url,
                        "reference_path": ref_path,
                        "snippet": hit["snippet"],
                        "summary": summary,
                        "text": response_text,
                        "pdf_urls": pdf_urls,
                    }
                )
    except httpx.HTTPError as exc:
        raise ToolExecutionError(sanitize_text(f"Wikipedia 请求失败: {exc}")) from exc

    pdf_n = sum(len(p["pdf_urls"]) for p in pages)
    top = pages[0]["title"] if pages else "(无)"
    return ToolResult(
        ok=True,
        summary=clip_summary(
            f"维基「{args.query}」{len(pages)} 条→{len(saved_paths)} 份 md, PDF 外链 {pdf_n}; 首条 {top}"
        ),
        data={
            "query": args.query,
            "lang": lang,
            "saved_paths": saved_paths,
            "pages": pages,
        },
    )
