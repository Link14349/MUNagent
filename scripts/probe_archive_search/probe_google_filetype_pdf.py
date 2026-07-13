#!/usr/bin/env python3
"""Google filetype:pdf 探针 — 经配置的搜索 API 找 PDF 直链并 HEAD 验证.

用法:
  python scripts/probe_archive_search/probe_google_filetype_pdf.py
  python scripts/probe_archive_search/probe_google_filetype_pdf.py "Suez Crisis 1956 report" un.org 5

依赖 ~/.munagent/config.yaml 的 tools.search (推荐 provider=serper).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from munagent.config import load_config  # noqa: E402
from scripts.probe_archive_search._common import (  # noqa: E402
    PdfCandidate,
    ProbeReport,
    dump_json,
    make_client,
    print_report,
    verify_pdf_url,
)

_PDF_URL_RE = re.compile(r"\.pdf(?:$|[?#])", re.I)


def build_query(topic: str, site: str | None) -> str:
    q = topic.strip()
    if "filetype:pdf" not in q.lower():
        q = f"{q} filetype:pdf"
    if site and f"site:{site}" not in q.lower():
        q = f"{q} site:{site}"
    return q


def _looks_like_pdf_url(url: str) -> bool:
    if not url:
        return False
    path = urlparse(url).path.lower()
    return path.endswith(".pdf") or bool(_PDF_URL_RE.search(url))


def search_google_pdf(query: str, *, provider: str, api_key: str, max_results: int) -> list[dict]:
    if provider == "serper":
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json={"q": query, "num": max_results},
            )
            resp.raise_for_status()
            organic = resp.json().get("organic", [])
        return [
            {"title": r.get("title", ""), "url": r.get("link", ""), "snippet": r.get("snippet", "")}
            for r in organic[:max_results]
        ]
    if provider == "tavily":
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                "https://api.tavily.com/search",
                json={"api_key": api_key, "query": query, "max_results": max_results},
            )
            resp.raise_for_status()
            organic = resp.json().get("results", [])
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
            for r in organic[:max_results]
        ]
    if provider == "bocha":
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
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
    raise RuntimeError(f"未知 provider: {provider}")


def probe_google_filetype_pdf(
    topic: str,
    *,
    site: str | None = None,
    max_results: int = 5,
    provider: str,
    api_key: str,
) -> ProbeReport:
    query = build_query(topic, site)
    notes: list[str] = []
    try:
        hits = search_google_pdf(query, provider=provider, api_key=api_key, max_results=max_results)
    except Exception as exc:  # noqa: BLE001
        return ProbeReport(
            source="google_filetype_pdf",
            query=query,
            search_url=f"provider={provider}",
            candidates=[],
            verifications=[],
            error=str(exc),
        )

    notes.append(f"search hits: {len(hits)}")
    pdf_hits = [h for h in hits if _looks_like_pdf_url(h.get("url", ""))]
    notes.append(f"url looks pdf: {len(pdf_hits)}/{len(hits)}")
    non_pdf = [h.get("url") for h in hits if h not in pdf_hits]
    if non_pdf:
        notes.append(f"non-pdf urls dropped: {non_pdf[:3]}")

    candidates = [
        PdfCandidate(
            source="google_filetype_pdf",
            title=h.get("title") or h.get("url", ""),
            pdf_url=h["url"],
            landing_url=h["url"],
            extra={"snippet": h.get("snippet", "")},
        )
        for h in pdf_hits
    ]

    with make_client() as client:
        verifications = [verify_pdf_url(client, c.pdf_url) for c in candidates]

    return ProbeReport(
        source="google_filetype_pdf",
        query=query,
        search_url=f"provider={provider}",
        candidates=candidates,
        verifications=verifications,
        notes=notes,
    )


def main() -> int:
    topic = sys.argv[1] if len(sys.argv) > 1 else "Suez Crisis 1956 report"
    site = sys.argv[2] if len(sys.argv) > 2 else "un.org"
    max_results = int(sys.argv[3]) if len(sys.argv) > 3 else 5

    config = load_config()
    search = config.tools.search
    if not search.api_key:
        print("ERROR: 未配置 tools.search.api_key")
        return 1

    cases = [
        (topic, site),
        ("cuba missile crisis declassified telegram", "history.state.gov"),
    ]
    out_dir = _REPO / "out" / "probe_archive_search"
    out_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    exit_code = 0

    for t, s in cases:
        report = probe_google_filetype_pdf(
            t,
            site=s,
            max_results=max_results,
            provider=search.provider,
            api_key=search.api_key,
        )
        print_report(report)
        reports.append(report.to_dict())
        safe = re.sub(r"[^\w]+", "_", t)[:30]
        dump_json(report, str(out_dir / f"google_filetype_{safe}.json"))
        if report.error or not any(v.ok for v in report.verifications):
            exit_code = 1

    summary = out_dir / "google_filetype_summary.json"
    summary.write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n汇总 → {summary}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
