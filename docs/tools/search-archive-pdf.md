# 档案站 PDF 搜索工具设计 (`search_archive_pdf`)

> 面向设计 Agent 的工具规格. 人类向站点清单见 [how-to-find-pdf.md](./how-to-find-pdf.md).
>
> **实现本工具的首要任务**: 先逐站研究「如何在这些网站上搜索」以及「如何得到可直接下载的 PDF URL」——各站机制差异大, 没有统一 API 可抄; 适配器与返回字段必须在调研清楚后再定稿, 不可先写壳再猜.

## 1. 背景与定位

设计 Agent 在撰写历史委/危机委场景时, 需要一手外交与政治档案 PDF. 现有工具链:

```
web_search(泛网) → fetch_page / download_file → mineru_convert
```

泛网检索噪声大, 且难保证来源权威性. [how-to-find-pdf.md](./how-to-find-pdf.md) 已整理一批**免注册(或仅需免费账号)、高权威、多数可直接下 PDF** 的档案站.

本工具 `search_archive_pdf` 在这些**已知站点**内做定向检索, 把**前几名**候选的 **PDF 直链 URL** 返回给 Agent; Agent 再按需 `download_file` → `mineru_convert`.

与 `web_search` 的分工:

| 维度 | `web_search` | `search_archive_pdf` |
|------|--------------|----------------------|
| 范围 | 全网 | 预置档案站白名单 |
| 输出 | 标题/摘要/网页 URL | 标题/元数据/**PDF 直链**/来源站 |
| 决策者 | Agent 写查询 | Agent **选站点子集** + 写查询 |
| 典型用途 | 背景科普、新闻、百科 | 联合国决议、FRUS 卷宗、解密电报等一手文献 |

## 2. Agent 侧契约

### 2.1 Agent 已知信息

系统 prompt(或工具描述附带的站点表)提供 [how-to-find-pdf.md](./how-to-find-pdf.md) 中的站点清单及 `source_id`. Agent **自行决定**本次从哪些站搜(不必每次全选).

### 2.2 工具参数(草案)

```json
{
  "name": "search_archive_pdf",
  "description": "在权威历史档案站(联合国数字图书馆、FRUS、威尔逊中心等)内搜索可下载 PDF, 返回直链 URL 列表供后续 download_file 使用. Agent 根据主题选择 sources 子集.",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "检索关键词, 建议英文并含事件名/年份/机构"
      },
      "sources": {
        "type": "array",
        "items": {
          "type": "string",
          "enum": [
            "un_digitallibrary",
            "frus",
            "wilson_center",
            "avalon",
            "internet_archive",
            "hathitrust"
          ]
        },
        "description": "要搜索的档案站 ID 列表, 由 Agent 按主题选取"
      },
      "max_results": {
        "type": "integer",
        "description": "每个来源站最多返回几条(默认 5); 合并后按相关度排序再截断",
        "default": 5
      }
    },
    "required": ["query", "sources"]
  }
}
```

### 2.3 返回结构(草案)

`ToolResult.data`:

```json
{
  "query": "cuba missile crisis",
  "results": [
    {
      "rank": 1,
      "source": "frus",
      "source_label": "Foreign Relations of the United States",
      "title": "Foreign Relations, 1961–1963, Volumes X/XI/XII, Microfiche Supplement, ... Cuban Missile Crisis and Aftermath",
      "pdf_url": "https://static.history.state.gov/frus/frus1961-63v10-12mSupp/pdf/frus1961-63v10-12mSupp.pdf",
      "landing_url": "frus1961-63v10-12mSupp",
      "published_date": null,
      "relevance_hint": "catalog/all 标题 AND 匹配",
      "registration_required": false,
      "notes": "主卷 frus1961-63v11 无 PDF, 仅 supplement 有"
    }
  ],
  "per_source": {
    "frus": { "ok": true, "count": 3 },
    "wilson_center": { "ok": true, "count": 2 },
    "avalon": { "ok": false, "error": "无原生 PDF 直链, 仅 HTML 页面" }
  },
  "errors": []
}
```

字段约束:

- `pdf_url` **必须是** `download_file` 可直接 GET 的直链(或经一次 302 即到 PDF); 拿不到直链则该条不入 `results`, 记入 `per_source` 说明;
- `summary`(写入 chat `tool_call`) ≤200 字, 例: `frus×3, wilson×2; 首推 FRUS 1955-57 v17 PDF`;
- 大体积正文不进 `tool_call`, 只返 URL 列表.

