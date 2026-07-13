#!/usr/bin/env python3
"""Internet Archive Advanced Search 探针 — 搜索并验证 PDF 直链.

用法:
  python scripts/probe_archive_search/probe_internet_archive.py
  python scripts/probe_archive_search/probe_internet_archive.py "Suez Crisis 1956" 3
"""

from __future__ import annotations

import sys
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

SEARCH_BASE = "https://archive.org/advancedsearch.php"
METADATA_BASE = "https://archive.org/metadata"


def _build_search_url(query: str, rows: int) -> str:
    q = f"{query} AND mediatype:texts AND format:Text PDF"
    return (
        f"{SEARCH_BASE}?q={quote(q)}"
        f"&fl[]=identifier,title"
        f"&rows={rows}"
        f"&output=json"
    )


def _pick_pdf_file(files: list[dict]) -> tuple[str | None, str | None]:
    """从 metadata files[] 选最佳 PDF 文件名. 返回 (filename, format_label)."""
    ranked: list[tuple[int, int, str, str]] = []
    for f in files:
        if not isinstance(f, dict):
            continue
        name = (f.get("name") or "").strip()
        fmt = (f.get("format") or "").strip()
        if not name.lower().endswith(".pdf") or "pdf" not in fmt.lower():
            continue
        priority = 3 if fmt == "Text PDF" else (2 if fmt == "PDF" else 1)
        try:
            size = int(f.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        ranked.append((priority, size, name, fmt))

    ranked.sort(key=lambda x: (x[0], x[1]), reverse=True)
    if not ranked:
        return None, None
    _, _, name, fmt = ranked[0]
    return name, fmt


def probe_internet_archive(query: str, max_results: int = 5) -> ProbeReport:
    search_url = _build_search_url(query, max_results)
    notes: list[str] = []
    candidates: list[PdfCandidate] = []
    verifications = []

    with make_client() as client:
        try:
            resp = client.get(search_url)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            return ProbeReport(
                source="internet_archive",
                query=query,
                search_url=search_url,
                candidates=[],
                verifications=[],
                error=str(exc),
            )

        docs = (payload.get("response") or {}).get("docs") or []
        notes.append(f"search numFound={(payload.get('response') or {}).get('numFound')}")

        for doc in docs:
            identifier = (doc.get("identifier") or "").strip()
            title = (doc.get("title") or identifier or "(no title)").strip()
            if not identifier:
                continue
            meta_url = f"{METADATA_BASE}/{identifier}"
            try:
                meta_resp = client.get(meta_url)
                meta_resp.raise_for_status()
                meta = meta_resp.json()
            except Exception as exc:  # noqa: BLE001
                notes.append(f"metadata failed for {identifier}: {exc}")
                continue

            filename, fmt = _pick_pdf_file(meta.get("files") or [])
            if not filename:
                notes.append(f"no PDF in metadata: {identifier}")
                continue

            pdf_url = f"https://archive.org/download/{identifier}/{quote(filename, safe='/')}"
            landing_url = f"https://archive.org/details/{identifier}"
            candidates.append(
                PdfCandidate(
                    source="internet_archive",
                    title=title,
                    pdf_url=pdf_url,
                    landing_url=landing_url,
                    extra={"identifier": identifier, "filename": filename, "format": fmt},
                )
            )

        verifications = [verify_pdf_url(client, c.pdf_url) for c in candidates]

    return ProbeReport(
        source="internet_archive",
        query=query,
        search_url=search_url,
        candidates=candidates,
        verifications=verifications,
        notes=notes,
    )


def main() -> int:
    query = sys.argv[1] if len(sys.argv) > 1 else "Suez Crisis 1956"
    max_results = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    report = probe_internet_archive(query, max_results=max_results)
    print_report(report)

    out_dir = _REPO / "out" / "probe_archive_search"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_q = query.replace(" ", "_")[:40]
    dump_json(report, str(out_dir / f"internet_archive_{safe_q}.json"))
    print(f"\n已写入 {out_dir / f'internet_archive_{safe_q}.json'}")

    return 0 if report.error is None and any(v.ok for v in report.verifications) else 1


if __name__ == "__main__":
    raise SystemExit(main())
