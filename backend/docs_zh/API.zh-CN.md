# API 参考

本文档提供 DeerFlow 后端 API 的完整参考。

## 概览

DeerFlow 后端暴露两组 API：

1. **兼容 LangGraph 的 API** - Agent 交互、线程与流式输出（`/api/langgraph/*`）
2. **Gateway API** - 模型、MCP、技能、上传与产物（`/api/*`）

所有 API 均通过 2026 端口上的 Nginx 反向代理访问。

## 兼容 LangGraph 的 API

基础 URL：`/api/langgraph`

公开的 LangGraph 兼容 API 遵循 LangGraph SDK 约定。在统一的 nginx 部署中，Gateway 接管 `/api/langgraph/*`，并将这些路径转换到其原生的 `/api/*` 运行、线程与流式路由。

### 线程（Threads）

#### 创建线程

```http
POST /api/langgraph/threads
Content-Type: application/json
```

**请求体：**
```json
{
  "metadata": {}
}
```

**响应：**
```json
{
  "thread_id": "abc123",
  "created_at": "2024-01-15T10:30:00Z",
  "metadata": {}
}
```

#### 获取线程状态

```http
GET /api/langgraph/threads/{thread_id}/state
```

**响应：**
```json
{
  "values": {
    "messages": [...],
    "sandbox": {...},
    "artifacts": [...],
    "thread_data": {...},
    "title": "Conversation Title"
  },
  "next": [],
  "config": {...}
}
```

### 运行（Runs）

#### 创建运行

使用输入执行 agent。

```http
POST /api/langgraph/threads/{thread_id}/runs
Content-Type: application/json
```

**请求体：**
```json
{
  "input": {
    "messages": [
      {
        "role": "user",
        "content": "Hello, can you help me?"
      }
    ]
  },
  "config": {
    "recursion_limit": 100,
    "configurable": {
      "model_name": "gpt-4",
      "thinking_enabled": false,
      "is_plan_mode": false
    }
  },
  "stream_mode": ["values", "messages-tuple", "custom"]
}
```

**流模式兼容性：**
- 可用：`values`、`messages-tuple`、`custom`、`updates`、`events`、`debug`、`tasks`、`checkpoints`
- 不可用：`tools`（已弃用/在当前 `langgraph-api` 中无效，会触发 schema 校验错误）

**递归限制：**

`config.recursion_limit` 用于限制 LangGraph 在单次运行中可执行的图步骤数。统一 Gateway 路径在 `build_run_config` 中默认设置为 `100`（见 `backend/app/gateway/services.py`），这对于 plan mode 或大量 subagent 的运行是更安全的起点。客户端仍可在请求体中显式设置 `recursion_limit`；若你的 subagent 图嵌套层级较深，请提高该值。

**可配置选项：**
- `model_name`（string）：覆盖默认模型
- `thinking_enabled`（boolean）：为支持的模型启用扩展思考
- `is_plan_mode`（boolean）：启用 TodoList 中间件进行任务追踪

**响应：** Server-Sent Events（SSE）流

```
event: values
data: {"messages": [...], "title": "..."}

event: messages
data: {"content": "Hello! I'd be happy to help.", "role": "assistant"}

event: end
data: {}
```

#### 获取运行历史

```http
GET /api/langgraph/threads/{thread_id}/runs
```

**响应：**
```json
{
  "runs": [
    {
      "run_id": "run123",
      "status": "success",
      "created_at": "2024-01-15T10:30:00Z"
    }
  ]
}
```

#### 流式运行

实时流式返回响应。

```http
POST /api/langgraph/threads/{thread_id}/runs/stream
Content-Type: application/json
```

请求体与“创建运行”相同。返回 SSE 流。

---

## Gateway API（网关接口）

基础 URL：`/api`

### 模型（Models）

#### 列出模型

从配置中获取所有可用的 LLM 模型。

```http
GET /api/models
```

**响应：**
```json
{
  "models": [
    {
      "name": "gpt-4",
      "display_name": "GPT-4",
      "supports_thinking": false,
      "supports_vision": true
    },
    {
      "name": "claude-3-opus",
      "display_name": "Claude 3 Opus",
      "supports_thinking": false,
      "supports_vision": true
    },
    {
      "name": "deepseek-v3",
      "display_name": "DeepSeek V3",
      "supports_thinking": true,
      "supports_vision": false
    }
  ]
}
```

#### 获取模型详情

```http
GET /api/models/{model_name}
```

**响应：**
```json
{
  "name": "gpt-4",
  "display_name": "GPT-4",
  "model": "gpt-4",
  "max_tokens": 4096,
  "supports_thinking": false,
  "supports_vision": true
}
```

