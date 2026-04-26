# API 参考文档

本文档提供DeerFlow后端API的完整参考。

## 概述

===================
设计思路说明
===================

**为什么分为两套API**：
DeerFlow后端暴露两套API以实现关注点分离：

1. **LangGraph API** (`/api/langgraph/*`) - 代理交互、线程管理和流式响应
   - 由LangGraph服务器提供
   - 遵循LangGraph SDK约定
   - 处理所有与代理执行相关的操作

2. **Gateway API** (`/api/*`) - 模型、MCP、技能、上传和产物
   - 由FastAPI网关提供
   - 处理辅助功能（配置、文件管理、技能管理等）
   - 为前端提供统一的辅助接口

**架构优势**：
- **解耦设计**：代理逻辑与辅助功能分离，便于独立扩展
- **标准化**：LangGraph API兼容LangGraph SDK，降低集成成本
- **灵活性**：Gateway API可根据需求定制，不影响核心代理流程

所有API通过Nginx反向代理在端口2026访问。

---

## LangGraph API

基础URL: `/api/langgraph`

LangGraph API由LangGraph服务器提供，遵循LangGraph SDK约定。

### 线程(Thread)管理

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

### 运行(Run)管理

#### 创建运行

使用输入执行代理。

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
    "configurable": {
      "model_name": "gpt-4",
      "thinking_enabled": false,
      "is_plan_mode": false
    }
  },
  "stream_mode": ["values", "messages-tuple", "custom"]
}
```

**流模式兼容性说明：**
- **支持的模式**：`values`, `messages-tuple`, `custom`, `updates`, `events`, `debug`, `tasks`, `checkpoints`
- **不支持的模式**：`tools`（在当前`langgraph-api`中已弃用/无效，会触发schema验证错误）

**可配置选项：**
- `model_name` (字符串)：覆盖默认模型
- `thinking_enabled` (布尔值)：为支持的模型启用扩展思考模式
- `is_plan_mode` (布尔值)：启用TodoList中间件进行任务跟踪

**响应：** Server-Sent Events (SSE) 流

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

与创建运行相同的请求体。返回SSE流。

---

## Gateway API

基础URL: `/api`

### 模型管理

#### 列出模型

从配置中获取所有可用的LLM模型。

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

### MCP配置管理

#### 获取MCP配置

获取当前MCP服务器配置。

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
    },
    "filesystem": {
      "enabled": false,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem"],
      "description": "File system access"
    }
  }
}
```

#### 更新MCP配置

更新MCP服务器配置。

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

### 技能管理

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

从`.skill`文件安装技能。

```http
POST /api/skills/install
Content-Type: multipart/form-data
```

**请求体：**
- `file`: 要安装的`.skill`文件

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
- `files`: 一个或多个要上传的文件

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

**支持的文档格式**（自动转换为Markdown）：
- PDF (`.pdf`)
- PowerPoint (`.ppt`, `.pptx`)
- Excel (`.xls`, `.xlsx`)
- Word (`.doc`, `.docx`)

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

在LangGraph线程本身被删除后，删除`.deer-flow/threads/{thread_id}`下的DeerFlow管理的本地线程文件。

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
- `422` - 无效的线程ID
- `500` - 返回通用的`{"detail": "Failed to delete local thread data."}`响应，完整异常详情保留在服务器日志中

### 产物管理

#### 获取产物

下载或查看代理生成的产物。

```http
GET /api/threads/{thread_id}/artifacts/{path}
```

**路径示例：**
- `/api/threads/abc123/artifacts/mnt/user-data/outputs/result.txt`
- `/api/threads/abc123/artifacts/mnt/user-data/uploads/document.pdf`

**查询参数：**
- `download` (布尔值)：如果为`true`，强制下载并设置Content-Disposition头

**响应：** 带有适当Content-Type的文件内容

---

## 错误响应

所有API以一致的格式返回错误：

```json
{
  "detail": "Error message describing what went wrong"
}
```

**HTTP状态码：**
- `400` - Bad Request: 无效输入
- `404` - Not Found: 资源未找到
- `422` - Validation Error: 请求验证失败
- `500` - Internal Server Error: 服务器端错误

---

## 认证

目前，DeerFlow未实现认证。所有API都无需凭据即可访问。

**注意：** 这是关于DeerFlow API认证。MCP出站连接仍可为配置的HTTP/SSE MCP服务器使用OAuth。

**对于生产部署，建议：**
1. 使用Nginx进行基本认证或OAuth集成
2. 部署在VPN或私有网络后
3. 实现自定义认证中间件

---

## 速率限制

默认未实现速率限制。对于生产部署，在Nginx中配置速率限制：

```nginx
limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;

location /api/ {
    limit_req zone=api burst=20 nodelay;
    proxy_pass http://backend;
}
```

---

## WebSocket支持

LangGraph服务器支持WebSocket连接进行实时流式传输。连接到：

```
ws://localhost:2026/api/langgraph/threads/{thread_id}/runs/stream
```

---

## SDK使用示例

### Python (LangGraph SDK)

```python
from langgraph_sdk import get_client

client = get_client(url="http://localhost:2026/api/langgraph")

# 创建线程
thread = await client.threads.create()

# 运行代理
async for event in client.runs.stream(
    thread["thread_id"],
    "lead_agent",
    input={"messages": [{"role": "user", "content": "Hello"}]},
    config={"configurable": {"model_name": "gpt-4"}},
    stream_mode=["values", "messages-tuple", "custom"],
):
    print(event)
```

### JavaScript/TypeScript

```typescript
// 使用fetch调用Gateway API
const response = await fetch('/api/models');
const data = await response.json();
console.log(data.models);

// 使用EventSource进行流式传输
const eventSource = new EventSource(
  `/api/langgraph/threads/${threadId}/runs/stream`
);
eventSource.onmessage = (event) => {
  console.log(JSON.parse(event.data));
};
```

### cURL示例

```bash
# 列出模型
curl http://localhost:2026/api/models

# 获取MCP配置
curl http://localhost:2026/api/mcp/config

# 上传文件
curl -X POST http://localhost:2026/api/threads/abc123/uploads \
  -F "files=@document.pdf"

# 启用技能
curl -X POST http://localhost:2026/api/skills/pdf-processing/enable

# 创建线程并运行代理
curl -X POST http://localhost:2026/api/langgraph/threads \
  -H "Content-Type: application/json" \
  -d '{}'

curl -X POST http://localhost:2026/api/langgraph/threads/abc123/runs \
  -H "Content-Type: application/json" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "Hello"}]},
    "config": {"configurable": {"model_name": "gpt-4"}}
  }'
```