### 2.4 推荐工作流

```
1. Agent 读用户主题 → 从站点表选 sources(如冷战: frus + wilson_center + un_digitallibrary)
2. search_archive_pdf(query, sources, max_results)
3. 审阅 results → 选 1~N 条 pdf_url
4. download_file(url, dest=references/raw/...)
5. mineru_convert(pdf_path) → references/*.md
```

## 3. 站点注册表

与 [how-to-find-pdf.md](./how-to-find-pdf.md) 一一对应. `pdf_mode` 标注直链可行性(调研后可能调整).

| `source_id` | 名称 | 注册 | `pdf_mode` | 调研状态 |
|-------------|------|------|------------|----------|
| `un_digitallibrary` | UN Digital Library | 否 | `direct` | 待实测 |
| `frus` | FRUS (history.state.gov) | 否 | `direct`(仅部分卷) | **探针已验证** — 见 §4.2 |
| `wilson_center` | Wilson Center Digital Archive | 否 | `direct` | 待实测(原 API 已关闭) |
| `avalon` | Yale Avalon Project | 否 | `indirect` | 仅 HTML, 无官方 PDF |
| `internet_archive` | Internet Archive | 否 | `direct` | **探针已验证** — 见 §4.5 |
| `hathitrust` | HathiTrust | 常需登录/反爬 | `assembled` | 无整卷 PDF, 仅逐页拼装 |

`pdf_mode` 含义:

- `direct`: 单 URL 即 PDF 文件;
- `indirect`: 只有网页, 需「打印为 PDF」或走 `fetch_page` 读 HTML, **本工具默认不返回**;
- `assembled`: 需按页下载再合并, **v1 不纳入** `results`(可仅返回书目 landing_url 供 Agent 知晓).

## 4. 各站调研笔记(首要任务产出)

> 以下为实现前必须补齐/验证的内容. **§4.0** 记录已完成的 FRUS / Internet Archive 探针实验(脚本在 `scripts/probe_archive_search/`, 原始 JSON 落盘 `out/probe_archive_search/`).

### 4.0 探针实验记录(2026-07-13)

**脚本**:

| 文件 | 用途 |
|------|------|
| `scripts/probe_archive_search/probe_frus.py` | FRUS OPDS 搜索 + catalog/all 回退 |
| `scripts/probe_archive_search/probe_internet_archive.py` | IA Advanced Search + metadata 二次请求 |
| `scripts/probe_archive_search/run_probes.py` | 批量跑两组 query 并写 `out/probe_archive_search/summary.json` |
| `scripts/probe_archive_search/probe_google_filetype_pdf.py` | `web_search` 等价: 查询加 `filetype:pdf`(+`site:`) → 过滤 `.pdf` URL → HEAD 验证 |
| `scripts/probe_archive_search/_common.py` | HEAD/Range 验证 `application/pdf` |

**测试 query**: `Suez Crisis 1956`, `cuba missile crisis`(各 `max_results=3`).

**汇总结论**:

| 来源 | 抓取是否跑通 | PDF 直链验证 | 关键发现 |
|------|-------------|-------------|----------|
| `frus` | 是(需回退策略) | `cuba missile crisis` **1/1 OK**; `Suez Crisis 1956` **0 条**(该专题卷无 PDF 版) | OPDS `/search?q=` **不返回卷宗**, 仅导航 tag; 实用路径是 `/catalog/all`(551 卷) + 标题过滤 + 取 `application/pdf` 链接 |
| `internet_archive` | 是 | Suez **2/3 OK**; Cuba **3/3 OK** | 搜索→metadata 两跳可行; `archive.org/download/{id}/{file}` 会 302 到 `*.archive.org`, 仍可用; 部分条目 403/500 需 HEAD 过滤 |
| `google_filetype_pdf` | 是(tavily/serper) | `Suez… site:un.org` **5/5 OK**; `cuba… site:history.state.gov` **0 条** | 查询自动追加 `filetype:pdf`; 返回 URL 须 `.pdf` 后缀; 可 HEAD 验证直链 |

**MinerU epub/mobi(2026-07-13)**: 网关支持 epub/mobi 上传→转 PDF→Markdown; FRUS 苏伊士卷 mobi/epub 实测 ~7min, 产出 400 万+ 字符. `mineru_convert` 已扩展支持三种格式.

---
### 4.1 `un_digitallibrary` — UN Digital Library