### MCP 配置

#### 获取 MCP 配置

获取当前 MCP 服务器配置。

```http
GET /api/mcp/config
```

**响应：**
```json
{
  "mcpServers": {
    "github": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "***"
      },
      "description": "GitHub operations"
    }
  }
}
```

#### 更新 MCP 配置

更新 MCP 服务器配置。

```http
PUT /api/mcp/config
Content-Type: application/json
```

**请求体：**
```json
{
  "mcpServers": {
    "github": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "$GITHUB_TOKEN"
      },
      "description": "GitHub operations"
    }
  }
}
```

**响应：**
```json
{
  "success": true,
  "message": "MCP configuration updated"
}
```

### 技能（Skills）

#### 列出技能

获取所有可用技能。

```http
GET /api/skills
```

**响应：**
```json
{
  "skills": [
    {
      "name": "pdf-processing",
      "display_name": "PDF Processing",
      "description": "Handle PDF documents efficiently",
      "enabled": true,
      "license": "MIT",
      "path": "public/pdf-processing"
    },
    {
      "name": "frontend-design",
      "display_name": "Frontend Design",
      "description": "Design and build frontend interfaces",
      "enabled": false,
      "license": "MIT",
      "path": "public/frontend-design"
    }
  ]
}
```

#### 获取技能详情

```http
GET /api/skills/{skill_name}
```

**响应：**
```json
{
  "name": "pdf-processing",
  "display_name": "PDF Processing",
  "description": "Handle PDF documents efficiently",
  "enabled": true,
  "license": "MIT",
  "path": "public/pdf-processing",
  "allowed_tools": ["read_file", "write_file", "bash"],
  "content": "# PDF Processing\n\nInstructions for the agent..."
}
```

#### 启用技能

```http
POST /api/skills/{skill_name}/enable
```

**响应：**
```json
{
  "success": true,
  "message": "Skill 'pdf-processing' enabled"
}
```

#### 禁用技能

```http
POST /api/skills/{skill_name}/disable
```

**响应：**
```json
{
  "success": true,
  "message": "Skill 'pdf-processing' disabled"
}
```

#### 安装技能

从 `.skill` 文件安装技能。

```http
POST /api/skills/install
Content-Type: multipart/form-data
```

**请求体：**
- `file`：要安装的 `.skill` 文件

**响应：**
```json
{
  "success": true,
  "message": "Skill 'my-skill' installed successfully",
  "skill": {
    "name": "my-skill",
    "display_name": "My Skill",
    "path": "custom/my-skill"
  }
}
```

### 文件上传

#### 上传文件

向线程上传一个或多个文件。

```http
POST /api/threads/{thread_id}/uploads
Content-Type: multipart/form-data
```

