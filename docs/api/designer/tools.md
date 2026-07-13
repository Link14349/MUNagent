# 设计 Agent 工具链 (`designer/tools/`)

对应 [design/designer/03-agent-interaction.md](../../../design/designer/03-agent-interaction.md) §7.4. 文件类工具委托 `designer/scenario/files.py`, 不重复实现 IO.

**使用指南(参数示例、推荐工作流)**: [docs/tools/designer-agent-tools.md](../../tools/designer-agent-tools.md)

## 公开入口 (`designer/tools/__init__.py`)

| 符号 | 说明 |
|---|---|
| `ToolContext` | `scenario_id` + `AppConfig` + 可选 `chat_id` / `turn`(todo 工具用) |
| `ToolResult` | `ok` / `summary`(≤200字, 写入 chat tool_call) / `data` |
| `TOOL_NAMES` | 13 个工具名元组 |
| `execute_tool(ctx, name, arguments) -> ToolResult` | 统一执行; 业务错误不抛异常 |
| `openai_tool_definitions() -> list[dict]` | OpenAI 兼容 `tools` 数组 |

## 工具一览

| 名称 | 模块 | 约束 |
|---|---|---|
| `list_files` | `files.py` | 可选 `path` 前缀; 含二进制 |
| `read_file` | `files.py` | 仅文本后缀 yaml/md/txt |
| `write_file` | `files.py` | 全量覆盖写入; 返回 validation |
| `append_file` | `files.py` | 文末追加 `content`; 不存在则创建; `data.new_content` 供 file_edit diff |
| `insert_file` | `files.py` | 按 `anchor` 整行匹配插入; `position`: after/before/end |
| `search_wikipedia` | `wikipedia.py` | 全文落盘 `references/wikipedia/{lang}_{slug}.md`; 返回摘要 + 外链 PDF; **检索首选** |
| `web_search` | `search.py` | `tools.search` provider: tavily/serper/bocha; 配合 `fetch_page` |
| `search_web_pdf` | `search_pdf.py` | 自动 `filetype:pdf` 搜 PDF 直链; 可选 `site`; 需 `tools.search` |
| `fetch_page` | `fetch.py` | HTML→纯文本, `max_chars` 截断 |
| `download_file` | `fetch.py` | 仅 `references/` 下, 上限 50MB |
| `mineru_convert` | `mineru.py` | 场景内 pdf/epub/mobi→`references/*.md`; 见 [MinerU 指南](../../tools/agent-api-pdf-to-markdown-guide.md) |
| `check_todo` | `todo.py` | 无参; 读当前 chat 最新 todo 全文(无则 `"(暂无 todo)"`) |
| `edit_todo` | `todo.py` | 全量替换计划清单; 校验行前缀后追加 `type:todo` 记录 |

## scenario 扩展 (`designer/scenario/files.py`)

| 函数 | 说明 |
|---|---|
| `list_package_files(id, prefix="")` | Agent 用文件清单(含 PDF 等) |
| `read_bytes(id, path)` | 读二进制(供 MinerU 上传) |
| `put_bytes(id, path, data)` | 写二进制(供 download_file) |