**目标**: 安理会记录、决议、会议文件等 PDF.

**已知线索**:

- 搜索入口: `https://digitallibrary.un.org/search` (GET, 可嵌第三方搜索框, 见 UN 研究指南);
- 高级搜索支持按 `Formats: PDF` 筛选;
- 若已知**文件代号**(document symbol), 可走 UNDOCS 直链, 无需先搜索:
  - `https://docs.un.org/en/{symbol}?direct=true` (语言码: en/zh/fr/ru/es/ar);
  - 例: `https://docs.un.org/en/S/RES/242(1967)?direct=true`;
- 搜索列表页 → 详情页 → 下载按钮; 需从 HTML/JSON 抽 PDF href.

**待实测**:

- [ ] 搜索 URL 参数规范(关键词、format 过滤、分页);
- [ ] 列表项是否含稳定 PDF 直链, 还是仅详情页链接;
- [ ] 反爬/403 策略(需 User-Agent、限速);
- [ ] `query` 含 symbol 时是否可短路走 UNDOCS.

### 4.2 `frus` — Foreign Relations of the United States

**目标**: 美国外交史料整卷 PDF.

**探针结论(2026-07-13, 已验证)**:

- OPDS 根目录: `GET https://history.state.gov/api/v1/catalog` → 导航 feed(All Volumes / Recently Published / Browse By Keywords).
- **`GET /api/v1/catalog/search?q={query}` 不能用于卷宗检索**: 返回的是关键词**导航节点**(`rel=subsection`), 不是带 PDF 的 `entry`. 例: `q=suez` 仅返回 tag `suez-canal` 的子目录链接.
- **实用全量目录**: `GET https://history.state.gov/api/v1/catalog/all` → **551** 条卷宗 `entry`.
- 每条卷宗 acquisition 链接统计: `epub` 551、`mobi` 551、**`application/pdf` 仅 103**. 多数卷(含苏伊士危机卷 `frus1955-57v16`)**只有 epub/mobi, 无 PDF**.
- PDF 链接形态(存在时): `https://static.history.state.gov/frus/{slug}/pdf/{slug}.pdf` — 与 `/ebook/*.epub` 并列, **不能**假设 `{slug}/ebook/{slug}.pdf` 存在.
- 标题过滤 + PDF 抽取可跑通. 实测 `cuba missile crisis` 命中 Microfiche Supplement, HEAD **200 application/pdf** (~10MB):
  - `https://static.history.state.gov/frus/frus1961-63v10-12mSupp/pdf/frus1961-63v10-12mSupp.pdf`
- 实测 `Suez Crisis 1956`: 标题可匹配到 «Suez Crisis, July 26–December 31, 1956, Volume XVI», 但该卷**无 PDF acquisition 链接**, 探针正确返回 0 候选(非抓取失败).

**待实测(剩余)**:

- [x] 空结果 vs 有结果时 feed 结构 — search 为导航/空 entry; 卷宗在 `/catalog/all`
- [x] 相关性排序 — search 无效; 需在 551 卷上按 query 词在标题中 AND 匹配, 可按卷名年份/专题词排序
- [x] PDF `href` 直链 — 抽样验证 1 条 200 OK; 无 PDF 的卷 HEAD 为 403

**适配器结论(修订)**:

1. **不要**依赖 `/catalog/search?q=` 作为唯一搜索路径.
2. 拉取 `/catalog/all`(可内存缓存, 551 条体量可接受) → 按 query 词过滤 `entry/title` → 取 `link[@rel=opds-spec.org/acquisition][@type=application/pdf]`.
3. 无 PDF 链接的匹配卷**跳过**(不要猜 URL); 可提示 Agent 改下 **epub/mobi** + `mineru_convert`(网关已支持, 整卷约 7min).
4. 可选增强: OPDS `browse?tag=` 关键词树 + 站内 HTML 搜索作为补充(非 v1 必须).

### 4.3 `wilson_center` — Wilson Center Digital Archive

**目标**: 冷战解密档案(含中俄苏东欧材料).

**已知线索**:

- 搜索: `https://digitalarchive.wilsoncenter.org/search?search_api_fulltext={query}`;
- 文档页: `https://digitalarchive.wilsoncenter.org/document/{id}`;
- 历史上存在 `*.json` 元数据端点与非官方 Python 客户端, **Wilson Center 已关闭 API 访问**;
- 页面右上角 PDF 图标 → 直链(需在真实文档页抓取).

**待实测**:

