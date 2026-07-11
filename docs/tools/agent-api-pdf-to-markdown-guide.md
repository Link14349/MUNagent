# Agent 调用 MinerU HTTP API 指南

本文档面向**运行在本地电脑上的 Agent**，说明如何通过 HTTP 远程调用服务器上的 PDF → Markdown 转换服务。

## 前提

- 服务器上 MinerU 服务已启动（见 [server-operations.md](./server-operations.md)）
- 本地能访问服务器 `8282` 端口（内网或 VPN）
- 将下文中的 `<SERVER>` 替换为服务器实际地址，例如 `192.168.1.100` 或 `your-server.example.com`

**Base URL：** `http://<SERVER>:8282`

## Agent 典型工作流

```
用户给 Agent 一个 PDF
    ↓
Agent 调用 HTTP API 上传 PDF
    ↓
服务器 GPU 转换为 Markdown
    ↓
Agent 读取 md_content，基于文本回答用户
```

Agent **不需要**在本地安装 MinerU 或 GPU，只需能发 HTTP 请求。

## 接口一览

| 方法 | 路径 | 用途 |
|------|------|------|
| `GET` | `/health` | 检查服务是否在线 |
| `POST` | `/file_parse` | **同步**转换，适合小 PDF（< ~50 页） |
| `POST` | `/tasks` | **异步**提交任务，适合大 PDF / 整本书 |
| `GET` | `/tasks/{task_id}` | 查询任务状态 |
| `GET` | `/tasks/{task_id}/result` | 获取转换结果 |

完整参数说明见：`http://<SERVER>:8282/docs`

## 推荐参数

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| `backend` | `pipeline` | GPU OCR，稳定，适合扫描版 PDF |
| `parse_method` | `auto` | 自动判断文本提取或 OCR |
| `lang_list` | `ch` | OCR 语言（英文文档也用 `ch`） |
| `return_md` | `true` | 返回 Markdown 正文 |
| `return_images` | `false` | 通常不需要内嵌图片 |
| `return_middle_json` | `false` | 不需要中间 JSON 时关闭 |

## 方式一：同步转换（小 PDF）

适合论文、讲义等 < 50 页的文件。一次请求等待完成，响应中直接包含 Markdown。

### curl 示例

```bash
curl -X POST "http://<SERVER>:8282/file_parse" \
  -F "files=@paper.pdf" \
  -F "backend=pipeline" \
  -F "parse_method=auto" \
  -F "lang_list=ch" \
  -F "return_md=true" \
  -F "return_middle_json=false" \
  -F "return_images=false"
```

### 响应结构

```json
{
  "task_id": "abc-123-...",
  "status": "completed",
  "backend": "pipeline",
  "file_names": ["paper"],
  "results": {
    "paper": {
      "md_content": "# Title\n\n正文内容..."
    }
  }
}
```

**取 Markdown：** `results[<文件名不含扩展名>].md_content`

> 注意：HTTP 连接会一直保持到转换结束。大文件（如 400+ 页）可能耗时数分钟，客户端容易超时，请用异步模式。

## 方式二：异步转换（大 PDF，推荐）

适合整本书、长文档。提交后立即返回 `task_id`，Agent 轮询状态，完成后取结果。

### Step 1 — 提交任务

```bash
curl -X POST "http://<SERVER>:8282/tasks" \
  -F "files=@big_book.pdf" \
  -F "backend=pipeline" \
  -F "parse_method=auto" \
  -F "lang_list=ch" \
  -F "return_md=true"
```

响应（HTTP 202）：

```json
{
  "task_id": "5d25774a-fa0e-4a15-9551-469f7deb5a45",
  "status": "pending",
  "status_url": "http://<SERVER>:8282/tasks/5d25774a-...",
  "result_url": "http://<SERVER>:8282/tasks/5d25774a-.../result",
  "message": "Task submitted successfully"
}
```

### Step 2 — 轮询状态

每 3~5 秒请求一次：

```bash
curl "http://<SERVER>:8282/tasks/{task_id}"
```

| status | 含义 |
|--------|------|
| `pending` | 排队中 |
| `processing` | 转换中 |
| `completed` | 完成，可取结果 |
| `failed` | 失败，查看 `error` 字段 |

