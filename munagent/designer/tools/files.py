"""场景包内文件工具 — 委托 designer.scenario.files, 不重复实现 IO."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from munagent.designer.tools.base import ToolContext, ToolExecutionError, ToolResult, clip_summary
from munagent.designer.scenario import files as file_svc

InsertPosition = Literal["after", "before", "end"]


class ListFilesArgs(BaseModel):
    path: str = Field(default="", description="可选目录前缀, 如 seats 或 references")


class ReadFileArgs(BaseModel):
    path: str = Field(description="场景包内相对路径")


class WriteFileArgs(BaseModel):
    path: str = Field(description="场景包内相对路径")
    content: str = Field(description="文件全文")


class AppendFileArgs(BaseModel):
    path: str = Field(description="场景包内相对路径")
    content: str = Field(description="追加到文件末尾的文本(只写新增部分, 勿重复旧正文)")


class InsertFileArgs(BaseModel):
    path: str = Field(description="场景包内相对路径")
    content: str = Field(description="要插入的文本块")
    anchor: str = Field(
        description="锚点: 文件中某一整行的精确文本(通常为 ## 标题行); read_file 后原样复制"
    )
    position: InsertPosition = Field(
        default="after",
        description="after=锚点行之后, before=锚点行之前, end=等同 append 到文末",
    )


def merge_append(old: str, content: str) -> str:
    """在文末拼接 content; 文件为空时等价于 write."""
    piece = content.lstrip("\n")
    if not old:
        return piece
    if not piece:
        return old
    return old.rstrip("\n") + "\n\n" + piece


def insert_at_anchor(old: str, content: str, anchor: str, position: InsertPosition) -> str:
    """按锚点行插入; position=end 时走 merge_append."""
    if position == "end":
        return merge_append(old, content)

    anchor_stripped = anchor.strip()
    if not anchor_stripped:
        raise ValueError("anchor 不能为空")

    lines = old.splitlines(keepends=True)
    if not lines and old:
        lines = [old]
    if not lines and not old:
        raise ValueError("文件为空, 无法用 anchor 插入; 请用 append_file 或 write_file")

    matches = [i for i, line in enumerate(lines) if line.strip() == anchor_stripped]
    if not matches:
        raise ValueError(f"锚点行未找到: {anchor!r} — 请 read_file 后复制 exact 标题行")
    if len(matches) > 1:
        raise ValueError(f"锚点行不唯一({len(matches)} 处): {anchor!r}")

    idx = matches[0]
    block = content if content.endswith("\n") or not content else content + "\n"
    if position == "after":
        return "".join(lines[: idx + 1]) + block + "".join(lines[idx + 1 :])
    return "".join(lines[:idx]) + block + "".join(lines[idx:])


def _read_or_empty(scenario_id: str, path: str) -> tuple[str, bool]:
    try:
        return file_svc.get_file(scenario_id, path).content, True
    except FileNotFoundError:
        return "", False
    except ValueError as exc:
        raise ToolExecutionError(str(exc)) from exc


def _put_text(ctx: ToolContext, path: str, new_content: str, *, existed: bool) -> ToolResult:
    try:
        result = file_svc.put_file(ctx.scenario_id, path, new_content)
    except PermissionError as exc:
        raise ToolExecutionError(str(exc)) from exc
    except ValueError as exc:
        raise ToolExecutionError(str(exc)) from exc
    op = "modify" if existed else "create"
    err_count = sum(1 for v in result.validation if v.level == "error")
    summary = f"{op} {path}"
    if err_count:
        summary += f", 校验 {err_count} 处 error"
    return ToolResult(
        ok=True,
        summary=clip_summary(summary),
        data={
            "path": path,
            "op": op,
            "new_content": new_content,
            "validation": [v.model_dump() for v in result.validation],
        },
    )


async def list_files(ctx: ToolContext, args: ListFilesArgs) -> ToolResult:
    paths = file_svc.list_package_files(ctx.scenario_id, args.path)
    return ToolResult(
        ok=True,
        summary=clip_summary(f"共 {len(paths)} 个文件" + (f" 于 {args.path}" if args.path else "")),
        data={"paths": paths},
    )


async def read_file(ctx: ToolContext, args: ReadFileArgs) -> ToolResult:
    try:
        got = file_svc.get_file(ctx.scenario_id, args.path)
    except FileNotFoundError as exc:
        raise ToolExecutionError(str(exc)) from exc
    except ValueError as exc:
        raise ToolExecutionError(str(exc)) from exc
    return ToolResult(
        ok=True,
        summary=clip_summary(f"读取 {args.path}, {len(got.content)} 字符"),
        data={"path": got.path, "content": got.content},
    )


async def write_file(ctx: ToolContext, args: WriteFileArgs) -> ToolResult:
    old, existed = _read_or_empty(ctx.scenario_id, args.path)
    del old
    result = _put_text(ctx, args.path, args.content, existed=existed)
    if result.data is not None:
        result.data["added_chars"] = len(args.content)
    return result


async def append_file(ctx: ToolContext, args: AppendFileArgs) -> ToolResult:
    old, existed = _read_or_empty(ctx.scenario_id, args.path)
    new_content = merge_append(old, args.content)
    result = _put_text(ctx, args.path, new_content, existed=existed)
    if result.data is not None:
        result.data["added_chars"] = len(new_content) - len(old)
    return result


async def insert_file(ctx: ToolContext, args: InsertFileArgs) -> ToolResult:
    old, existed = _read_or_empty(ctx.scenario_id, args.path)
    try:
        new_content = insert_at_anchor(old, args.content, args.anchor, args.position)
    except ValueError as exc:
        raise ToolExecutionError(str(exc)) from exc
    result = _put_text(ctx, args.path, new_content, existed=existed)
    if result.data is not None:
        result.data["added_chars"] = len(new_content) - len(old)
        result.data["anchor"] = args.anchor
        result.data["position"] = args.position
    return result