- [ ] 搜索结果 HTML 结构(Drupal `search_api`);
- [ ] 文档页 PDF 链接 DOM/CSS 选择器或嵌入 JSON;
- [ ] 是否有翻译件/原件两个 PDF;
- [ ] 请求频率限制.

**适配器草案**: HTML 解析(httpx + 选择器) 或 探测是否仍有隐藏 JSON 端点.

### 4.7 `google_filetype_pdf` — 泛网 PDF 直链(经搜索 API)

**目标**: 在指定站点或全网用 Google 语法 `filetype:pdf` 找 PDF 直链, 作为档案站定向搜的补充.

**探针**: `scripts/probe_archive_search/probe_google_filetype_pdf.py` — 复用 `tools.search`(推荐 `serper`) 发查询, 丢弃非 `.pdf` URL, HEAD 验证.

**查询构造**:

```
{topic} filetype:pdf site:{domain}   # 例: Suez Crisis 1956 report filetype:pdf site:un.org
```

**适配器结论(v1 草案)**: 可并入 `web_search` 使用纪律(由 prompt 要求 Agent 自带 `filetype:pdf`), 或独立为 `search_web_pdf` 工具自动追加语法并过滤结果. 探针结论见 §4.0.

**实测(2026-07-13)**: `Suez Crisis 1956 report filetype:pdf site:un.org` → 5 条 PDF URL 全部 HEAD 200; `cuba missile crisis … site:history.state.gov` → 0 条(该域 PDF 多不在搜索索引, 需站内/OPDS 路径).

### 4.4 `avalon` — Yale Avalon Project

**目标**: 条约、宣言、法律文本(近代—20 世纪初).

**已知线索**:

- 站点: `https://avalon.law.yale.edu/`, 按世纪/专题组织, **无公开搜索 API**;
- 内容为 HTML 页面, 用户侧「打印→另存为 PDF」;
- 无稳定 `*.pdf` 直链.

**结论(v1)**: 纳入 `sources` 枚举供 Agent 知晓, 但适配器**不产出** `pdf_url`; `per_source` 返回 `ok: false` + 说明, 引导 Agent 用 `fetch_page` 读 HTML.

**待实测**:

- [ ] 站内搜索(若有) URL 形态;
- [ ] 是否有个别子目录静态 PDF(边缘情况).

### 4.5 `internet_archive` — Internet Archive

**目标**: 绝版政府白皮书、老旧书刊.

**探针结论(2026-07-13, 已验证)**:

- Advanced Search(JSON) 一步搜索可用:
  ```
  GET https://archive.org/advancedsearch.php
    ?q={query}+AND+mediatype:texts+AND+format:Text+PDF
    &fl[]=identifier,title
    &rows={n}&output=json
  ```
  实测 `Suez Crisis 1956` → `numFound=418`; `cuba missile crisis` → `numFound=828`.
- **必须二次请求 metadata**: `GET https://archive.org/metadata/{identifier}` → 从 `files[]` 选 PDF 文件名.
- **选文件启发式(探针采用)**: 优先 `format=="Text PDF"`, 其次 `format=="PDF"`, 同优先级取 `size` 最大. 实测 Cuba 结果多为 `*_text.pdf`.
- **直链拼法**: `https://archive.org/download/{identifier}/{filename}` — 符合永久链接规范; GET/HEAD 会 **302** 到 `dn*.ca.archive.org` / `ia*.us.archive.org`, 验证时须 `follow_redirects=True`.
- **直链验证**: Cuba 3/3 为 `200 application/pdf`; Suez 3 条中 2 条 OK, 1 条 `500`(大部头百科全书, 非档案类噪声).
- 相关性: 纯关键词搜索会混入无关大部头书; 建议 Agent query 加机构/事件词, 或实现侧优先 `collection:*` 过滤(待后续试验).

**待实测(剩余)**:

- [x] 从 search 到 pick 最佳 PDF 文件名的启发式 — Text PDF 优先 + 最大 size
- [x] `format:Text PDF` 与 `format:PDF` 差异 — 均有 PDF; Text PDF 更常见; 另有 `Image Container PDF`(CIA 扫描件)
- [x] 超时与 rows 上限 — 单次 search+3×metadata ~数秒; 探针 timeout 60s 足够
- [ ] 借阅/受限条目预判(403/500) — 需 HEAD 过滤; 是否可从 metadata 字段提前排除(未测)

