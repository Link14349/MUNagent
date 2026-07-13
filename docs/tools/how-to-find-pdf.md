准备模拟联合国（MUN）历史委员会（Historical Committee）或危机委（Crisis Committee）时，寻找**最真实、最权威的一手历史政治资料**至关重要。

> **设计 Agent 工具(已实现)**: `search_web_pdf` — Google 语法 `filetype:pdf` 搜 PDF 直链; `search_wikipedia` — 维基 API 摘要/正文 + 外链 PDF. 衔接 `download_file` → `mineru_convert`. 档案站定向搜(`search_archive_pdf`)暂缓, 见 [search-archive-pdf.md](./search-archive-pdf.md).
>
> **Agent 检索优先级**: ① `search_wikipedia`(自动写入 `references/wikipedia/*.md` 并找外链 PDF); ② `web_search` & `fetch_page`; ③ `search_web_pdf`; ④ `download_file` & `mineru_convert`(含 epub/mobi).

| 工具 `source_id` | 站点 | PDF 直链 | 无 PDF 时 |
|------------------|------|----------|-----------|
| `un_digitallibrary` | §1 UN Digital Library | 是(多数) | — |
| `frus` | §1 FRUS | **仅部分卷**(103/551) | epub/mobi → mineru_convert |
| `wilson_center` | §2 威尔逊中心 | 是 | — |
| `avalon` | §2 阿瓦隆项目 | 否(HTML) | fetch_page |
| `internet_archive` | §2 Internet Archive | 是 | — |
| `hathitrust` | §2 HathiTrust | 困难 | 暂跳过 |

---

## 🌍 全球外交与联合国历史官方档案

### 1. UN Digital Library (联合国数字图书馆)

* **最适合查找：** 联合国自 1945 年成立以来的历史决议、会议记录、投票结果。
* **下载体验：** 🔍 在右上角直接筛选“**Formats: PDF**”，所有解密的历史文件、安理会（UNSC）决议草案都可以直接免登录一键下载。
* **模联大招：** 查找历史委中当时各国的官方发言和投票立场（Meeting Records）。

### 2. Foreign Relations of the United States (FRUS - 美国对外关系档案)

* **网址/来源：** 美国国务院历史学家办公室 (Office of the Historian)
* **最适合查找：** **冷战、一战、二战等重大历史政治危机。** 里面包含了当年美国总统、国务卿与世界各国首脑的秘密电报、会议备忘录和情报分析。
* **下载体验：** 每一个历史时期和专题整理成完整电子书卷. **仅约 103/551 卷提供 PDF**; 其余卷仅有 epub/mobi, 可下载后经 MinerU 网关转为 Markdown(实测整卷约 7 分钟).

---

## 🏛️ 顶级智库、解密档案与多国政策库

### 3. Wilson Center Digital Archive (威尔逊中心数字档案)

* **最适合查找：** **冷战史、中苏关系、朝鲜战争、柏林墙危机等。**
* **下载体验：** 它的强悍之处在于收集了大量**前苏联、中国、东欧阵营**解密的外交秘密档案，并且被翻译成了英文。只要点击文件右上角的 PDF 图标即可直接下载。这是打历史委和危机委的“作弊神器”。

### 4. Yale Law School Avalon Project (耶鲁大学阿瓦隆项目)

* **最适合查找：** **古代、近代到 21 世纪初的所有重要国际条约、宣言和法律文本。**
* **下载体验：** 比如你想找 1648 年《威斯特伐利亚和约》、1919 年《凡尔赛条约》或者二战时期的《大西洋宪章》，这里全部有全文。网页端非常干净，可以直接在浏览器“打印 -> 另存为 PDF”。

### 5. Internet Archive (互联网档案馆) & HathiTrust

* **最适合查找：** 绝版的老旧历史书籍、二战前各国的政府白皮书、历史期刊。
* **下载体验：** 输入历史事件关键词，在左侧筛选“**Text**”。在进入书籍页面后，右侧通常有直接的 “**PDF**” 下载选项（完全免费）。

---

## 💡 模联历史委的高效搜索技巧

为了让你更快找到能直接下载 PDF 的资料，在 Google 搜索时请善用**高级搜索语法**（Agent 用 `search_web_pdf` 会自动追加 `filetype:pdf`）：

> 举个例子：你想找 1956 年苏伊士运河危机的联合国的官方报告
> 🔍 `search_web_pdf(query="Suez Crisis 1956 report")` 或手动: `Suez Crisis 1956 report filetype:pdf`
> 🔍 若只要联合国: 加 `site:un.org`(工具参数 `site`)

探针: `scripts/probe_archive_search/probe_google_filetype_pdf.py`

如果是针对冷战时期的某次秘密会议：

> 🔍 搜索：`"Suez Crisis" declassified telegram filetype:pdf`

直接用这套组合拳，基本上 5 分钟内就能把你的 Position Paper（立场文件）和 BG（背景资料）塞满一手文献。祝你代表在历史委大杀四方，拿到 Good Rep！