# DeerFlow 文件上传 REST API 调用流程

本文档描述通过 DeerFlow REST API 上传文件到 Thread 的完整流程。文件会被存储在 Thread 隔离目录下，Agent 可通过虚拟路径访问。

**Base URL**: `http://localhost:2026`

---

## 1. 上传相关 API 端点总览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/threads/{thread_id}/uploads` | 上传文件（支持多文件） |
| GET | `/api/threads/{thread_id}/uploads/list` | 列出已上传文件 |
| GET | `/api/threads/{thread_id}/uploads/limits` | 获取上传限制配置 |
| DELETE | `/api/threads/{thread_id}/uploads/{filename}` | 删除指定文件 |
| GET | `/api/threads/{thread_id}/artifacts/{path}` | 获取文件内容（Artifact） |

---

## 2. 上传限制

### 获取上传限制配置

```http
GET /api/threads/{thread_id}/uploads/limits
```

**响应：**
```json
{
  "max_files": 10,
  "max_file_size": 52428800,
  "max_total_size": 104857600
}
```

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `max_files` | 单次请求最大文件数 | 10 |
| `max_file_size` | 单文件最大大小（字节） | 50 MB |
| `max_total_size` | 单次请求总大小上限（字节） | 100 MB |

> 上传限制可通过 `config.yaml` 中的 `uploads.max_files`、`uploads.max_file_size`、`uploads.max_total_size` 配置。

---

## 3. 上传文件流程

### Step 1: 确保 Thread 已存在

```http
POST /api/threads
Content-Type: application/json

{"metadata": {}}
```

**响应：**
```json
{
  "thread_id": "abc123",
  "created_at": "2024-01-15T10:30:00Z",
  "metadata": {}
}
```

### Step 2: 上传文件

```http
POST /api/threads/{thread_id}/uploads
Content-Type: multipart/form-data

files: @document.pdf
files: @data.xlsx
files: @report.docx
```

**Python requests 示例：**
```python
import requests

url = "http://localhost:2026/api/threads/{thread_id}/uploads"
files = {
    "files": (
        "document.pdf", 
        open("document.pdf", "rb"), 
        "application/pdf"
    ),
    "files": (
        "data.xlsx", 
        open("data.xlsx", "rb"), 
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
}
response = requests.post(url, files=files)
print(response.json())
```

**响应：**
```json
{
  "success": true,
  "files": [
    {
      "filename": "document.pdf",
      "size": 1234567,
      "path": ".deer-flow/threads/abc123/user-data/uploads/document.pdf",
      "virtual_path": "/mnt/user-data/uploads/document.pdf",
      "artifact_url": "/api/threads/abc123/artifacts/mnt/user-data/uploads/document.pdf",
      "markdown_file": "document.md",
      "markdown_path": ".deer-flow/threads/abc123/user-data/uploads/document.md",
      "markdown_virtual_path": "/mnt/user-data/uploads/document.md",
      "markdown_artifact_url": "/api/threads/abc123/artifacts/mnt/user-data/uploads/document.md"
    },
    {
      "filename": "data.xlsx",
      "size": 98765,
      "path": ".deer-flow/threads/abc123/user-data/uploads/data.xlsx",
      "virtual_path": "/mnt/user-data/uploads/data.xlsx",
      "artifact_url": "/api/threads/abc123/artifacts/mnt/user-data/uploads/data.xlsx",
      "markdown_file": "data.md",
      "markdown_path": ".deer-flow/threads/abc123/user-data/uploads/data.md",
      "markdown_virtual_path": "/mnt/user-data/uploads/data.md",
      "markdown_artifact_url": "/api/threads/abc123/artifacts/mnt/user-data/uploads/data.md"
    }
  ],
  "message": "Successfully uploaded 2 file(s)"
}
```

### Step 3: 文件如何传递给 Agent

`UploadsMiddleware` 会自动将上传文件信息注入到 Agent 上下文中：

