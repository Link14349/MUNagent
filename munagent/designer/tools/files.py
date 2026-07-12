"""场景包内文件工具 — 委托 designer.scenario.files, 不重复实现 IO."""

from __future__ import annotations

from pydantic import BaseModel, Field

from munagent.designer.tools.base import ToolContext, ToolExecutionError, ToolResult, clip_summary
from munagent.designer.scenario import files as file_svc


class ListFilesArgs(BaseModel):
    path: str = Field(default="", description="可选目录前缀, 如 seats 或 references")


class ReadFileArgs(BaseModel):
    path: str = Field(description="场景包内相对路径")


class WriteFileArgs(BaseModel):
    path: str = Field(description="场景包内相对路径")
    content: str = Field(description="文件全文")


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
    existed = True
    try:
        file_svc.get_file(ctx.scenario_id, args.path)
    except FileNotFoundError:
        existed = False
    except ValueError:
        existed = False
    try:
        result = file_svc.put_file(ctx.scenario_id, args.path, args.content)
    except PermissionError as exc:
        raise ToolExecutionError(str(exc)) from exc
    except ValueError as exc:
        raise ToolExecutionError(str(exc)) from exc
    op = "修改" if existed else "创建"
    err_count = sum(1 for v in result.validation if v.level == "error")
    summary = f"{op} {args.path}"
    if err_count:
        summary += f", 校验 {err_count} 处 error"
    return ToolResult(
        ok=True,
        summary=clip_summary(summary),
        data={
            "path": args.path,
            "op": "modify" if existed else "create",
            "validation": [v.model_dump() for v in result.validation],
        },
    )
