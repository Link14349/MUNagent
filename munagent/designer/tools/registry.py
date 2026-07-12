"""工具注册表 — 统一执行入口与 OpenAI tools 定义."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from munagent.designer.tools.base import ToolContext, ToolExecutionError, ToolResult, clip_summary
from munagent.designer.tools.fetch import DownloadFileArgs, FetchPageArgs, download_file, fetch_page
from munagent.designer.tools.files import ListFilesArgs, ReadFileArgs, WriteFileArgs, list_files, read_file, write_file
from munagent.designer.tools.mineru import MineruConvertArgs, mineru_convert
from munagent.designer.tools.search import WebSearchArgs, web_search
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
        "创建或覆盖场景包内文本文件; 返回校验 issues.",
        WriteFileArgs,
        write_file,
    ),
    ToolSpec(
        "web_search",
        "联网检索资料, 返回标题/链接/摘要列表. 需配置 tools.search.",
        WebSearchArgs,
        web_search,
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
        "将场景包内 PDF 转为 Markdown 写入 references/. 需 MinerU 服务.",
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
        "全量替换当前对话计划清单(一行一项, 非空行以 [ ] 或 [x] 开头); 写入 chats 记录.",
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
