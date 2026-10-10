# 文件上传功能

## 概述

DeerFlow 后端提供了完整的文件上传功能，支持多文件上传，并可选地将 Office 文档和 PDF 转换为 Markdown 格式。

## 功能特性

- ✅ 支持多文件同时上传
- ✅ 可选地转换文档为 Markdown（PDF、PPT、Excel、Word）
- ✅ 文件存储在线程隔离的目录中
- ✅ Agent 自动感知当前消息中附带的文件
- ✅ 支持文件列表查询和删除

## API 端点

### 1. 上传文件
```
POST /api/threads/{thread_id}/uploads
```

**请求体：** `multipart/form-data`
- `files`: 一个或多个文件

网关会在应用层限制上传规模，默认最多 10 个文件、单文件 50 MiB、单次请求总计 100 MiB。可通过 `config.yaml` 的 `uploads.max_files`、`uploads.max_file_size`、`uploads.max_total_size` 调整；前端会读取同一组限制并在选择文件时提示，超过限制时后端返回 `413 Payload Too Large`。

文件名匹配 `.upload-*.part`（例如 `.upload-notes.part`）时，网关会返回 `400 Bad Request`，提示改名后重新上传。这是系统保留的临时文件命名规则；文件名按去掉目录后的 basename 判断，HTTP 检查在 Linux 上也同时识别 `/` 和 `\` 两种路径分隔符，例如 `folder\.upload-notes.part`。网关会先检查整批文件，再开始写入聊天的上传目录或获取沙箱，因此保留名称排在批次末尾也不会留下部分上传。聊天界面收到该错误后会提示用户，并停止本次消息发送。`.upload-notes.txt`、`notes.part` 和 `.env` 仍可上传。

检查也会拒绝 Windows 去掉末尾点号或空格、忽略大小写后会变成保留名称的别名，例如 `.upload-notes.part.`、`.upload-notes.part `、`.UPLOAD-NOTES.PART` 和 `.Upload-NoTeS.Part .`。这项检查在所有主机上生效，HTTP 上传会在整批文件写入前返回 `400`，提示改名。

嵌入式 `DeerFlowClient.upload_files` 同样在复制前检查整批文件名，保留名称会抛出 `ValueError`。项目资料库上传和从聊天加入资料库时的重命名也遵循这项限制，包括沿用来源文件名和手动指定新名称两种情况；旧资料库中使用保留名称的文件仍可下载，但直接附加到聊天会返回 `400`。请先下载、改名，再上传到聊天。本修复不会迁移或恢复旧聊天目录中已经匹配该临时文件规则的文件。

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

### 2. 查询上传限制
```
GET /api/threads/{thread_id}/uploads/limits
```

返回网关当前生效的上传限制，供前端在用户选择文件前提示和拦截。

**响应：**
```json
{
  "max_files": 10,
  "max_file_size": 52428800,
  "max_total_size": 104857600
}
```

### 3. 列出已上传文件
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

### 4. 删除文件
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

以下格式在显式启用 `uploads.auto_convert_documents: true` 时会自动转换为 Markdown：
- PDF (`.pdf`)
- PowerPoint (`.ppt`, `.pptx`)
- Excel (`.xls`, `.xlsx`)
- Word (`.doc`, `.docx`)

转换后的 Markdown 文件会保存在同一目录下，通常使用原文件的主干名加 `.md`；若该名称已被占用，则追加 `_N` 后缀。上传响应中的 `markdown_file` 给出实际名称。

新转换会在沙箱挂载目录之外保存原文件与转换文件的归属记录。Agent 的历史文件列表只隐藏归属已验证的转换文件；文档大纲也只读取这份记录指定的 Markdown。原文件校验包含修改时间戳，即使修改前后大小相同，也会拒绝使用旧转换结果。旧版本没有归属记录或记录缺少原文件时间戳的转换文件，升级后会作为独立 Markdown 显示，原文件也不会再从这些文件读取大纲。系统不会自动补建记录或填入当前时间戳，以免将过期转换结果认定为有效；需要大纲时，可在启用 `uploads.auto_convert_documents: true` 后重新上传原文件。原文件和转换文件都会保留。

时间戳校验是保守的元数据校验，不能保证文件内容完全一致。Windows 上的 `st_ctime_ns` 可能表示创建时间，因此等长度覆盖后若恢复原 `mtime`，校验可能无法识别变化。

默认情况下，自动转换是关闭的，以避免在网关主机上对不受信任的 Office/PDF 上传执行解析。只有在受信任部署中明确接受此风险时，才应将 `uploads.auto_convert_documents` 设置为 `true`。

## Agent 集成

### 当前消息中的文件上下文

发送消息时，前端会把该消息附带的上传文件元数据放入
`HumanMessage.additional_kwargs.files`。`UploadsMiddleware` 只把当前消息中的文件
注入 Agent 上下文，格式如下：

```xml
<current_uploads>
The following files were uploaded in this message:

