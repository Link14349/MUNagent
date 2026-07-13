# 设计 Agent 工具使用指南

> 面向**使用设计 Agent 的人**与**维护 prompt 的开发者**. 代码接口地图见 [docs/api/designer/tools.md](../api/designer/tools.md).
>
> 当前共 **11** 个工具. 验证脚本: `scripts/verify_designer_tools.py`(全链), `scripts/verify_search_tools.py`(检索专项).

## 配置前提

| 配置项 | 用途 | 未配置时 |
|--------|------|----------|
| `tools.search.api_key` + `provider` | `web_search`, `search_web_pdf` | 检索类工具报错 |
| `tools.mineru.base_url` | `mineru_convert` | 无法转 PDF/epub/mobi |
| (无) | `search_wikipedia` | 始终可用, 注意 Wiki API 限速 |

Provider 支持: `tavily` / `serper` / `bocha`.

---

## 推荐使用顺序(资料检索)

设计历史委/危机委场景时, 建议 Agent 按此优先级找资料:

```
1. search_wikipedia   → 建背景 + 条目外链里的 PDF 线索(自动存 md)
2. web_search         → 泛网搜页面/机构站线索
   fetch_page         → 读取单页 HTML(条约站、新闻等; 维基勿用)
3. search_web_pdf     → 仍缺 PDF 时用 filetype:pdf 找直链
4. download_file      → 把 PDF/epub/mobi 拉到 references/raw/
   mineru_convert     → 转成 references/*.md 供阅读
```

**典型链路 A — 维基起步(默认)**

```
search_wikipedia("Suez Crisis", lang="en")
  # 自动写入 references/wikipedia/en_Suez_Crisis.md
  → 从返回的 pdf_urls 挑一条
  → download_file → mineru_convert
  → write_file("background.md", ...)  # 结合维基 md 与转换后的文献
```

**典型链路 B — 泛网页面**

```
web_search("1956 Suez Canal UN Security Council")
  → fetch_page(avalon / un.org 等 HTML 页)
  → 若需 PDF 再进入链路 C
```

**典型链路 C — 定向搜 PDF**

```
search_web_pdf("Suez Crisis 1956 declassified")
  → download_file(pdf_url, "references/raw/suez_nsarchive.pdf")
  → mineru_convert("references/raw/suez_nsarchive.pdf")
  → read_file("references/suez_nsarchive.md")  # 写 background 前通读
```

**注意**

- 维基全文用 `search_wikipedia`, **不要** `fetch_page` 抓维基 HTML.
- `search_web_pdf` 默认**不限** `site:`; 需要某机构文件时传 `site: "un.org"` 等.
- JSTOR / ResearchGate 等常 403, 换 `nsarchive.gwu.edu`、`archives.gov` 等结果.
- `mineru_convert` 支持 `.pdf` / `.epub` / `.mobi`; 大部头 epub/mobi 约 5–10 分钟.
- 维基搜索结果可能混入**年代无关**条目(如 2021 堵船), Agent 应挑与主题最相关的标题.

---

## 工具详解

### 场景包文件

#### `list_files`

列出场景包内文件(含 `references/` 下 PDF 等二进制).

```json
{"path": ""}
{"path": "seats"}
{"path": "references"}
```

#### `read_file`

读取文本文件全文(yaml / md / txt). 写 background、改席位前先读.

```json
{"path": "background.md"}
{"path": "seats/premier.yaml"}
{"path": "references/wikipedia/en_Suez_Crisis.md"}
```

#### `write_file`

全量覆盖写入; 返回结构校验 `issues`. 改 `venues.yaml` 后记得联动检查 `seats/`.

```json
{"path": "background.md", "content": "# 背景\n\n..."}
```

---

### 资料检索

#### `search_wikipedia` ⭐ 首选: 背景 + PDF 线索

MediaWiki API 搜条目; **全文自动写入** `references/wikipedia/{lang}_{slug}.md`. 资料检索**第一步**.