**请求体：**
- `files`：要上传的一个或多个文件

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
    }
  ],
  "message": "Successfully uploaded 1 file(s)"
}
```

**支持的文档格式**（自动转换为 Markdown）：
- PDF（`.pdf`）
- PowerPoint（`.ppt`、`.pptx`）
- Excel（`.xls`、`.xlsx`）
- Word（`.doc`、`.docx`）

#### 列出已上传文件

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

#### 删除文件

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

### 线程清理

在 LangGraph 线程本身已删除后，删除 `.deer-flow/threads/{thread_id}` 下由 DeerFlow 管理的本地线程文件。

```http
DELETE /api/threads/{thread_id}
```

**响应：**
```json
{
  "success": true,
  "message": "Deleted local thread data for abc123"
}
```

**错误行为：**
- 线程 ID 无效时返回 `422`
- `500` 返回通用响应 `{"detail": "Failed to delete local thread data."}`，完整异常细节保留在服务端日志中

### 产物（Artifacts）

#### 获取产物

下载或查看 agent 生成的产物文件。

```http
GET /api/threads/{thread_id}/artifacts/{path}
```

**路径示例：**
- `/api/threads/abc123/artifacts/mnt/user-data/outputs/result.txt`
- `/api/threads/abc123/artifacts/mnt/user-data/uploads/document.pdf`

**查询参数：**
- `download`（boolean）：若为 `true`，则通过 Content-Disposition 头强制下载

**响应：** 带正确 Content-Type 的文件内容

---

## 错误响应

所有 API 统一返回如下错误格式：

```json
{
  "detail": "Error message describing what went wrong"
}
```

**HTTP 状态码：**
- `400` - Bad Request：无效输入
- `404` - Not Found：资源不存在
- `422` - Validation Error：请求校验失败
- `500` - Internal Server Error：服务端错误

---

## 认证

DeerFlow 对所有非公开 HTTP 路由强制认证。公开路由仅限健康检查/文档元数据，以及以下公开认证端点：

- `POST /api/v1/auth/initialize`：在不存在管理员时创建首个管理员账户。
- `POST /api/v1/auth/login/local`：使用邮箱/密码登录并设置 HttpOnly `access_token` cookie。
- `POST /api/v1/auth/register`：创建普通 `user` 账户并设置会话 cookie。
- `POST /api/v1/auth/logout`：清除会话 cookie。
- `GET /api/v1/auth/setup-status`：报告是否仍需创建首个管理员。

需要认证的认证端点如下：

- `GET /api/v1/auth/me`：返回当前用户。
- `POST /api/v1/auth/change-password`：修改密码，可在初始化阶段选择同时修改邮箱，会递增 `token_version` 并重新签发 cookie。

受保护且会改变状态的请求还需要 CSRF 双提交令牌：将 `csrf_token` cookie 的值作为 `X-CSRF-Token` 请求头发送。login/register/initialize/logout 属于引导型认证端点：它们不要求双提交令牌，但仍会拒绝恶意浏览器 `Origin` 头。

用户隔离由认证用户上下文强制保证：

- 线程元数据由 `threads_meta.user_id` 进行作用域隔离；搜索/读取/写入/删除 API 仅暴露当前用户线程。
- 线程文件位于 `{base_dir}/users/{user_id}/threads/{thread_id}/user-data/`，并在沙箱中以 `/mnt/user-data/` 暴露。
- Memory 与自定义 agents 存储在 `{base_dir}/users/{user_id}/...` 下。

注意：MCP 出站连接对已配置的 HTTP/SSE MCP 服务器仍可使用 OAuth；这与 DeerFlow API 认证是两套独立机制。

---

## 限流

默认未启用限流。生产环境部署建议在 Nginx 中配置限流：

```nginx
limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;

location /api/ {
    limit_req zone=api burst=20 nodelay;
    proxy_pass http://backend;
}
```

---

## 流式支持

Gateway 的 LangGraph 兼容 API 使用 Server-Sent Events（SSE）流式输出 run 事件：

```http
POST /api/langgraph/threads/{thread_id}/runs/stream
Accept: text/event-stream
```

---

## SDK 用法

### Python（LangGraph SDK）

```python
from langgraph_sdk import get_client

client = get_client(url="http://localhost:2026/api/langgraph")

# 创建线程
thread = await client.threads.create()

# 运行 agent
async for event in client.runs.stream(
    thread["thread_id"],
    "lead_agent",
    input={"messages": [{"role": "user", "content": "Hello"}]},
    config={"configurable": {"model_name": "gpt-4"}},
    stream_mode=["values", "messages-tuple", "custom"],
):
    print(event)
```

### JavaScript/TypeScript 示例

```typescript
// 使用 fetch 调用 Gateway API
const response = await fetch('/api/models');
const data = await response.json();
console.log(data.models);

// 创建运行并流式读取 SSE 事件
const streamResponse = await fetch(`/api/langgraph/threads/${threadId}/runs/stream`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  },
  body: JSON.stringify({
    input: { messages: [{ role: "user", content: "Hello" }] },
    stream_mode: ["values", "messages-tuple", "custom"],
  }),
});

const reader = streamResponse.body?.getReader();
// 在你的客户端代码中从 reader 解码并解析 SSE 帧。
```

### cURL 示例

```bash
# 列出模型
curl http://localhost:2026/api/models

# 获取 MCP 配置
curl http://localhost:2026/api/mcp/config

# 上传文件
curl -X POST http://localhost:2026/api/threads/abc123/uploads \
  -F "files=@document.pdf"

# 启用技能
curl -X POST http://localhost:2026/api/skills/pdf-processing/enable

# 创建线程并运行 agent
curl -X POST http://localhost:2026/api/langgraph/threads \
  -H "Content-Type: application/json" \
  -d '{}'

curl -X POST http://localhost:2026/api/langgraph/threads/abc123/runs \
  -H "Content-Type: application/json" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "Hello"}]},
    "config": {
      "recursion_limit": 100,
      "configurable": {"model_name": "gpt-4"}
    }
  }'
```

> 统一 Gateway 路径默认将 `config.recursion_limit` 设置为 100，
> 用于 plan mode 和 subagent 密集型运行。客户端仍可显式设置
> `config.recursion_limit`——详情请见[创建运行](#创建运行)章节。
