#!/usr/bin/env python3
"""探针 MinerU 网关对 epub/mobi 的转换能力."""

from __future__ import annotations

import json
import sys
import time
import zipfile
from io import BytesIO
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "out" / "probe_epub"
SERVER = "http://36.139.151.129:8282"


def make_tiny_epub(path: Path) -> None:
    """生成最小合法 EPUB(含 Suez Crisis 样例文本)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content_xhtml = """<?xml version='1.0' encoding='utf-8'?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Suez Crisis Sample</title></head>
<body>
<h1>Suez Crisis, 1956</h1>
<p>This is a probe document for MinerU epub conversion.</p>
<p>On 26 July 1956, President Nasser nationalized the Suez Canal Company.</p>
</body>
</html>"""
    content_opf = """<?xml version='1.0' encoding='utf-8'?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Suez Crisis Sample</dc:title>
    <dc:language>en</dc:language>
    <dc:identifier id="uid">munagent-probe-epub-001</dc:identifier>
  </metadata>
  <manifest>
    <item id="content" href="content.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="content"/>
  </spine>
</package>"""
    container = """<?xml version='1.0' encoding='UTF-8'?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/content.opf", content_opf)
        zf.writestr("OEBPS/content.xhtml", content_xhtml)


def convert_file(path: Path, *, mime: str, use_async: bool = False, timeout_s: float = 7200.0) -> dict:
    form = {
        "backend": "pipeline",
        "parse_method": "auto",
        "lang_list": "ch",
        "return_md": "true",
        "return_middle_json": "false",
        "return_images": "false",
    }
    endpoint = "/tasks" if use_async else "/file_parse"
    with path.open("rb") as f:
        files = {"files": (path.name, f, mime)}
        with httpx.Client(timeout=timeout_s) as client:
            t0 = time.perf_counter()
            resp = client.post(f"{SERVER}{endpoint}", files=files, data=form)
            body: dict = {}
            try:
                body = resp.json()
            except Exception:
                body = {"raw": resp.text[:500]}

            if use_async and resp.status_code in {200, 202} and body.get("status") != "completed":
                task_id = body.get("task_id")
                if not task_id:
                    elapsed = time.perf_counter() - t0
                    return {
                        "file": str(path),
                        "mime": mime,
                        "mode": "async",
                        "status_code": resp.status_code,
                        "elapsed_s": round(elapsed, 2),
                        "body": body,
                    }
                status_url = f"{SERVER}/tasks/{task_id}"
                result_url = f"{SERVER}/tasks/{task_id}/result"
                while time.perf_counter() - t0 < timeout_s:
                    s = client.get(status_url, timeout=30.0).json()
                    st = s.get("status")
                    if st == "completed":
                        resp = client.get(result_url, timeout=120.0)
                        body = resp.json()
                        break
                    if st == "failed":
                        body = s
                        break
                    time.sleep(3)
            elapsed = time.perf_counter() - t0
    return {
        "file": str(path),
        "mime": mime,
        "mode": "async" if use_async else "sync",
        "status_code": resp.status_code,
        "elapsed_s": round(elapsed, 2),
        "body": body,
    }


