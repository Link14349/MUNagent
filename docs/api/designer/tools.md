# 设计 Agent 工具链 (`designer/tools/`)

占位, 尚无公开接口(空壳模块). 实现时对应 [design/designer/03-agent-interaction.md](../../../design/designer/03-agent-interaction.md) §7.4 的工具面:

| 分组 | 工具 |
|---|---|
| 文件操作(场景包目录内, 拒绝路径逃逸) | `list_files` / `read_file` / `write_file` |
| 资料检索 | `web_search` / `fetch_page` / `download_file` |
| 格式转换 | `mineru_convert`(见 [docs/tools/agent-api-pdf-to-markdown-guide.md](../../tools/agent-api-pdf-to-markdown-guide.md)) |
