# 文件上传功能

## 概述

DeerFlow 后端提供了完整的文件上传功能，支持多文件上传，并可选地将 Office 文档和 PDF 转换为 Markdown 格式。

## 功能特性

- ✅ 支持多文件同时上传
- ✅ 可选地转换文档为 Markdown（PDF、PPT、Excel、Word）
- ✅ 文件存储在线程隔离的目录中
- ✅ 跨请求、跨进程的同名文件不会互相覆盖
- ✅ 生成的 Markdown 与用户上传命名空间隔离
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

**响应：**
```json
{
  "success": true,
  "files": [
    {
      "filename": "document.pdf",
      "size": 1234567,
      "path": ".deer-flow/users/{user_id}/threads/{thread_id}/user-data/uploads/document.pdf",
      "virtual_path": "/mnt/user-data/uploads/document.pdf",
      "artifact_url": "/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/document.pdf",
      "markdown_file": "document.pdf.md",
      "markdown_path": ".deer-flow/users/{user_id}/threads/{thread_id}/user-data/.upload-conversions/document.pdf.md",
      "markdown_virtual_path": "/mnt/user-data/.upload-conversions/document.pdf.md",
      "markdown_artifact_url": "/api/threads/{thread_id}/artifacts/mnt/user-data/.upload-conversions/document.pdf.md"
    }
  ],
  "message": "Successfully uploaded 1 file(s)"
}
```

**路径说明：**
- `path`: 实际文件系统路径（相对于 `backend/` 目录）
- `virtual_path`: Agent 在沙箱中使用的虚拟路径
- `artifact_url`: 前端通过 HTTP 访问文件的 URL

所有上传入口都先完整写入同目录暂存文件，再以“不替换已有条目”的原子操作发布。同名碰撞依次命名为 `document.pdf`、`document_1.pdf`、`document_2.pdf`；响应中的 `filename` 和各路径字段始终使用实际发布名。系统内部保留 `.upload-*.part` 作为暂存命名空间；使用该模式的 basename、包含 NUL、`<` 或 `>`、包含保留模型上下文边界标记，或无法在 Windows 上无损表示（如设备名、尾随点/空格或保留字符）的文件名会在创建暂存文件前被拒绝，以保证所有已接受的文件名和 Agent 可见路径都能无损呈现。若请求在 staging 创建尚未返回时被取消，Gateway 会等待创建结束并精确 abort 该临时文件。

实际发布名会在转换、权限调整、沙箱同步和响应构造期间持有同名租约。大小写、Unicode 规范化及 Win32 尾随后缀等可移植文件系统别名共用同一协调键，避免用别名绕过 generation lease。发布遇到正在使用的协调键时不会等待，而会继续选择 `_N` 候选，因此逆序并发批次不会互相持锁；删除仍会等待目标 generation 生命周期完成，并在 hard-link 歧义下拒绝误报成功。跨进程协调使用 `.upload-conversions/.locks/` 下稳定保留的摘要锁文件，该目录属于内部实现，不应由 Agent 或部署脚本修改或清理。最终 lease release 是明确提交点：如果新的取消恰在 release 期间到达，系统会先完成 release 并返回已构造的成功结果，而不会把已提交文件报告成取消。Gateway 拒绝不安全或空的 multipart 文件名时会把原名（空值记为 `""`）加入 `skipped_files` 并返回 `success: false`，不会把“上传 0 个文件”误报为成功。

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
      "path": ".deer-flow/users/{user_id}/threads/{thread_id}/user-data/uploads/document.pdf",
      "virtual_path": "/mnt/user-data/uploads/document.pdf",
      "artifact_url": "/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/document.pdf",
      "extension": ".pdf",
      "modified": 1705997600.0
    }
  ],
  "count": 1
}
```

列表只包含 `uploads/` 下的用户主文件；系统生成的 `.upload-conversions/` 资产不会出现在该接口中。

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

删除 `document.pdf` 时，会先等待该实际文件名当前正在进行的上传、转换或沙箱同步生命周期结束。对于非挂载 provider，系统在同一个 generation lease 内先删除精确同步到沙箱的主文件和转换副本；远端删除失败会返回错误并保留宿主机主文件。随后只删除宿主机上它精确拥有的生成资产和主文件。系统不会推断或删除 `uploads/document.md`；该文件可能是用户独立上传的内容。其他文件名不会被这次等待阻塞。在 POSIX 部署上，升级前已经存在且能被列表接口返回的 Windows 非兼容文件名（例如 `CON`、`report?.pdf`、含反斜杠、仅由点/空格组成或末尾带空格的名称）仍可按返回的精确名称删除；新上传仍执行严格的跨平台文件名校验。

## 支持的文档格式

以下格式在显式启用 `uploads.auto_convert_documents: true` 时会自动转换为 Markdown：
- PDF (`.pdf`)
- PowerPoint (`.ppt`, `.pptx`)
- Excel (`.xls`, `.xlsx`)
- Word (`.doc`, `.docx`)

转换后的 Markdown 文件保存在系统拥有的 `.upload-conversions/` 目录中，文件名包含完整的实际主文件名。例如：

```text
Primary:   /mnt/user-data/uploads/report.pdf
Generated: /mnt/user-data/.upload-conversions/report.pdf.md
Collision: report.pdf, report_1.pdf, report_2.pdf
Deletion:  删除 report.pdf 时只删除 .upload-conversions/report.pdf.md；
           /mnt/user-data/uploads/report.md 永远不会被推断为生成文件或自动删除。
