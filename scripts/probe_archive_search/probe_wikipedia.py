#!/usr/bin/env python3
"""Wikipedia 检索探针 — API 搜条目、抽外链/参考文献 PDF 并 HEAD 验证.

用法:
  python scripts/probe_archive_search/probe_wikipedia.py
  python scripts/probe_archive_search/probe_wikipedia.py "Suez Crisis" en 3
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import time

import httpx

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.probe_archive_search._common import (  # noqa: E402
    PdfCandidate,
    PdfVerifyResult,
    make_client,
    verify_pdf_url,
)

_PDF_URL_RE = re.compile(r"\.pdf(?:$|[?#])", re.I)
_WIKI_API = "https://{lang}.wikipedia.org/w/api.php"
_USER_AGENT = "MUNagent-wiki-probe/0.1 (research; contact local)"


def _wiki_api(lang: str, **params: Any) -> dict:
    params.setdefault("format", "json")
    url = _WIKI_API.format(lang=lang)
    with httpx.Client(timeout=30.0, headers={"User-Agent": _USER_AGENT}) as client:
        for attempt in range(4):
            resp = client.get(url, params=params)
            if resp.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()
    raise RuntimeError("unreachable")


def search_titles(query: str, *, lang: str = "en", limit: int = 5) -> list[dict[str, str]]:
    """MediaWiki action=query list=search."""
    body = _wiki_api(
        lang,
        action="query",
        list="search",
        srsearch=query,
        srlimit=limit,
        srprop="snippet|titlesnippet",
    )
    hits = body.get("query", {}).get("search", [])
    return [
        {
            "title": h.get("title", ""),
            "pageid": str(h.get("pageid", "")),
            "snippet": re.sub(r"<[^>]+>", "", h.get("snippet", "")),
        }
        for h in hits
    ]


def page_externallinks(title: str, *, lang: str = "en") -> list[str]:
    body = _wiki_api(lang, action="parse", page=title, prop="externallinks")
    links = body.get("parse", {}).get("externallinks") or []
    return [str(u) for u in links if u]


def page_references(title: str, *, lang: str = "en") -> list[str]:
    """从 wikitext 引用模板里粗抽 URL(含 archive.org / pdf). 失败时返回空."""
    try:
        body = _wiki_api(lang, action="query", prop="revisions", titles=title, rvslots="main", rvprop="content")
    except httpx.HTTPError:
        return []
    pages = body.get("query", {}).get("pages", {})
    wikitext = ""
    for page in pages.values():
        slots = page.get("revisions", [{}])[0].get("slots", {})
        wikitext = slots.get("main", {}).get("*", "") or ""
        break
    urls = re.findall(r"https?://[^\s\]|<>\"']+", wikitext)
    return [unquote(u.rstrip(".,;)")) for u in urls]


def page_summary(title: str, *, lang: str = "en", sentences: int = 3) -> str:
    body = _wiki_api(
        lang,
        action="query",
        prop="extracts",
        titles=title,
        explaintext=1,
        exsentences=sentences,
    )
    pages = body.get("query", {}).get("pages", {})
    for page in pages.values():
        return (page.get("extract") or "").strip()
    return ""


def _looks_like_pdf(url: str) -> bool:
    if not url:
        return False
    path = urlparse(url).path.lower()
    return path.endswith(".pdf") or bool(_PDF_URL_RE.search(url))


def collect_pdf_urls(title: str, *, lang: str = "en") -> tuple[list[str], dict[str, list[str]]]:
    externals = page_externallinks(title, lang=lang)
    refs = page_references(title, lang=lang)
    buckets = {"externallinks": externals, "references": refs}
    seen: set[str] = set()
    pdfs: list[str] = []
    for source, urls in buckets.items():
        for u in urls:
            if _looks_like_pdf(u) and u not in seen:
                seen.add(u)
                pdfs.append(u)
    return pdfs, buckets


def probe_wikipedia(query: str, *, lang: str = "en", top_pages: int = 3, max_pdf: int = 8) -> dict:
    hits = search_titles(query, lang=lang, limit=top_pages)
    pages_out: list[dict] = []
    all_pdfs: list[PdfCandidate] = []

    for hit in hits:
        title = hit["title"]
        time.sleep(0.5)
        pdf_urls, buckets = collect_pdf_urls(title, lang=lang)
        summary = page_summary(title, lang=lang)
        pages_out.append(
            {
                "title": title,
                "pageid": hit["pageid"],
                "wiki_url": f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}",
                "snippet": hit["snippet"],
                "summary": summary,
                "externallinks_count": len(buckets["externallinks"]),
                "reference_urls_count": len(buckets["references"]),
                "pdf_urls": pdf_urls[:max_pdf],
                "sample_externallinks": buckets["externallinks"][:8],
            }
        )
        for u in pdf_urls[:max_pdf]:
            all_pdfs.append(
                PdfCandidate(
                    source="wikipedia",
                    title=f"{title} → PDF",
                    pdf_url=u,
                    landing_url=pages_out[-1]["wiki_url"],
                    extra={"wiki_title": title},
                )
            )

    verifications: list[PdfVerifyResult] = []
    with make_client() as client:
        for c in all_pdfs:
            verifications.append(verify_pdf_url(client, c.pdf_url))

    ok_n = sum(1 for v in verifications if v.ok)
    return {
        "query": query,
        "lang": lang,
        "api": _WIKI_API.format(lang=lang),
        "pages": pages_out,
        "pdf_candidates": [
            {"title": c.title, "pdf_url": c.pdf_url, "wiki": c.landing_url} for c in all_pdfs
        ],
        "verifications": [
            {
                "pdf_url": v.pdf_url,
                "ok": v.ok,
                "status_code": v.status_code,
                "content_type": v.content_type,
                "error": v.error,
            }
            for v in verifications
        ],
        "verified_ok_count": ok_n,
        "pdf_total": len(all_pdfs),
    }


def main() -> int:
    query = sys.argv[1] if len(sys.argv) > 1 else "Suez Crisis"
    lang = sys.argv[2] if len(sys.argv) > 2 else "en"
    top_pages = int(sys.argv[3]) if len(sys.argv) > 3 else 3

    cases = [query]
    if query.lower() == "suez crisis":
        cases.append("Cuban Missile Crisis")

    out_dir = _REPO / "out" / "probe_archive_search"
    out_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    exit_code = 0

    for q in cases:
        print(f"\n{'=' * 60}")
        print(f"[wikipedia] lang={lang} query={q!r}")
        report = probe_wikipedia(q, lang=lang, top_pages=top_pages)
        reports.append(report)
        print(f"top pages: {len(report['pages'])}")
        for p in report["pages"]:
            print(f"  • {p['title']} — extlinks={p['externallinks_count']} refs={p['reference_urls_count']} pdfs={len(p['pdf_urls'])}")
            if p["summary"]:
                print(f"    summary: {p['summary'][:160]}…")
            for u in p["pdf_urls"][:5]:
                print(f"    pdf: {u}")
        print(f"verified PDF: {report['verified_ok_count']}/{report['pdf_total']}")
        for v in report["verifications"]:
            mark = "OK" if v["ok"] else "FAIL"
            print(f"  [{mark}] {v['pdf_url']} — status={v['status_code']} type={v['content_type']}")
        safe = re.sub(r"[^\w]+", "_", q)[:30]
        path = out_dir / f"wikipedia_{lang}_{safe}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"→ {path}")
        if report["pdf_total"] == 0:
            exit_code = 1

    summary = out_dir / "wikipedia_summary.json"
    summary.write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n汇总 → {summary}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
