# 文件上传功能

## 概述

DeerFlow 后端提供了完整的文件上传功能，支持多文件上传，并自动将 Office 文档和 PDF 转换为 Markdown 格式。

## 功能特性

- ✅ 支持多文件同时上传
- ✅ 自动转换文档为 Markdown（PDF、PPT、Excel、Word）
- ✅ 文件存储在线程隔离的目录中
- ✅ Agent 自动感知已上传的文件
- ✅ 支持文件列表查询和删除

## API 端点

### 1. 上传文件
```
POST /api/threads/{thread_id}/uploads
```

**请求体：** `multipart/form-data`
- `files`: 一个或多个文件

**响应：**
```json
{
  "success": true,
  "files": [
    {
      "filename": "document.pdf",
      "size": 1234567,
      "path": ".deer-flow/threads/{thread_id}/user-data/uploads/document.pdf",
      "virtual_path": "/mnt/user-data/uploads/document.pdf",
      "artifact_url": "/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/document.pdf",
      "markdown_file": "document.md",
      "markdown_path": ".deer-flow/threads/{thread_id}/user-data/uploads/document.md",
      "markdown_virtual_path": "/mnt/user-data/uploads/document.md",
      "markdown_artifact_url": "/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/document.md"
    }
  ],
  "message": "Successfully uploaded 1 file(s)"
}
```

**路径说明：**
- `path`: 实际文件系统路径（相对于 `backend/` 目录）
- `virtual_path`: Agent 在沙箱中使用的虚拟路径
- `artifact_url`: 前端通过 HTTP 访问文件的 URL

### 2. 列出已上传文件
```
GET /api/threads/{thread_id}/uploads/list
```

**响应：**
```json
{
  "files": [
    {
      "filename": "document.pdf",
      "size": 1234567,
      "path": ".deer-flow/threads/{thread_id}/user-data/uploads/document.pdf",
      "virtual_path": "/mnt/user-data/uploads/document.pdf",
      "artifact_url": "/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/document.pdf",
      "extension": ".pdf",
      "modified": 1705997600.0
    }
  ],
  "count": 1
}
```

### 3. 删除文件
```
DELETE /api/threads/{thread_id}/uploads/{filename}
```

**响应：**
```json
{
  "success": true,
  "message": "Deleted document.pdf"
}
```

## 支持的文档格式

以下格式会自动转换为 Markdown：
- PDF (`.pdf`)
- PowerPoint (`.ppt`, `.pptx`)
- Excel (`.xls`, `.xlsx`)
- Word (`.doc`, `.docx`)

转换后的 Markdown 文件会保存在同一目录下，文件名为原文件名 + `.md` 扩展名。

## Agent 集成

### 自动文件列举

Agent 在每次请求时会自动收到已上传文件的列表，格式如下：

```xml
<uploaded_files>
The following files have been uploaded and are available for use:

- document.pdf (1.2 MB)
  Path: /mnt/user-data/uploads/document.pdf

- document.md (45.3 KB)
  Path: /mnt/user-data/uploads/document.md

You can read these files using the `read_file` tool with the paths shown above.
</uploaded_files>
```

### 使用上传的文件

Agent 在沙箱中运行，使用虚拟路径访问文件。Agent 可以直接使用 `read_file` 工具读取上传的文件：

```python
# 读取原始 PDF（如果支持）
read_file(path="/mnt/user-data/uploads/document.pdf")

# 读取转换后的 Markdown（推荐）
read_file(path="/mnt/user-data/uploads/document.md")
```

**路径映射关系：**
- Agent 使用：`/mnt/user-data/uploads/document.pdf`（虚拟路径）
- 实际存储：`backend/.deer-flow/threads/{thread_id}/user-data/uploads/document.pdf`
- 前端访问：`/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/document.pdf`（HTTP URL）

上传流程采用“线程目录优先”策略：
- 先写入 `backend/.deer-flow/threads/{thread_id}/user-data/uploads/` 作为权威存储
- 本地沙箱（`sandbox_id=local`）直接使用线程目录内容
- 非本地沙箱会额外同步到 `/mnt/user-data/uploads/*`，确保运行时可见

## 测试示例

### 使用 curl 测试