```

通常生成名为 `<实际主文件名>.md`。如果这一文件名组件会超过 255 个 UTF-8 字节，系统会使用 UTF-8 安全截断的主文件名前缀、完整 SHA-256 摘要和 `.md`，并在响应中返回精确的 `markdown_*` 路径。上传名称碰撞产生的 `_N` 名称同样始终限制在 255 个 UTF-8 字节内；极端情况下，如果后缀本身占满几乎整个组件，系统会截断完整原名后再追加 `_N`。客户端和 Agent 不应自行拼接生成路径。AIO 挂载模式把 `.upload-conversions` 显式挂载为只读；远端 Provisioner 会再次校验该挂载必须来自同一用户/线程并覆盖在可写父挂载之上。挂载契约版本进入 AIO sandbox ID，因此旧容器不能满足新版本对该线程的获取；它仍可能被枚举并仅用于常规孤儿清理。Local 的结构化文件 API 通过只读路径映射拒绝写入，但可选的 Local 宿主机 bash 不受该映射约束，不应对不受信任任务启用。非挂载远端沙箱不会安装嵌套只读转换挂载，而是得到独立同步副本；该副本可能可写，但不会修改宿主机上的权威生成文件或内部锁。

直接上传的 `.md` 主文件会从同一个已验证的排他常规文件描述符提取 outline/preview，路径在验证后被替换成 symlink 或 hardlink 也不会读取替换目标；PDF、Office 等其他格式只读取其精确拥有的 `.upload-conversions` 转换件，不会把用户独立上传的同名 Markdown 误认为转换结果。

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
`list_uploaded_files` 查询历史上传；如果已知文件名，也可直接使用
`read_file` 或 `grep` 访问 `/mnt/user-data/uploads/` 下的文件。

### 使用上传的文件

Agent 在沙箱中运行，使用虚拟路径访问文件。Agent 可以直接使用 `read_file` 工具读取上传的文件：

```python
# 读取原始 PDF（如果支持）
read_file(path="/mnt/user-data/uploads/document.pdf")