def extract_md(body: dict) -> tuple[str, int]:
    results = body.get("results") or {}
    for doc in results.values():
        md = doc.get("md_content") or ""
        if md:
            return md, len(md)
    return "", 0


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    epub_path = OUT / "suez_sample.epub"
    make_tiny_epub(epub_path)
    print(f"已生成 {epub_path} ({epub_path.stat().st_size} bytes)")

    with httpx.Client(timeout=15.0) as client:
        health = client.get(f"{SERVER}/health").json()
    print(f"health: {health.get('status')} version={health.get('version')}")

    reports: list[dict] = []

    print("\n=== EPUB file_parse ===")
    epub_report = convert_file(epub_path, mime="application/epub+zip")
    reports.append(epub_report)
    print(json.dumps({k: v for k, v in epub_report.items() if k != "body"}, ensure_ascii=False, indent=2))
    md, n = extract_md(epub_report["body"])
    print(f"md chars: {n}")
    if md:
        print("md preview:", md[:400].replace("\n", " "))
        (OUT / "suez_sample.epub.md").write_text(md, encoding="utf-8")

    mobi_candidates = [
        OUT / "sample.mobi",
        REPO / "out" / "probe_epub" / "frus1955-57v16.mobi",
    ]
    mobi_path = next((p for p in mobi_candidates if p.is_file() and p.stat().st_size > 1000), None)
    if len(sys.argv) > 1:
        mobi_path = Path(sys.argv[1])

    if mobi_path:
        print(f"\n=== MOBI file_parse ({mobi_path.name}) ===")
        mobi_report = convert_file(mobi_path, mime="application/x-mobipocket-ebook")
        reports.append(mobi_report)
        print(json.dumps({k: v for k, v in mobi_report.items() if k != "body"}, ensure_ascii=False, indent=2))
        md2, n2 = extract_md(mobi_report["body"])
        print(f"md chars: {n2}")
        if md2:
            print("md preview:", md2[:400].replace("\n", " "))
            (OUT / f"{mobi_path.stem}.md").write_text(md2, encoding="utf-8")
    else:
        print("\n[跳过 MOBI] 无本地 mobi 样例; 可传路径: python scripts/probe_mineru_ebook.py /path/to/file.mobi")
        # 尝试下载 FRUS mobi(小概率成功)
        frus_mobi = OUT / "frus1955-57v16.mobi"
        if not frus_mobi.exists():
            print("尝试下载 FRUS mobi …")
            try:
                with httpx.Client(timeout=180.0, follow_redirects=True) as client:
                    r = client.get(
                        "https://static.history.state.gov/frus/frus1955-57v16/ebook/frus1955-57v16.mobi"
                    )
                    if r.status_code == 200 and len(r.content) > 1000:
                        frus_mobi.write_bytes(r.content)
                        print(f"已下载 {frus_mobi} ({len(r.content)} bytes)")
            except Exception as exc:  # noqa: BLE001
                print(f"下载失败: {exc}")
        if frus_mobi.is_file() and frus_mobi.stat().st_size > 1000:
            print(f"\n=== MOBI /tasks async ({frus_mobi.name}, {frus_mobi.stat().st_size} bytes) ===")
            mobi_report = convert_file(
                frus_mobi, mime="application/x-mobipocket-ebook", use_async=True, timeout_s=7200.0
            )
            reports.append(mobi_report)
            print(json.dumps({k: v for k, v in mobi_report.items() if k != "body"}, ensure_ascii=False, indent=2))
            md2, n2 = extract_md(mobi_report["body"])
            print(f"md chars: {n2}")
            if md2:
                (OUT / "frus1955-57v16.mobi.md").write_text(md2, encoding="utf-8")

    # 顺带测较大 EPUB(Gutenberg 样例, 若存在)
    gutenberg = OUT / "sample.epub"
    if gutenberg.is_file() and gutenberg.stat().st_size > 10_000:
        print(f"\n=== EPUB /tasks async ({gutenberg.name}, {gutenberg.stat().st_size} bytes) ===")
        g_report = convert_file(gutenberg, mime="application/epub+zip", use_async=True)
        reports.append(g_report)
        print(json.dumps({k: v for k, v in g_report.items() if k != "body"}, ensure_ascii=False, indent=2))
        md_g, n_g = extract_md(g_report["body"])
        print(f"md chars: {n_g}")
        if md_g:
            print("md preview:", md_g[:400].replace("\n", " "))
            (OUT / "sample.epub.md").write_text(md_g, encoding="utf-8")

    summary_path = OUT / "mineru_ebook_probe.json"
    # body 可能很大, 摘要写入
    slim = []
    for r in reports:
        md, n = extract_md(r.get("body") or {})
        slim.append(
            {
                **{k: v for k, v in r.items() if k != "body"},
                "md_chars": n,
                "task_status": (r.get("body") or {}).get("status"),
                "error": (r.get("body") or {}).get("error"),
            }
        )
    summary_path.write_text(json.dumps(slim, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n摘要 → {summary_path}")

    ok = any(r.get("status_code") == 200 and (extract_md(r.get("body") or {})[1] > 0) for r in reports)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