```xml
<uploaded_files>
  - document.pdf (1.2 MB)
    Path: /mnt/user-data/uploads/document.pdf
    Document outline (use `read_file` with line ranges to read sections):
      L1: Introduction
      L15: Chapter 1: Background
      L42: Chapter 2: Analysis
  - data.xlsx (96.5 KB)
    Path: /mnt/user-data/uploads/data.xlsx
    Document outline (use `read_file` with line ranges to read sections):
      L1: Sheet1 - Summary
      L20: Sheet2 - Details
</uploaded_files>
```

---

## 4. 支持的文件格式

### 可直接上传的文件

所有文件类型均可直接上传，Agent 可通过 `read_file` 工具读取内容。

### 支持自动转换的文件（PDF/PPT/Excel/Word → Markdown）

| 格式 | 扩展名 | 转换后格式 |
|------|--------|-----------|
| PDF | `.pdf` | `.md` |
| PowerPoint | `.ppt`, `.pptx` | `.md` |
| Excel | `.xls`, `.xlsx` | `.md` |
| Word | `.doc`, `.docx` | `.md` |

> 自动转换默认**关闭**，需在 `config.yaml` 中设置 `uploads.auto_convert_documents: true` 启用。

---

## 5. 文件名重复处理

同一请求中如果出现重名文件，系统会自动重命名：

| 上传顺序 | 原文件名 | 实际保存文件名 | 说明 |
|----------|----------|---------------|------|
| 1 | `data.xlsx` | `data.xlsx` | 保持原名 |
| 2 | `data.xlsx` | `data_1.xlsx` | 添加 `_1` 后缀 |
| 3 | `data.xlsx` | `data_2.xlsx` | 添加 `_2` 后缀 |

> 如果上传的文件名与 Thread 中已有文件重名，已存在的文件不会被覆盖，而是同样进行自动重命名。

---

## 6. 文件存储路径

### 物理路径（宿主机）

```
backend/.deer-flow/
├── threads/
│   └── {thread_id}/
│       └── user-data/
│           ├── uploads/          # 上传的文件
│           │   ├── document.pdf
│           │   └── document.md   # PDF 转换后的 Markdown
│           ├── workspace/        # Agent 工作区
│           └── outputs/          # Agent 生成的输出文件
```

### 虚拟路径（Agent 可见）

| 类型 | 虚拟路径 |
|------|----------|
| 上传目录 | `/mnt/user-data/uploads/` |
| 工作区 | `/mnt/user-data/workspace/` |
| 输出目录 | `/mnt/user-data/outputs/` |

---

## 7. Artifact 访问

上传的文件和转换后的 Markdown 都可通过 Artifact 端点访问。

### 获取文件内容

```http
GET /api/threads/{thread_id}/artifacts/mnt/user-data/uploads/document.pdf
```

**查询参数：**
- `download=true` — 强制下载而非浏览器内联显示

### 不同文件的处理策略

| 文件类型 | 处理方式 |
|----------|----------|
| HTML / XHTML / SVG | **始终下载**（防止 XSS） |
| 文本文件（.txt, .md, .json 等） | 内联显示 |
| 二进制文件（.pdf, .xlsx 等） | 浏览器默认行为 |
| `.skill` 压缩包内的文件 | 提取并返回内容 |

**响应示例（文本文件）：**
```
HTTP/1.1 200 OK
Content-Type: text/plain; charset=utf-8

# Document Title

This is the content of the document...
```

---

## 8. 列出与删除

### 列出已上传文件

```http
GET /api/threads/{thread_id}/uploads/list
```

**响应：**
```json
{
  "files": [
    {
      "filename": "document.pdf",
      "size": 1234567,
      "path": ".deer-flow/threads/abc123/user-data/uploads/document.pdf",
      "virtual_path": "/mnt/user-data/uploads/document.pdf",
      "artifact_url": "/api/threads/abc123/artifacts/mnt/user-data/uploads/document.pdf",
      "extension": ".pdf",
      "modified": 1705997600.0
    }
  ],
  "count": 1
}
```

