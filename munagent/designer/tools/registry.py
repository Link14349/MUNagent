"""工具注册表 — 统一执行入口与 OpenAI tools 定义."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from munagent.designer.tools.base import ToolContext, ToolExecutionError, ToolResult, clip_summary
from munagent.designer.tools.fetch import DownloadFileArgs, FetchPageArgs, download_file, fetch_page
from munagent.designer.tools.files import (
    AppendFileArgs,
    InsertFileArgs,
    ListFilesArgs,
    ReadFileArgs,
    WriteFileArgs,
    append_file,
    insert_file,
    list_files,
    read_file,
    write_file,
)
from munagent.designer.tools.mineru import MineruConvertArgs, mineru_convert
from munagent.designer.tools.search import WebSearchArgs, web_search
from munagent.designer.tools.search_pdf import SearchWebPdfArgs, search_web_pdf
from munagent.designer.tools.wikipedia import SearchWikipediaArgs, search_wikipedia
from munagent.designer.tools.todo import CheckTodoArgs, EditTodoArgs, check_todo, edit_todo

ToolHandler = Callable[[ToolContext, BaseModel], Awaitable[ToolResult]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: ToolHandler


TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "list_files",
        "列出场景包内文件路径(含 references/ 下二进制). 可选目录前缀过滤.",
        ListFilesArgs,
        list_files,
    ),
    ToolSpec(
        "read_file",
        "读取场景包内文本文件全文(manifest/seats/background 等 yaml/md).",
        ReadFileArgs,
        read_file,
    ),
    ToolSpec(
        "write_file",
        "创建或覆盖场景包内文本文件(全量); 返回校验 issues. 改结构/改 YAML 时用.",
        WriteFileArgs,
        write_file,
    ),
    ToolSpec(
        "append_file",
        "在文本文件末尾追加 content(只传新增段落, 勿重复旧正文); 文件不存在则创建. 扩写 background.md 等长文首选.",
        AppendFileArgs,
        append_file,
    ),
    ToolSpec(
        "insert_file",
        "在锚点行之前/之后插入 content. anchor 须为 read_file 见到的完整一行(通常 ## 标题); position: after/before/end.",
        InsertFileArgs,
        insert_file,
    ),
    ToolSpec(
        "search_wikipedia",
        "资料检索首选: Wikipedia API 搜条目, 全文写入 references/wikipedia/*.md, 并返回摘要/可选正文 + 外链 PDF 列表.",
        SearchWikipediaArgs,
        search_wikipedia,
    ),
    ToolSpec(
        "web_search",
        "泛网检索, 返回标题/链接/摘要. 维基之后找 HTML 页面或机构站线索, 配合 fetch_page. 需 tools.search.",
        WebSearchArgs,
        web_search,
    ),
    ToolSpec(
        "search_web_pdf",
        "维基与泛网仍缺文献时, 用 Google 语法 filetype:pdf 搜索 PDF 直链(默认不限 site). 需 tools.search.",
        SearchWebPdfArgs,
        search_web_pdf,
    ),
    ToolSpec(
        "fetch_page",
        "抓取网页正文为纯文本(HTML 去标签), 用于阅读单页内容.",
        FetchPageArgs,
        fetch_page,
    ),
    ToolSpec(
        "download_file",
        "从 URL 下载文件到场景包 references/ 下(如 PDF 原始件).",
        DownloadFileArgs,
        download_file,
    ),
    ToolSpec(
        "mineru_convert",
        "将场景包内 pdf/epub/mobi 转为 Markdown 写入 references/. 优先用 PDF; 无 PDF 时可用 epub/mobi. 需 MinerU 服务.",
        MineruConvertArgs,
        mineru_convert,
    ),
    ToolSpec(
        "check_todo",
        "读取当前对话最新计划清单全文; 无 todo 时返回提示文案.",
        CheckTodoArgs,
        check_todo,
    ),
    ToolSpec(
        "edit_todo",
        "全量替换当前对话计划清单(一行一项, 非空行以 [ ] 或 [x] 开头). "
        "每完成 write_file / append_file / insert_file 等计划项后须立即调用, 把对应行改为 [x] .",
        EditTodoArgs,
        edit_todo,
    ),
)

_TOOLS_BY_NAME: dict[str, ToolSpec] = {s.name: s for s in TOOL_SPECS}
TOOL_NAMES: tuple[str, ...] = tuple(s.name for s in TOOL_SPECS)


def openai_tool_definitions() -> list[dict[str, Any]]:
    """OpenAI 兼容 function calling 的 tools 数组."""
    defs: list[dict[str, Any]] = []
    for spec in TOOL_SPECS:
        schema = spec.args_model.model_json_schema()
        schema.pop("title", None)
        defs.append(
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": schema,
                },
            }
        )
    return defs


async def execute_tool(ctx: ToolContext, name: str, arguments: dict[str, Any]) -> ToolResult:
    """按名称执行工具; 业务错误不抛异常, 统一为 ok=False 的 ToolResult."""
    spec = _TOOLS_BY_NAME.get(name)
    if spec is None:
        msg = f"未知工具: {name}"
        return ToolResult(ok=False, summary=clip_summary(msg), data={"error": msg})
    try:
        args = spec.args_model.model_validate(arguments)
    except ValidationError as exc:
        msg = "参数无效"
        return ToolResult(ok=False, summary=clip_summary(msg), data={"error": str(exc)})
    try:
        return await spec.handler(ctx, args)
    except ToolExecutionError as exc:
        return ToolResult(ok=False, summary=clip_summary(exc.message), data={"error": exc.message})