# 读取转换后的 Markdown（推荐）
read_file(path="/mnt/user-data/.upload-conversions/document.pdf.md")
```

**路径映射关系：**
- Agent 使用：`/mnt/user-data/uploads/document.pdf`（虚拟路径）
- 实际存储：`backend/.deer-flow/users/{user_id}/threads/{thread_id}/user-data/uploads/document.pdf`
- 前端访问：`/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/document.pdf`（HTTP URL）
- 转换结果：`/mnt/user-data/.upload-conversions/document.pdf.md`（以上传响应的 `markdown_virtual_path` 为准，不要自行推导）

上传流程采用“用户/线程目录优先”策略：
- 先写入 `backend/.deer-flow/users/{user_id}/threads/{thread_id}/user-data/uploads/` 作为权威存储
- 本地沙箱（`sandbox_id=local`）直接使用线程目录内容
- AIO 挂载模式把 `/mnt/user-data/.upload-conversions` 单独挂载为只读；Local 的结构化文件 API 通过更具体的只读路径映射执行同一规则，但 Local 宿主机 bash 不属于该边界
- Gateway、嵌入式 `DeerFlowClient` 和 IM 通道都会执行同一沙箱可见性步骤：挂载型 provider 调整精确发布路径的读取权限；非挂载 provider 获取沙箱后，把本次主文件及生成转换件精确同步到各自虚拟路径
- 非挂载同步副本是沙箱私有副本；任一路径失败（包括远端已落盘但传输随后报错）、后续响应构造失败或请求取消时，会对本次尝试的精确远端路径执行幂等撤销，再回滚宿主文件
- 嵌入式 `DeerFlowClient.upload_files()` 以整批为事务边界：后续文件失败会逆序撤销本次调用中此前成功的所有远端副本和宿主 generation
- 如果 Gateway 与远端沙箱保证挂载同一份线程 user-data（例如正确对齐的共享 PVC、NFS 或 hostPath），可设置 `sandbox.thread_data_mounts: true`；只有 Provisioner 能通过 `/api/capabilities` 证明当前挂载契约时，上传路由才会跳过 sandbox acquire 和逐文件同步
- 新 Gateway 与已确认的旧 Provisioner 混合部署时，只有 `default` 无认证用户可降级为显式同步；旧 Provisioner 的主挂载不包含 `user_id`，认证用户必须先升级 Provisioner，否则创建沙箱会 fail closed
- `/api/capabilities` 暂时不可达时会选择显式同步并按退避窗口重试能力协商，不会把缺少嵌套只读转换挂载的 Pod 标记为当前契约；在重试确认当前租户隔离契约之前，认证用户的沙箱创建仍会 fail closed。远端获取（包括活跃缓存和暖池复用）会通过幂等创建重新校验本次请求的完整 Pod 挂载签名，而不是只信任 discovery 或健康检查响应
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
backend/.deer-flow/users/
└── {user_id}/
    └── threads/
        └── {thread_id}/
            └── user-data/
                ├── uploads/
                │   ├── document.pdf          # 用户主文件
                │   ├── document.md           # 用户独立上传，绝不按名称推断归属
                │   └── presentation.pptx
                └── .upload-conversions/
                    ├── document.pdf.md       # document.pdf 的生成结果
                    └── presentation.pptx.md  # presentation.pptx 的生成结果
```

旧版 `backend/.deer-flow/threads/{thread_id}/...` 仅用于兼容和迁移已有数据；新写入不得继续使用该非租户隔离布局。

## 限制

- 最大文件大小：100MB（可在 nginx.conf 中配置 `client_max_body_size`）
- 文件名安全性：系统会自动验证文件路径，防止目录遍历攻击
- 线程隔离：每个线程的上传文件相互隔离，无法跨线程访问
- 自动文档转换默认关闭；如需启用，需在 `config.yaml` 中显式设置 `uploads.auto_convert_documents: true`

## 技术实现

### 组件

1. **Upload Router** (`app/gateway/routers/uploads.py`)
   - 处理文件上传、列表、删除请求
   - 流式写入暂存文件，并通过共享上传管理器原子发布
   - 使用 markitdown 转换文档；生成文件发布到系统拥有的隔离目录

2. **Uploads Middleware** (`packages/harness/deerflow/agents/middlewares/uploads_middleware.py`)
   - 读取当前消息的 `additional_kwargs.files`
   - 在 Agent 请求前生成并注入 `<current_uploads>` 文件上下文
   - 历史上传由 `list_uploaded_files` 按需查询，不会每轮自动注入

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
3. 确认文件确实已上传到 `backend/.deer-flow/users/{user_id}/threads/{thread_id}/user-data/uploads/`
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