### Step 3 — 获取结果

```bash
curl "http://<SERVER>:8282/tasks/{task_id}/result"
```

响应结构与同步模式相同，`results.<文件名>.md_content` 即 Markdown。

## Python 工具函数（可直接嵌入 Agent）

```python
import time
import httpx

SERVER = "http://<SERVER>:8282"


def check_service() -> bool:
    """检查服务是否在线。"""
    try:
        r = httpx.get(f"{SERVER}/health", timeout=10)
        return r.status_code == 200 and r.json().get("status") == "healthy"
    except Exception:
        return False


def pdf_to_markdown(pdf_path: str, timeout: int = 7200) -> str:
    """
    上传 PDF，返回 Markdown 字符串。
    大文件自动走异步模式并轮询等待。
    """
    with open(pdf_path, "rb") as f:
        files = {"files": (pdf_path.rsplit("/", 1)[-1], f, "application/pdf")}
        data = {
            "backend": "pipeline",
            "parse_method": "auto",
            "lang_list": "ch",
            "return_md": "true",
            "return_middle_json": "false",
            "return_images": "false",
        }
        r = httpx.post(f"{SERVER}/tasks", files=files, data=data, timeout=60)
        r.raise_for_status()
        task = r.json()

    task_id = task["task_id"]
    status_url = f"{SERVER}/tasks/{task_id}"
    result_url = f"{SERVER}/tasks/{task_id}/result"

    while True:
        s = httpx.get(status_url, timeout=30).json()
        if s["status"] == "completed":
            break
        if s["status"] == "failed":
            raise RuntimeError(f"转换失败: {s.get('error')}")
        time.sleep(3)

    result = httpx.get(result_url, timeout=timeout).json()
    for _, doc in result.get("results", {}).items():
        if doc.get("md_content"):
            return doc["md_content"]
    raise RuntimeError("响应中未找到 md_content")


# Agent 使用示例
if __name__ == "__main__":
    if not check_service():
        raise SystemExit("MinerU 服务不可用")
    md = pdf_to_markdown("paper.pdf")
    print(md[:500])
```

依赖：`pip install httpx`

## 注册为 Agent Tool 的描述模板

给 LLM Agent 注册工具时，可用如下描述：

```json
{
  "name": "pdf_to_markdown",
  "description": "将 PDF 文件转换为 Markdown 文本，用于阅读扫描版 PDF、含公式/表格的学术文档。当用户需要理解 PDF 内容时，先调用此工具获取 markdown，再基于返回文本回答。",
  "parameters": {
    "type": "object",
    "properties": {
      "pdf_path": {
        "type": "string",
        "description": "本地 PDF 文件的绝对路径"
      }
    },
    "required": ["pdf_path"]
  }
}
```

工具实现内部调用 `pdf_to_markdown(pdf_path)` 即可。

## 并发与性能

| 场景 | 行为 |
|------|------|
| 1 个 Agent 转 1 本 PDF | 使用 1 块 GPU，约 1 页/秒（视内容复杂度） |
| 4 个 Agent 同时各转 1 本 PDF | 4 块 GPU 并行，互不影响 |
| 1 个 Agent 转 1 本 400 页书 | 仍用 1 块 GPU，耗时约 5~10 分钟 |

服务最大并发 **12** 个任务（4 卡 × 每卡 3）。超出会排队。

## 错误处理

| HTTP 状态码 | 含义 | Agent 处理建议 |
|-------------|------|----------------|
| 200 | 成功 | 解析 `results` |
| 202 | 任务未完成（轮询 result 时） | 继续等待 |
| 409 | 任务执行失败 | 读取 `error`，告知用户 |
| 503 | 服务不可用 / 无健康 worker | 稍后重试或通知用户 |
| 连接超时 | 网络问题或文件过大 | 改用异步模式，增大 timeout |

## 健康检查

Agent 在转换前可先检查服务：

```bash
curl -s http://<SERVER>:8282/health
```

返回 `"status": "healthy"` 且 `servers` 中有 4 个 `local-gpu-*` 即可使用。

## 安全提醒

- API 当前**无鉴权**，请通过内网或 VPN 访问
- 不要将 8282 端口裸露在公网
- 如需公网访问，建议在 Nginx 后加 API Key 校验
