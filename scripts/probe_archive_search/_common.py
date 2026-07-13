"""探针脚本共享工具 — 验证 PDF 直链是否可 GET."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

DEFAULT_TIMEOUT = 60.0
USER_AGENT = "MUNagent-archive-probe/0.1 (+https://github.com/local/munagent)"


@dataclass
class PdfCandidate:
    source: str
    title: str
    pdf_url: str
    landing_url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class PdfVerifyResult:
    pdf_url: str
    ok: bool
    status_code: int | None = None
    content_type: str | None = None
    content_length: int | None = None
    final_url: str | None = None
    error: str | None = None


@dataclass
class ProbeReport:
    source: str
    query: str
    search_url: str
    candidates: list[PdfCandidate]
    verifications: list[PdfVerifyResult]
    notes: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "query": self.query,
            "search_url": self.search_url,
            "candidates": [asdict(c) for c in self.candidates],
            "verifications": [asdict(v) for v in self.verifications],
            "notes": self.notes,
            "error": self.error,
            "verified_ok_count": sum(1 for v in self.verifications if v.ok),
        }


def make_client() -> httpx.Client:
    return httpx.Client(
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


def verify_pdf_url(client: httpx.Client, url: str) -> PdfVerifyResult:
    """HEAD 优先; 不支持时回退 Range GET 1 字节."""
    try:
        resp = client.head(url)
        if resp.status_code in {405, 501} or not resp.headers.get("content-type"):
            resp = client.get(url, headers={"Range": "bytes=0-0"})
    except httpx.HTTPError as exc:
        return PdfVerifyResult(pdf_url=url, ok=False, error=str(exc))

    ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
    clen_raw = resp.headers.get("content-length")
    clen = int(clen_raw) if clen_raw and clen_raw.isdigit() else None
    ok = resp.status_code in {200, 206} and (
        "pdf" in ctype or url.lower().rstrip("/").endswith(".pdf")
    )
    return PdfVerifyResult(
        pdf_url=url,
        ok=ok,
        status_code=resp.status_code,
        content_type=ctype or None,
        content_length=clen,
        final_url=str(resp.url),
        error=None if ok else f"status={resp.status_code}, content-type={ctype or '(none)'}",
    )


def print_report(report: ProbeReport) -> None:
    print(f"\n{'=' * 60}")
    print(f"[{report.source}] query={report.query!r}")
    print(f"search: {report.search_url}")
    if report.error:
        print(f"ERROR: {report.error}")
    print(f"candidates: {len(report.candidates)}")
    for i, c in enumerate(report.candidates, 1):
        print(f"  {i}. {c.title}")
        print(f"     pdf: {c.pdf_url}")
        if c.landing_url:
            print(f"     page: {c.landing_url}")
    ok_n = sum(1 for v in report.verifications if v.ok)
    print(f"verified PDF: {ok_n}/{len(report.verifications)}")
    for v in report.verifications:
        mark = "OK" if v.ok else "FAIL"
        detail = f"status={v.status_code} type={v.content_type}"
        if v.content_length is not None:
            detail += f" len={v.content_length}"
        if v.final_url and v.final_url != v.pdf_url:
            detail += f" final={v.final_url}"
        if v.error:
            detail += f" err={v.error}"
        print(f"  [{mark}] {v.pdf_url} — {detail}")
    for note in report.notes:
        print(f"  note: {note}")


def dump_json(report: ProbeReport, path: str | None = None) -> str:
    text = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    if path:
        from pathlib import Path

        Path(path).write_text(text + "\n", encoding="utf-8")
    return text
