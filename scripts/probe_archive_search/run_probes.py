#!/usr/bin/env python3
"""运行 FRUS + Internet Archive 探针并汇总."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import json

from scripts.probe_archive_search._common import print_report  # noqa: E402
from scripts.probe_archive_search.probe_frus import probe_frus  # noqa: E402
from scripts.probe_archive_search.probe_internet_archive import probe_internet_archive  # noqa: E402

QUERIES = [
    "Suez Crisis 1956",
    "cuba missile crisis",
]


def main() -> int:
    max_results = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    reports = []
    exit_code = 0

    for query in QUERIES:
        for probe_fn in (probe_frus, probe_internet_archive):
            report = probe_fn(query, max_results=max_results)
            print_report(report)
            reports.append(report.to_dict())
            if report.error or not any(v.ok for v in report.verifications):
                exit_code = 1

    out_dir = _REPO / "out" / "probe_archive_search"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "summary.json"
    summary_path.write_text(
        json.dumps({"queries": QUERIES, "reports": reports}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\n汇总 → {summary_path}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