### 删除指定文件

```http
DELETE /api/threads/{thread_id}/uploads/{filename}
```

**响应：**
```json
{
  "success": true,
  "message": "Deleted document.pdf"
}
```

> 删除操作会同时删除原始文件和对应的 Markdown 转换文件（如果存在）。

---

## 9. 完整调用序列

```
Client              Nginx              Gateway API         File System
  │                   │                    │                   │
  │                   │                    │                   │
  ├─── POST /api/threads ─────────────────►│                   │
  │◄── {thread_id} ───────────────────────│                   │
  │                   │                    │                   │
  ├─── POST /api/threads/{id}/uploads ────►│                   │
  │                   │─── write file ────►│─── uploads/ ─────►│
  │                   │                    │                   │
  │                   │─── auto-convert ───►│                   │
  │                   │   (if enabled)      │                   │
  │                   │                    │                   │
  │◄── {success, files} ───────────────────│                   │
  │                   │                    │                   │
  ├─── GET /api/threads/{id}/uploads/list ───────────────────►│
  │◄── {files: [...]} ──────────────────────────────────────│
  │                   │                    │                   │
  ├─── GET /api/threads/{id}/artifacts/ ──────────────────────►│
  │◄─── file content ─────────────────────────────────────────│
```

---

## 10. cURL 快速测试

```bash
# 创建 Thread
curl -X POST http://localhost:2026/api/threads \
  -H "Content-Type: application/json" \
  -d '{}'
# 返回: {"thread_id": "abc123", ...}

# 上传文件
curl -X POST http://localhost:2026/api/threads/abc123/uploads \
  -F "files=@/path/to/document.pdf"

# 列出已上传文件
curl http://localhost:2026/api/threads/abc123/uploads/list

# 访问上传的文件
curl http://localhost:2026/api/threads/abc123/artifacts/mnt/user-data/uploads/document.pdf

# 下载文件（强制下载）
curl -o downloaded.pdf \
  "http://localhost:2026/api/threads/abc123/artifacts/mnt/user-data/uploads/document.pdf?download=true"

# 删除文件
curl -X DELETE http://localhost:2026/api/threads/abc123/uploads/document.pdf

# 获取上传限制
curl http://localhost:2026/api/threads/abc123/uploads/limits
```

---

## 11. Python SDK 示例

```python
from deerflow import DeerFlowClient

client = DeerFlowClient()

# 创建 Thread
thread = client.create_thread()
thread_id = thread["thread_id"]

# 上传文件
result = client.upload_files(thread_id, [
    "/path/to/document.pdf",
    "/path/to/data.xlsx"
])

print(result)
# {
#   "success": True,
#   "files": [
#     {
#       "filename": "document.pdf",
#       "virtual_path": "/mnt/user-data/uploads/document.pdf",
#       "markdown_virtual_path": "/mnt/user-data/uploads/document.md",
#       ...
#     },
#     ...
#   ],
#   "message": "Successfully uploaded 2 file(s)"
# }

# 列出文件
files = client.list_uploads(thread_id)
print(files["files"])

# 获取 Artifact 内容
content, mime_type = client.get_artifact(
    thread_id, 
    "mnt/user-data/uploads/document.pdf"
)
```

---

## 12. 错误处理

| HTTP 状态码 | 错误信息 | 说明 |
|-------------|----------|------|
| 400 | `No files provided` | 未提供文件 |
| 400 | `Invalid thread ID` | Thread ID 格式错误 |
| 413 | `File too large: filename` | 单文件超出限制 |
| 413 | `Total upload size too large` | 总大小超出限制 |
| 413 | `Too many files: maximum is N` | 文件数量超出限制 |
| 404 | `Artifact not found: path` | 文件不存在 |
| 422 | Validation Error | 请求参数验证失败 |

**错误响应格式：**
```json
{
  "detail": "File too large: document.pdf"
}
```