```bash
# 1. 上传单个文件
curl -X POST http://localhost:2026/api/threads/test-thread/uploads \
  -F "files=@/path/to/document.pdf"

# 2. 上传多个文件
curl -X POST http://localhost:2026/api/threads/test-thread/uploads \
  -F "files=@/path/to/document.pdf" \
  -F "files=@/path/to/presentation.pptx" \
  -F "files=@/path/to/spreadsheet.xlsx"

# 3. 列出已上传文件
curl http://localhost:2026/api/threads/test-thread/uploads/list

# 4. 删除文件
curl -X DELETE http://localhost:2026/api/threads/test-thread/uploads/document.pdf
```

### 使用 Python 测试

```python
import requests

thread_id = "test-thread"
base_url = "http://localhost:2026"

# 上传文件
files = [
    ("files", open("document.pdf", "rb")),
    ("files", open("presentation.pptx", "rb")),
]
response = requests.post(
    f"{base_url}/api/threads/{thread_id}/uploads",
    files=files
)
print(response.json())

# 列出文件
response = requests.get(f"{base_url}/api/threads/{thread_id}/uploads/list")
print(response.json())

# 删除文件
response = requests.delete(
    f"{base_url}/api/threads/{thread_id}/uploads/document.pdf"
)
print(response.json())
```

## 文件存储结构

```
backend/.deer-flow/threads/
└── {thread_id}/
    └── user-data/
        └── uploads/
            ├── document.pdf          # 原始文件
            ├── document.md           # 转换后的 Markdown
            ├── presentation.pptx
            ├── presentation.md
            └── ...
```

## 限制

- 最大文件大小：100MB（可在 nginx.conf 中配置 `client_max_body_size`）
- 文件名安全性：系统会自动验证文件路径，防止目录遍历攻击
- 线程隔离：每个线程的上传文件相互隔离，无法跨线程访问

## 技术实现

### 组件

1. **Upload Router** (`src/gateway/routers/uploads.py`)
   - 处理文件上传、列表、删除请求
   - 使用 markitdown 转换文档

2. **Uploads Middleware** (`src/agents/middlewares/uploads_middleware.py`)
   - 在每次 Agent 请求前注入文件列表
   - 自动生成格式化的文件列表消息

3. **Nginx 配置** (`nginx.conf`)
   - 路由上传请求到 Gateway API
   - 配置大文件上传支持

### 依赖

- `markitdown>=0.0.1a2` - 文档转换
- `python-multipart>=0.0.20` - 文件上传处理

## 故障排查

### 文件上传失败

1. 检查文件大小是否超过限制
2. 检查 Gateway API 是否正常运行
3. 检查磁盘空间是否充足
4. 查看 Gateway 日志：`make gateway`

### 文档转换失败

1. 检查 markitdown 是否正确安装：`uv run python -c "import markitdown"`
2. 查看日志中的具体错误信息
3. 某些损坏或加密的文档可能无法转换，但原文件仍会保存

### Agent 看不到上传的文件

1. 确认 UploadsMiddleware 已在 agent.py 中注册
2. 检查 thread_id 是否正确
3. 确认文件确实已上传到 `backend/.deer-flow/threads/{thread_id}/user-data/uploads/`
4. 非本地沙箱场景下，确认上传接口没有报错（需要成功完成 sandbox 同步）

## 开发建议

### 前端集成

```typescript
// 上传文件示例
async function uploadFiles(threadId: string, files: File[]) {
  const formData = new FormData();
  files.forEach(file => {
    formData.append('files', file);
  });

  const response = await fetch(
    `/api/threads/${threadId}/uploads`,
    {
      method: 'POST',
      body: formData,
    }
  );

  return response.json();
}

// 列出文件
async function listFiles(threadId: string) {
  const response = await fetch(
    `/api/threads/${threadId}/uploads/list`
  );
  return response.json();
}
```

### 扩展功能建议

1. **文件预览**：添加预览端点，支持在浏览器中直接查看文件
2. **批量删除**：支持一次删除多个文件
3. **文件搜索**：支持按文件名或类型搜索
4. **版本控制**：保留文件的多个版本
5. **压缩包支持**：自动解压 zip 文件
6. **图片 OCR**：对上传的图片进行 OCR 识别
