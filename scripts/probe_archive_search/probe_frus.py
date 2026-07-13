#!/usr/bin/env python3
"""FRUS OPDS 探针 — 搜索关键词并验证 PDF 直链.

用法:
  python scripts/probe_archive_search/probe_frus.py
  python scripts/probe_archive_search/probe_frus.py "cuba missile crisis" 3
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.probe_archive_search._common import (  # noqa: E402
    PdfCandidate,
    ProbeReport,
    dump_json,
    make_client,
    print_report,
    verify_pdf_url,
)

ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}
OPDS_ACQ = "http://opds-spec.org/acquisition"
SEARCH_BASE = "https://history.state.gov/api/v1/catalog/search"
CATALOG_ALL = "https://history.state.gov/api/v1/catalog/all"


def _local(tag: str) -> str:
    return f"{{{ATOM_NS['a']}}}{tag}"


def _entry_pdf_url(entry: ET.Element) -> str | None:
    for link in entry.findall("a:link", ATOM_NS):
        href = (link.get("href") or "").strip()
        rel = link.get("rel") or ""
        typ = (link.get("type") or "").lower()
        if rel != OPDS_ACQ or not href:
            continue
        if typ == "application/pdf" and href.lower().endswith(".pdf"):
            return href
    return None


def _title_matches(title: str, query: str) -> bool:
    title_l = title.lower()
    tokens = [t for t in query.lower().split() if len(t) >= 3]
    if not tokens:
        return query.lower() in title_l
    return all(tok in title_l for tok in tokens)


def parse_opds_entries(xml_text: str, *, max_results: int, query: str | None = None) -> list[PdfCandidate]:
    root = ET.fromstring(xml_text)
    out: list[PdfCandidate] = []
    for entry in root.findall("a:entry", ATOM_NS):
        title_el = entry.find("a:title", ATOM_NS)
        title = (title_el.text or "").strip() if title_el is not None else "(no title)"
        if query and not _title_matches(title, query):
            continue
        landing_el = entry.find("a:id", ATOM_NS)
        landing = (landing_el.text or "").strip() if landing_el is not None else None
        pdf_url = _entry_pdf_url(entry)
        if not pdf_url:
            continue
        out.append(
            PdfCandidate(
                source="frus",
                title=title,
                pdf_url=pdf_url,
                landing_url=landing,
            )
        )
        if len(out) >= max_results:
            break
    return out


def probe_frus(query: str, max_results: int = 5) -> ProbeReport:
    """FRUS 探针: 先尝试 OPDS search, 无 PDF 卷则回退 catalog/all 标题过滤."""
    search_url = f"{SEARCH_BASE}?q={quote(query)}"
    notes: list[str] = []
    with make_client() as client:
        try:
            search_resp = client.get(search_url)
            search_resp.raise_for_status()
            search_entries = len(ET.fromstring(search_resp.text).findall("a:entry", ATOM_NS))
            notes.append(f"OPDS search entries: {search_entries}")
            candidates = parse_opds_entries(search_resp.text, max_results=max_results, query=None)
        except Exception as exc:  # noqa: BLE001
            return ProbeReport(
                source="frus",
                query=query,
                search_url=search_url,
                candidates=[],
                verifications=[],
                error=str(exc),
            )

        if not candidates:
            notes.append("OPDS search 不返回卷宗 PDF; 回退 GET /api/v1/catalog/all 并按标题过滤")
            search_url = CATALOG_ALL
            try:
                all_resp = client.get(CATALOG_ALL)
                all_resp.raise_for_status()
                all_root = ET.fromstring(all_resp.text)
                total = len(all_root.findall("a:entry", ATOM_NS))
                notes.append(f"catalog/all entries: {total}")
                candidates = parse_opds_entries(all_resp.text, max_results=max_results, query=query)
                if not candidates:
                    notes.append("标题过滤后无带 application/pdf 链接的卷宗(多数卷仅 epub/mobi)")
            except Exception as exc:  # noqa: BLE001
                return ProbeReport(
                    source="frus",
                    query=query,
                    search_url=search_url,
                    candidates=[],
                    verifications=[],
                    notes=notes,
                    error=str(exc),
                )

        verifications = [verify_pdf_url(client, c.pdf_url) for c in candidates]

    return ProbeReport(
        source="frus",
        query=query,
        search_url=search_url,
        candidates=candidates,
        verifications=verifications,
        notes=notes,
    )


def main() -> int:
    query = sys.argv[1] if len(sys.argv) > 1 else "Suez Crisis 1956"
    max_results = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    report = probe_frus(query, max_results=max_results)
    print_report(report)

    out_dir = _REPO / "out" / "probe_archive_search"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_q = query.replace(" ", "_")[:40]
    dump_json(report, str(out_dir / f"frus_{safe_q}.json"))
    print(f"\n已写入 {out_dir / f'frus_{safe_q}.json'}")

    return 0 if report.error is None and any(v.ok for v in report.verifications) else 1


if __name__ == "__main__":
    raise SystemExit(main())