- document.pdf (1.2 MB)
  Path: /mnt/user-data/uploads/document.pdf

To work with these files:
- Read from the file first — use the outline line numbers and `read_file` to locate relevant sections.
- Use `grep` to search for keywords when you are not sure which section to look at.
- Use `glob` to find files by name pattern.
</current_uploads>
```

以前轮次上传的文件不会在每次请求中重复注入。Agent 可按需调用
`list_uploaded_files` 查询历史上传（可选 `query` 按文件名子串过滤、
`extensions` 按类型过滤；过滤发生在默认 20 条上限之前）。如果已知文件名，也可直接使用
`read_file` 或 `grep` 访问 `/mnt/user-data/uploads/` 下的文件。

历史上传支持有界续页：`max_results` 默认 20、每页最多 100。
返回 `next_cursor` 时，将其作为下一次调用的 `cursor`，并保留相同的
`query` / `extensions`；末页没有 `next_cursor`。可在续页时调整每页数量和
`include_outline`，大纲只针对当前页提取。结果按修改时间倒序、同时间按原始文件名
排序；`total_count` 是完整过滤结果数，`omitted_summary` 只统计当前页之后剩余的文件。

例如 250 个匹配附件可按 100 → 100 → 50 枚举。每页都排除本轮上传、staging、
符号链接以及现有规则识别的转换 companion。规范化后的过滤条件、用户、线程、
本轮上传排除集合或目录中的普通文件清单元数据改变时，旧游标返回
`error: stale_cursor`；畸形或过长游标返回 `error: invalid_cursor`。
两种情况都有 `restart_required: true`，应丢弃此前收集的页，省略 `cursor`
重新开始，避免把两次不同枚举混合起来。

游标仅用于一致性校验，不是授权凭据；工具仍从可信 runtime 解析当前用户和线程。
每页重新扫描目录，校验文件名、大小及纳秒级修改/变更时间，不保存持久快照，
不保证文件字节不变或扫描期间的原子快照，也不限制任意大目录的扫描开销。

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
- 默认情况下，非本地沙箱通过 `acquire_async` 获取后，再额外同步到 `/mnt/user-data/uploads/*`，确保运行时可见
- 如果 Gateway 与远端沙箱保证挂载同一份线程 user-data（例如正确对齐的共享 PVC、NFS 或 hostPath），可设置 `sandbox.thread_data_mounts: true`；上传路由会跳过 sandbox acquire 和逐文件同步
- 不确定挂载关系时应省略该配置并保留自动检测。错误地设为 `true` 会导致文件只存在于 Gateway 存储、沙箱内不可见

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
{DEER_FLOW_HOME}/users/{user_id}/threads/{thread_id}/
├── upload-companions/              # 服务端归属记录，不挂载到沙箱
│   └── <原文件名的 SHA-256>.json
└── user-data/
    └── uploads/
        ├── document.pdf            # 原始文件
        ├── document.md             # 转换后的 Markdown
        ├── presentation.pptx
        ├── presentation.md
        └── ...
```

## 限制

- 最大文件大小：100MB（可在 nginx.conf 中配置 `client_max_body_size`）
- 文件名安全性：系统会自动验证文件路径，防止目录遍历攻击
- 删除只作用于普通文件：上传目录中的符号链接不会被跟随，删除请求按文件不存在（404）处理
- 删除文档不会一并删除其转换生成的 Markdown；转换文件仍可通过上传 API 单独删除。`list_uploaded_files` 只对有归属记录的转换文件做历史发现排除，不影响上传 API 的完整文件列表（见 issue #5672）
- 上传（HTTP 与嵌入式 `DeerFlowClient`）不会写穿符号链接：目标名已是符号链接的文件会被跳过并列入 `skipped_files`，转换生成的 Markdown 也不会写入同名符号链接
- 转换读取的是本次上传写入的字节，而非落盘后的文件名：HTTP 上传在 uploads 之外的私有副本上转换，嵌入式客户端转换调用方提供的源文件，因此沙箱替换该文件名无法让宿主文件内容被转换进 uploads
- 线程隔离：每个线程的上传文件相互隔离，无法跨线程访问
- 自动文档转换默认关闭；如需启用，需在 `config.yaml` 中显式设置 `uploads.auto_convert_documents: true`

## 技术实现

### 组件

1. **Upload Router** (`app/gateway/routers/uploads.py`)
   - 处理文件上传、列表、删除请求
   - 使用 markitdown 转换文档

2. **Uploads Middleware** (`packages/harness/deerflow/agents/middlewares/uploads_middleware.py`)
   - 读取当前消息的 `additional_kwargs.files`
   - 在 Agent 请求前生成并注入 `<current_uploads>` 文件上下文
   - 历史上传由 `list_uploaded_files` 按需查询（可按文件名/扩展名过滤后再截断），不会每轮自动注入

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
