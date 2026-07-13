#!/usr/bin/env python3
"""验证 search_web_pdf + search_wikipedia — 真实联网, 结果复制到 ./out/.

用法:
  python scripts/verify_search_tools.py

依赖 ~/.munagent/config.yaml:
  - tools.search.api_key (search_web_pdf)
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from munagent.config import load_config, mask_api_key
from munagent.designer.scenario import files as file_svc
from munagent.designer.scenario import package as scenario_svc
from munagent.designer.scenario.package import ScenarioCreate
from munagent.designer.tools import ToolContext, execute_tool

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "out"
SCENARIO_ID = "search-verify"

PDF_QUERIES = [
    "Suez Crisis 1956 report",
    "cuba missile crisis declassified filetype:pdf",
]
WIKI_QUERIES = [
    ("Suez Crisis", "en"),
    ("Cuban Missile Crisis", "en"),
]


def _banner(title: str) -> None:
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def _print_result(label: str, result) -> None:
    print(f"\n[{label}] ok={result.ok}  summary={result.summary!r}")
    if result.data is not None:
        print(json.dumps(result.data, ensure_ascii=False, indent=2))


def _copy_scenario_file(scenario_id: str, rel: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        content = file_svc.get_file(scenario_id, rel).content
        dest.write_text(content, encoding="utf-8")
    except ValueError:
        data = file_svc.read_bytes(scenario_id, rel)
        dest.write_bytes(data)
    print(f"已复制 → {dest.relative_to(REPO_ROOT)}")
    return dest


def _ensure_scenario() -> None:
    try:
        scenario_svc.delete_scenario(SCENARIO_ID)
        print(f"已删除旧场景 {SCENARIO_ID}")
    except (FileNotFoundError, ValueError, PermissionError):
        pass
    scenario_svc.create_scenario(ScenarioCreate(id=SCENARIO_ID, title="检索工具验证"))
    print(f"已创建用户场景 {SCENARIO_ID} (~/.munagent/scenarios/{SCENARIO_ID})")


async def step_search_web_pdf(ctx: ToolContext) -> list[dict]:
    _banner("1/2 search_web_pdf")
    all_reports: list[dict] = []

    for i, query in enumerate(PDF_QUERIES, 1):
        print(f"\n--- 查询 {i}/{len(PDF_QUERIES)}: {query!r} ---")
        result = await execute_tool(
            ctx,
            "search_web_pdf",
            {"query": query, "max_results": 5},
        )
        _print_result(f"search_web_pdf[{i}]", result)
        if not result.ok:
            raise RuntimeError(f"search_web_pdf 失败: {query}")
        data = result.data or {}
        all_reports.append(data)
        results = data.get("results") or []

        safe = query.replace(" ", "_")[:40]
        json_path = OUT_DIR / f"search_web_pdf_{safe}.json"
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"已保存 JSON → {json_path.relative_to(REPO_ROOT)}")

    has_pdf = any((r.get("results") or []) for r in all_reports)
    if has_pdf:
        print(f"\n尝试下载 PDF 样本(跳过 403 等失败项)…")
        downloaded = False
        for report in all_reports:
            for item in report.get("results") or []:
                url = item.get("pdf_url") or ""
                if not url:
                    continue
                print(f"  试: {url}")
                dl = await execute_tool(
                    ctx,
                    "download_file",
                    {
                        "url": url,
                        "path": "references/raw/search_verify_sample.pdf",
                    },
                )
                if dl.ok:
                    _print_result("download_file(样本 PDF)", dl)
                    _copy_scenario_file(
                        SCENARIO_ID,
                        "references/raw/search_verify_sample.pdf",
                        OUT_DIR / "search_verify_sample.pdf",
                    )
                    downloaded = True
                    break
                print(f"    跳过: {dl.summary}")
            if downloaded:
                break
        if not downloaded:
            print("\n[跳过] 所有 PDF 样本下载均失败(常见: JSTOR/ResearchGate 403)")
    else:
        print("\n[跳过] 未找到 PDF 直链")

    summary_path = OUT_DIR / "search_web_pdf_summary.json"
    summary_path.write_text(
        json.dumps(all_reports, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"汇总 → {summary_path.relative_to(REPO_ROOT)}")
    return all_reports


async def step_search_wikipedia(ctx: ToolContext) -> list[dict]:
    _banner("2/2 search_wikipedia")
    all_reports: list[dict] = []

    for i, (query, lang) in enumerate(WIKI_QUERIES, 1):
        print(f"\n--- 查询 {i}/{len(WIKI_QUERIES)}: {query!r} ({lang}) ---")
        result = await execute_tool(
            ctx,
            "search_wikipedia",
            {
                "query": query,
                "lang": lang,
                "max_results": 2,
                "max_pdf_links": 5,
            },
        )
        _print_result(f"search_wikipedia[{i}]", result)
        if not result.ok:
            raise RuntimeError(f"search_wikipedia 失败: {query}")
        data = result.data or {}
        all_reports.append(data)

        safe = query.replace(" ", "_")[:40]
        json_path = OUT_DIR / f"search_wikipedia_{lang}_{safe}.json"
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"已保存 JSON → {json_path.relative_to(REPO_ROOT)}")

        for rel in data.get("saved_paths") or []:
            dest_name = Path(rel).name
            _copy_scenario_file(SCENARIO_ID, rel, OUT_DIR / dest_name)

    summary_path = OUT_DIR / "search_wikipedia_summary.json"
    summary_path.write_text(
        json.dumps(all_reports, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"汇总 → {summary_path.relative_to(REPO_ROOT)}")
    return all_reports


async def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    config = load_config()

    search_key = config.tools.search.api_key
    if not search_key:
        print("错误: 未配置 tools.search.api_key (~/.munagent/config.yaml)", file=sys.stderr)
        return 1

    print(f"search.provider={config.tools.search.provider}  key={mask_api_key(search_key)}")
    print(f"输出目录: {OUT_DIR.relative_to(REPO_ROOT)}/")

    _ensure_scenario()
    ctx = ToolContext(scenario_id=SCENARIO_ID, config=config)

    try:
        await step_search_web_pdf(ctx)
        await step_search_wikipedia(ctx)
    except Exception as exc:
        print(f"\n验证失败: {exc}", file=sys.stderr)
        return 1

    _banner("完成")
    print(f"场景包: ~/.munagent/scenarios/{SCENARIO_ID}")
    print(f"导出副本: {OUT_DIR.relative_to(REPO_ROOT)}/")
    for p in sorted(OUT_DIR.iterdir()):
        if p.name.startswith(("search_", "en_")) or p.name == "search_verify_sample.pdf":
            print(f"  - {p.name} ({p.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
