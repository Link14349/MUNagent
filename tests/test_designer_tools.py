"""设计 Agent 工具链测试 — 文件工具用 tmp 场景, 网络工具 mock httpx."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from munagent.config.models import AppConfig, SearchToolConfig, ToolsConfig
from munagent.designer.tools import ToolContext, execute_tool, openai_tool_definitions
from munagent.designer.scenario import package as scenario_svc
from munagent.designer.scenario import chats as chat_svc
from munagent.designer.scenario import files as file_svc
from munagent.designer.scenario.package import ScenarioCreate


@pytest.fixture()
def user_scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(scenario_svc, "user_scenarios_dir", lambda: tmp_path)
    scenario_svc.create_scenario(ScenarioCreate(id="tool-test", title="工具测试"))
    return "tool-test"


@pytest.fixture()
def tool_ctx(user_scenario: str, sample_config: AppConfig) -> ToolContext:
    cfg = sample_config.model_copy(deep=True)
    cfg.tools = ToolsConfig(
        search=SearchToolConfig(provider="tavily", api_key="tvly-test"),
        mineru=sample_config.tools.mineru,
    )
    return ToolContext(scenario_id=user_scenario, config=cfg)


@pytest.fixture()
def chat_ctx(tool_ctx: ToolContext, user_scenario: str) -> ToolContext:
    chat = chat_svc.create_chat(user_scenario, "todo 测试")
    return tool_ctx.model_copy(update={"chat_id": chat.id, "turn": 1})


def test_openai_tool_definitions_count() -> None:
    defs = openai_tool_definitions()
    names = {d["function"]["name"] for d in defs}
    assert names == {
        "list_files",
        "read_file",
        "write_file",
        "web_search",
        "fetch_page",
        "download_file",
        "mineru_convert",
        "check_todo",
        "edit_todo",
    }


@pytest.mark.asyncio
async def test_list_read_write_files(tool_ctx: ToolContext) -> None:
    w = await execute_tool(tool_ctx, "write_file", {"path": "notes.md", "content": "# 备注\n"})
    assert w.ok
    r = await execute_tool(tool_ctx, "read_file", {"path": "notes.md"})
    assert r.ok
    assert r.data is not None
    assert r.data["content"].startswith("# 备注")
    lst = await execute_tool(tool_ctx, "list_files", {"path": ""})
    assert lst.ok
    assert "notes.md" in lst.data["paths"]


@pytest.mark.asyncio
async def test_read_file_not_found(tool_ctx: ToolContext) -> None:
    r = await execute_tool(tool_ctx, "read_file", {"path": "missing.md"})
    assert not r.ok
    assert "不存在" in (r.data or {}).get("error", "")


@pytest.mark.asyncio
async def test_path_escape_rejected(tool_ctx: ToolContext) -> None:
    r = await execute_tool(tool_ctx, "read_file", {"path": "../secret"})
    assert not r.ok


@pytest.mark.asyncio
async def test_download_must_be_under_references(tool_ctx: ToolContext) -> None:
    r = await execute_tool(
        tool_ctx,
        "download_file",
        {"url": "https://example.com/a.pdf", "path": "seats/evil.pdf"},
    )
    assert not r.ok
    assert "references" in (r.data or {}).get("error", "")


@pytest.mark.asyncio
async def test_web_search_tavily(tool_ctx: ToolContext, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.tavily.com":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"title": "标题", "url": "https://ex.com", "content": "摘要文本"},
                    ]
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)

    class _Client(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    r = await execute_tool(tool_ctx, "web_search", {"query": "法国二月革命", "max_results": 3})
    assert r.ok
    assert len(r.data["results"]) == 1


def _patch_httpx_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    transport = httpx.MockTransport(handler)

    class _Client(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)


@pytest.mark.asyncio
async def test_fetch_page(tool_ctx: ToolContext, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body><p>正文</p></body></html>")

    _patch_httpx_transport(monkeypatch, handler)
    r = await execute_tool(tool_ctx, "fetch_page", {"url": "https://example.com/page"})
    assert r.ok
    assert "正文" in r.data["text"]


@pytest.mark.asyncio
async def test_fetch_page_gb2312_meta(tool_ctx: ToolContext, monkeypatch: pytest.MonkeyPatch) -> None:
    html = (
        "<html><head><meta http-equiv='content-type' content='text/html; charset=GB2312'>"
        "</head><body><p>青年视界</p></body></html>"
    ).encode("gb2312")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=html, headers={"content-type": "text/html"})

    _patch_httpx_transport(monkeypatch, handler)
    r = await execute_tool(tool_ctx, "fetch_page", {"url": "https://people.com.cn/article"})
    assert r.ok
    assert "青年视界" in r.data["text"]


@pytest.mark.asyncio
async def test_download_file(tool_ctx: ToolContext, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b"%PDF-1.4 fake"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    _patch_httpx_transport(monkeypatch, handler)
    r = await execute_tool(
        tool_ctx,
        "download_file",
        {"url": "https://example.com/paper.pdf", "path": "references/raw/paper.pdf"},
    )
    assert r.ok
    assert file_svc.read_bytes(tool_ctx.scenario_id, "references/raw/paper.pdf") == payload


@pytest.mark.asyncio
async def test_mineru_convert(tool_ctx: ToolContext, monkeypatch: pytest.MonkeyPatch) -> None:
    file_svc.put_bytes(tool_ctx.scenario_id, "references/raw/doc.pdf", b"%PDF")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/tasks"):
            return httpx.Response(
                202,
                json={
                    "task_id": "t1",
                    "status": "pending",
                },
            )
        if request.url.path.endswith("/tasks/t1"):
            return httpx.Response(200, json={"status": "completed"})
        if request.url.path.endswith("/tasks/t1/result"):
            return httpx.Response(
                200,
                json={"results": {"doc": {"md_content": "# 转换结果\n"}}},
            )
        return httpx.Response(404)

    _patch_httpx_transport(monkeypatch, handler)
    tool_ctx.config.tools.mineru.base_url = "http://mineru.test:8282"
    r = await execute_tool(
        tool_ctx,
        "mineru_convert",
        {"path": "references/raw/doc.pdf"},
    )
    assert r.ok
    got = file_svc.get_file(tool_ctx.scenario_id, "references/doc.md")
    assert got.content.startswith("# 转换结果")
    assert "/tasks" in calls[0]


@pytest.mark.asyncio
async def test_check_todo_empty(chat_ctx: ToolContext) -> None:
    r = await execute_tool(chat_ctx, "check_todo", {})
    assert r.ok
    assert r.data is not None
    assert r.data["text"] == "(暂无 todo)"


@pytest.mark.asyncio
async def test_edit_and_check_todo(chat_ctx: ToolContext) -> None:
    text = "[ ] 第一项\n[x] 第二项"
    r = await execute_tool(chat_ctx, "edit_todo", {"todo": text})
    assert r.ok
    assert r.data is not None
    assert r.data["text"] == text
    r2 = await execute_tool(chat_ctx, "check_todo", {})
    assert r2.ok
    assert r2.data is not None
    assert r2.data["text"] == text


@pytest.mark.asyncio
async def test_edit_todo_invalid_line(chat_ctx: ToolContext) -> None:
    r = await execute_tool(chat_ctx, "edit_todo", {"todo": "bad line"})
    assert not r.ok


@pytest.mark.asyncio
async def test_check_todo_requires_chat_id(tool_ctx: ToolContext) -> None:
    r = await execute_tool(tool_ctx, "check_todo", {})
    assert not r.ok


@pytest.mark.asyncio
async def test_list_package_files_includes_binary(user_scenario: str) -> None:
    file_svc.put_bytes(user_scenario, "references/raw/x.pdf", b"bin")
    paths = file_svc.list_package_files(user_scenario)
    assert "references/raw/x.pdf" in paths
