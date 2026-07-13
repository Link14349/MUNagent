#!/usr/bin/env python3
"""设计 Agent 工具链一次性验证 — 真实联网/MinerU, 结果复制到 ./out/.

用法:
  python scripts/verify_designer_tools.py

依赖 ~/.munagent/config.yaml:
  - tools.search.api_key (web_search)
  - tools.mineru.base_url (mineru_convert; 未配置则 PDF 只下载不转换)
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from munagent.config import load_config, mask_api_key
from munagent.config.models import AppConfig
from munagent.designer.scenario import files as file_svc
from munagent.designer.scenario import package as scenario_svc
from munagent.designer.scenario.package import ScenarioCreate
from munagent.designer.tools import ToolContext, execute_tool

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "out"
SCENARIO_ID = "tool-verify"
PDF_URL = "https://arxiv.org/pdf/2512.02104"
PDF_REL = "references/raw/2512.02104.pdf"
MD_REL = "references/2512.02104.md"
EDIT_REL = "background.md"
FETCH_FALLBACK_URL = "https://bimun.org.cn/committees/jcc-2"


def _banner(title: str) -> None:
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def _print_result(label: str, result) -> None:
    print(f"\n[{label}] ok={result.ok}  summary={result.summary!r}")
    if result.data is not None:
        print(json.dumps(result.data, ensure_ascii=False, indent=2))


def _copy_scenario_file(scenario_id: str, rel: str, dest_name: str | None = None) -> Path:
    dest = OUT_DIR / (dest_name or Path(rel).name)
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
    scenario_svc.create_scenario(ScenarioCreate(id=SCENARIO_ID, title="工具验证"))
    print(f"已创建用户场景 {SCENARIO_ID} (~/.munagent/scenarios/{SCENARIO_ID})")


async def step_web_search(ctx: ToolContext) -> str:
    _banner("1/4 web_search")
    query = "模拟联合国 历史委员会 危机联动"
    result = await execute_tool(ctx, "web_search", {"query": query, "max_results": 3})
    _print_result("web_search", result)
    if not result.ok:
        raise RuntimeError("web_search 失败")
    results = (result.data or {}).get("results") or []
    pick_url = ""
    for i, item in enumerate(results, 1):
        title = item.get("title") or item.get("name") or "(无标题)"
        url = item.get("url") or item.get("link") or ""
        snippet = (item.get("snippet") or item.get("content") or "")[:200]
        print(f"\n  [{i}] {title}\n      {url}\n      {snippet}…")
        if not pick_url and url:
            pick_url = url
    return pick_url or FETCH_FALLBACK_URL


async def step_fetch_page(ctx: ToolContext, url: str) -> None:
    _banner("2/4 fetch_page")
    print(f"抓取 URL: {url}")
    result = await execute_tool(ctx, "fetch_page", {"url": url, "max_chars": 4000})
    _print_result("fetch_page", result)
    if not result.ok:
        raise RuntimeError("fetch_page 失败")
    text = (result.data or {}).get("text") or ""
    out_path = OUT_DIR / "fetch_page.txt"
    out_path.write_text(text, encoding="utf-8")
    print(f"已保存正文 → {out_path.relative_to(REPO_ROOT)} ({len(text)} 字符)")
    print("\n正文预览(前 600 字符):")
    print("-" * 40)
    print(text[:600])
    if len(text) > 600:
        print("…(已截断)")


async def step_download_and_mineru(ctx: ToolContext, config: AppConfig) -> None:
    _banner("3/4 download_file + mineru_convert")
    print(f"PDF URL: {PDF_URL}")
    dl = await execute_tool(
        ctx,
        "download_file",
        {"url": PDF_URL, "path": PDF_REL},
    )
    _print_result("download_file", dl)
    if not dl.ok:
        raise RuntimeError("download_file 失败")

    _copy_scenario_file(SCENARIO_ID, PDF_REL, "2512.02104.pdf")

    mineru_url = (config.tools.mineru.base_url or "").strip()
    if not mineru_url:
        print("\n[跳过] 未配置 tools.mineru.base_url, mineru_convert 未执行")
        print("       可在 ~/.munagent/config.yaml 设置后重跑")
        return

    print(f"\nMinerU: {mineru_url}")
    conv = await execute_tool(ctx, "mineru_convert", {"path": PDF_REL})
    _print_result("mineru_convert", conv)
    if not conv.ok:
        raise RuntimeError("mineru_convert 失败")

    _copy_scenario_file(SCENARIO_ID, MD_REL, "2512.02104.md")
    preview = file_svc.get_file(SCENARIO_ID, MD_REL).content[:800]
    print("\nMarkdown 预览(前 800 字符):")
    print("-" * 40)
    print(preview)
    if len(file_svc.get_file(SCENARIO_ID, MD_REL).content) > 800:
        print("…(已截断)")


async def step_read_write_read(ctx: ToolContext) -> None:
    _banner("4/4 read_file → write_file → read_file")
    initial = "# 工具验证\n\n初始内容: hello designer tools.\n"
    w0 = await execute_tool(
        ctx,
        "write_file",
        {"path": EDIT_REL, "content": initial},
    )
    _print_result("write_file(初始)", w0)
    if not w0.ok:
        raise RuntimeError("write_file(初始) 失败")

    r1 = await execute_tool(ctx, "read_file", {"path": EDIT_REL})
    _print_result("read_file(编辑前)", r1)
    if not r1.ok:
        raise RuntimeError("read_file(编辑前) 失败")
    print("\n--- 编辑前全文 ---")
    print(r1.data.get("content", "") if r1.data else "")

    edited = initial + "\n## 追加段落\n\n已通过 write_file 修改。\n"
    w1 = await execute_tool(
        ctx,
        "write_file",
        {"path": EDIT_REL, "content": edited},
    )
    _print_result("write_file(修改)", w1)
    if not w1.ok:
        raise RuntimeError("write_file(修改) 失败")

    r2 = await execute_tool(ctx, "read_file", {"path": EDIT_REL})
    _print_result("read_file(编辑后)", r2)
    if not r2.ok:
        raise RuntimeError("read_file(编辑后) 失败")
    print("\n--- 编辑后全文 ---")
    print(r2.data.get("content", "") if r2.data else "")

    _copy_scenario_file(SCENARIO_ID, EDIT_REL, "background.md")


async def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    config = load_config()

    search_key = config.tools.search.api_key
    if not search_key:
        print("错误: 未配置 tools.search.api_key (~/.munagent/config.yaml)", file=sys.stderr)
        return 1
    print(f"search.provider={config.tools.search.provider}  key={mask_api_key(search_key)}")
    print(f"mineru.base_url={config.tools.mineru.base_url or '(未配置)'}")
    print(f"输出目录: {OUT_DIR.relative_to(REPO_ROOT)}/")

    _ensure_scenario()
    ctx = ToolContext(scenario_id=SCENARIO_ID, config=config)

    try:
        fetch_url = await step_web_search(ctx)
        await step_fetch_page(ctx, fetch_url)
        await step_download_and_mineru(ctx, config)
        await step_read_write_read(ctx)
    except Exception as exc:
        print(f"\n验证失败: {exc}", file=sys.stderr)
        return 1

    _banner("完成")
    print(f"场景包: ~/.munagent/scenarios/{SCENARIO_ID}")
    print(f"导出副本: {OUT_DIR.relative_to(REPO_ROOT)}/")
    for p in sorted(OUT_DIR.iterdir()):
        print(f"  - {p.name} ({p.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