**适配器结论(修订)**: search → metadata → 选 PDF → 拼 `download` URL → **可选 HEAD 验证**剔除 403/500 → 返回. 不要直接把 `iaNNN.*.archive.org` 临时重定向 URL 作为 `pdf_url` 存储(应存 `archive.org/download/...` 规范形式).

### 4.6 `hathitrust` — HathiTrust

**目标**: 绝版书籍扫描件.

**已知线索**:

- 书目检索有 Bibliographic API; **整卷 PDF 无单 URL**;
- Data API 按页返回 `pageimage`/`pageocr`, 需本地拼 PDF;
- 近年大量内容需机构/Friend 账号 + Cookie, Cloudflare 403 常见.

**结论(v1)**: **不返回** `pdf_url`. 可选: 仅返回 `landing_url`(书目页) + `notes` 提示需人工或后续专用下载器; 默认建议 Agent 不选此源除非明确要绝版书.

**待实测**:

- [ ] 2026 年公开域卷是否仍有免登录 PDF 入口;
- [ ] 书目 API 是否足以支撑「只找链接」场景.

## 5. 实现架构(代码阶段, 本文仅规格)

```
munagent/designer/tools/archive_search/
  __init__.py          # search_archive_pdf 入口
  registry.py          # source_id → adapter
  types.py             # Pydantic: 参数/单条结果/汇总
  adapters/
    frus.py
    internet_archive.py
    un_digitallibrary.py
    wilson_center.py
    avalon.py            # 仅报错/说明
    hathitrust.py        # v1 跳过或仅 landing
```

原则:

- 各 adapter **只负责**「搜索 + 解析 PDF 直链」, 不下载文件;
- 并行 `asyncio.gather` 查询多站, 单站失败不拖垮全局;
- 统一超时/限速(配置项 `tools.archive_search.*`);
- 不引入新重依赖; HTML 解析优先标准库 + 已有 `httpx`;
- 单元测试: 各 adapter 用**录制的 HTTP fixture**, 禁止测试打真实外网.

注册: 成为设计 Agent 第 10 个工具, 同步 [docs/api/designer/tools.md](../api/designer/tools.md) 与 [design/designer/03-agent-interaction.md](../../design/designer/03-agent-interaction.md) §7.4.

## 6. 与 prompt 的衔接

在 `munagent/designer/prompt.py` 工作流第 2 步补充:

```
检索并下载相关资料(
  优先 search_archive_pdf(按主题选档案站)
  → 不足时再 web_search
  → download_file
  → PDF 用 mineru_convert 转 Markdown
), 整理进 references/
```

站点清单摘要可嵌入 `S` 段或工具 `description`, 不必每次让 Agent 读 markdown 文件.

## 7. 验收标准

1. **调研**: §4 每个 `待实测` 项有脚本探针记录(可放 `scripts/probe_archive_search/`) 与结论 — **FRUS / Internet Archive 已完成(§4.0)**
2. **功能**: 对固定 query fixture, `frus` + `internet_archive` 至少各返回 ≥1 条可 `curl -I` 为 `application/pdf` 的 URL — **探针已通过**(`cuba missile crisis` 两源均有 OK 直链; `Suez Crisis 1956` 仅 IA 有 OK 直链, FRUS 该专题无 PDF 版属数据现实)
3. **Agent 链**: `search_archive_pdf` → `download_file` → `mineru_convert` 在 `scripts/verify_designer_tools.py` 可跑通(真实联网, 可选);
4. **失败语义**: 某站超时/无 PDF 时 `per_source` 有明确错误, 其他站结果仍返回;
5. **文档**: 本文件、how-to-find-pdf 链接、api 文档、plan 勾选同步.

## 8. 风险与边界

| 风险 | 缓解 |
|------|------|
| 站点改版/HTML 脆 | 每 adapter 独立 + fixture 测试; 失败降级到 `web_search`+`site:` 语法 |
| 反爬/403 | 可配置 User-Agent、请求间隔; 不绕过登录/付费墙 |
| 「PDF」非扫描原件 | `notes` 标注卷宗/译本; Agent 自行判断 |
| Avalon/HathiTrust 无直链 | 枚举保留但 `pdf_mode` 明示, 避免 Agent 空等 |
| 与 D17/密钥 | 工具不需 API key(除可选代理); URL 可进 tool_call 摘要 |

---

*文档版本: 2026-07-13. §4.0/§4.2/§4.5 已纳入 FRUS 与 Internet Archive 探针结论. 实现 adapter 时以本节为准.*