```json
{"query": "Suez Crisis", "lang": "en", "max_results": 2}
{"query": "Cuban Missile Crisis", "lang": "en", "max_results": 1, "max_pdf_links": 5, "include_full_text": true}
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `query` | (必填) | 条目检索词 |
| `lang` | `en` | 维基语言代码 |
| `max_results` | 3 | 1–5 条 |
| `include_full_text` | false | 为 true 时工具**返回值**也带全文(可截断); 落盘始终全文 |
| `max_text_chars` | 12000 | 返回值全文上限 |
| `max_pdf_links` | 5 | 每条目返回几条外链 PDF |

返回: `saved_paths`, `pages[].summary`, `pages[].pdf_urls`, `pages[].reference_path`.

#### `web_search`

泛网搜索, 返回标题/链接/摘要. **不**自动过滤 PDF; 维基之后用来找 HTML 页面或机构站线索, 配合 `fetch_page`.

```json
{"query": "1956 Suez Canal UN Security Council", "max_results": 5}
```

#### `fetch_page`

抓取单页 HTML 转纯文本(条约站、新闻等). 维基**不推荐**用此工具(噪声大), 用 `search_wikipedia`.

```json
{"url": "https://avalon.law.yale.edu/20th_century/imperialism.asp", "max_chars": 8000}
```

#### `search_web_pdf` ⭐ 仍缺 PDF 时用

经 `tools.search` 发 Google 风格查询, **自动追加** `filetype:pdf`, 只返回 URL 含 `.pdf` 的结果. 在维基与泛网之后仍缺文献时再调用.

```json
{"query": "Suez Crisis 1956 report", "max_results": 5}
{"query": "cuba missile crisis declassified", "max_results": 5, "site": "archives.gov"}
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `query` | (必填) | 英文关键词 + 事件名/年份 |
| `max_results` | 5 | 1–10 |
| `site` | null | 可选, 如 `un.org` |

返回 `results[].pdf_url` 可直接给 `download_file`.

#### `download_file`

从 URL 下载到场景包; **路径必须在 `references/` 下**, 单文件 ≤ 50MB.

```json
{
  "url": "https://nsarchive.gwu.edu/sites/default/files/documents/20515408/doc-5-cna-suez-1956.pdf",
  "path": "references/raw/suez_nsarchive.pdf"
}
```

#### `mineru_convert`

场景内 `pdf` / `epub` / `mobi` → `references/<stem>.md`. 需 MinerU 服务, 详见 [agent-api-pdf-to-markdown-guide.md](./agent-api-pdf-to-markdown-guide.md).

```json
{"path": "references/raw/suez_nsarchive.pdf"}
{"path": "references/raw/frus.epub", "output_path": "references/frus.md"}
```

---

### 计划清单(todo)

多步任务(≥3 文件或完整设计流程)时用; 单步小改可跳过.

#### `edit_todo`

全量替换计划清单(非增量). 每行 `[ ]` 未完成 / `[x]` 完成.

```json
{
  "todo": "[ ] 检索苏伊士危机资料\n[ ] 写 background.md\n[ ] 编写 venues.yaml"
}
```

#### `check_todo`

无参数; 读当前对话最新 todo.

```json
{}
```

---

## 从零设计场景的工作流(Agent 纪律)

与 `munagent/designer/prompt.py` 一致, 简表如下:

| 步 | 动作 | 常用工具 |
|----|------|----------|
| 1 | 确认主题与切入时间 | (对话) |
| 2 | 检索并整理资料 | `search_wikipedia` → `web_search` & `fetch_page` → `search_web_pdf` → `download_file` & `mineru_convert` |
| 3 | 通读 references | `read_file`, `list_files` |
| 4 | 划分会场 | `write_file` venues.yaml |
| 5 | 写 background | `write_file` background.md |
| 6 | 席位 / 弧线 / manifest | `write_file` + `read_file` 联动 |

多步时先 `edit_todo` 列计划; **每完成 write_file 须立即 `edit_todo` 勾掉对应行**. L 段每步注入最新 todo 全文.

---

## 限制与陷阱

| 项 | 说明 |
|----|------|
| 工具调用上限 | 每任务 ≤ 50 次 |
| 路径 | 不得写 `references/` 以外二进制; 不得 `..` 逃逸 |
| `tool_call` 摘要 | ≤200 字; 大正文在文件里, 用 `read_file` |
| PDF 403 | 换搜索结果中下一条 URL |
| Wiki 429 | 降低 `max_results`, 稍候重试 |
| 史实 | 不许编造; 推断须标注 |

---

## 相关文档

| 文档 | 内容 |
|------|------|
| [docs/api/designer/tools.md](../api/designer/tools.md) | 代码接口地图 |
| [how-to-find-pdf.md](./how-to-find-pdf.md) | 人类向档案站清单 + PDF 搜索技巧 |
| [agent-api-pdf-to-markdown-guide.md](./agent-api-pdf-to-markdown-guide.md) | MinerU HTTP API |
| [search-archive-pdf.md](./search-archive-pdf.md) | 档案站定向搜设计(暂缓实现) |
