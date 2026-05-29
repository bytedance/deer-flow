# DeerFlow 会话启动 REST API 调用流程

本文档描述通过 DeerFlow REST API 启动一个完整会话的调用流程。API 通过 Nginx 反向代理暴露在 port 2026。

**Base URL**: `http://localhost:2026`

---

## 前置检查

### 健康检查

```http
GET /health
```

```json
{"status": "healthy", "service": "deer-flow-gateway"}
```

### 认证状态检查

```http
GET /api/v1/auth/setup-status
```

```json
{"needs_setup": false}
```

---

## 1. 认证流程（可选）

取决于 DeerFlow 配置。若部署在可信任内网且无用户隔离需求，可跳过此步骤。

### 首次初始化（当 needs_setup: true 时）

```http
POST /api/v1/auth/initialize
Content-Type: application/json

{
  "email": "admin@example.com",
  "password": "your-password"
}
```

### 日常登录

```http
POST /api/v1/auth/login/local
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "your-password"
}
```

**响应**：登录成功后会设置 `access_token` HttpOnly cookie，后续请求无需额外 Header。

### 其他认证端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/auth/me` | 获取当前用户信息 |
| POST | `/api/v1/auth/logout` | 登出，清除 session cookie |
| POST | `/api/v1/auth/register` | 注册新用户 |
| POST | `/api/v1/auth/change-password` | 修改密码 |

> 受保护的状态变更请求还需要在 Header 中携带 `X-CSRF-Token`（值为 cookie 中的 `csrf_token`）。登录/注册/初始化/登出端点豁免此要求，但仍会拒绝恶意 `Origin` 头。

---

## 2. 获取运行时配置

### 获取可用模型列表

```http
GET /api/models
```

**响应示例：**
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
      "name": "deepseek-v3",
      "display_name": "DeepSeek V3",
      "supports_thinking": true,
      "supports_vision": false
    }
  ]
}
```

### 获取模型详情

```http
GET /api/models/{model_name}
```

### 获取已启用的 Skills

```http
GET /api/skills
```

### 获取 MCP 配置

```http
GET /api/mcp/config
```

---

## 3. 创建会话 Thread

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

> `thread_id` 是后续所有操作的唯一标识。

---

## 4. （可选）上传文件到 Thread

支持 PDF、PPT、Excel、Word 文档，自动转换为 Markdown。

```http
POST /api/threads/{thread_id}/uploads
Content-Type: multipart/form-data

files: @document.pdf
```

**响应：**
```json
{
  "success": true,
  "files": [
    {
      "filename": "document.pdf",
      "size": 1234567,
      "virtual_path": "/mnt/user-data/uploads/document.pdf",
      "markdown_file": "document.md",
      "markdown_virtual_path": "/mnt/user-data/uploads/document.md"
    }
  ],
  "message": "Successfully uploaded 1 file(s)"
}
```

### 列出已上传文件

```http
GET /api/threads/{thread_id}/uploads/list
```

### 删除上传文件

```http
DELETE /api/threads/{thread_id}/uploads/{filename}
```

---

## 5. 启动会话流（核心步骤）

### 方式 A：流式返回（SSE）— 推荐

```http
POST /api/threads/{thread_id}/runs/stream
Content-Type: application/json
Accept: text/event-stream

{
  "input": {
    "messages": [{"role": "user", "content": "帮我分析这份文档"}]
  },
  "config": {
    "recursion_limit": 100,
    "configurable": {
      "model_name": "deepseek-v3",
      "thinking_enabled": true,
      "is_plan_mode": false
    }
  },
  "stream_mode": ["values", "messages-tuple", "custom"]
}
```

**configurable 选项说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `model_name` | string | 覆盖默认模型 |
| `thinking_enabled` | boolean | 为支持思考的模型启用扩展思考 |
| `is_plan_mode` | boolean | 启用 TodoList 中间件，支持任务跟踪 |

**stream_mode 说明：**

- `values` — 完整状态快照（包含 messages、title、artifacts）
- `messages-tuple` — 增量更新：AI 文本为 delta，工具调用/结果逐条推送
- `custom` — 来自 StreamWriter 的自定义事件
- `updates` / `events` / `debug` / `tasks` / `checkpoints` — 额外模式
- **不要使用**：`tools`（已废弃，会触发 schema 校验错误）

**SSE 响应格式：**

```
event: values
data: {"values": {"messages": [...], "title": "..."}}

event: messages
data: {"content": "我来帮你分析...", "role": "assistant"}

event: messages
data: {"type": "tool_call", "name": "bash", "input": {"command": "ls"}}

event: messages
data: {"type": "tool_result", "tool_call_id": "abc123", "content": "file1.txt\nfile2.txt"}

event: custom
data: {"type": "artifact", "data": {...}}

event: end
data: {}
```

### 方式 B：阻塞等待

```http
POST /api/threads/{thread_id}/runs/wait
Content-Type: application/json

{
  "input": {"messages": [{"role": "user", "content": "..."}]},
  "config": {"configurable": {"model_name": "gpt-4"}}
}
```

**响应**：直接返回最终 AI 回复文本（不推荐用于长对话，LLM 响应慢时会阻塞超时）。

---

## 6. 会话交互后的查询接口

### 获取历史消息

```http
GET /api/threads/{thread_id}/messages
```

```json
{
  "data": [
    {"type": "human", "content": "帮我分析文档"},
    {"type": "ai", "content": "我来帮你分析..."},
    {"type": "tool", "name": "bash", "content": "..."}
  ],
  "has_more": false
}
```

### 获取 Thread 完整状态

```http
GET /api/threads/{thread_id}/state
```

```json
{
  "values": {
    "messages": [...],
    "artifacts": [...],
    "title": "文档分析",
    "todos": [],
    "thread_data": {...}
  },
  "next": []
}
```

### 获取 Run 历史

```http
GET /api/threads/{thread_id}/runs
```

### 获取 Token 使用统计

```http
GET /api/threads/{thread_id}/token-usage
```

### 获取 AI 建议的跟进问题

```http
POST /api/threads/{thread_id}/suggestions
```

---

## 7. 后续对话

重复步骤 5，在 `input.messages` 中包含完整对话历史：

```json
{
  "input": {
    "messages": [
      {"role": "user", "content": "第一轮消息"},
      {"role": "assistant", "content": "第一轮回复"},
      {"role": "user", "content": "第二轮消息"}
    ]
  }
}
```

---

## 8. 清理 Thread

### 删除 Thread（仅删除 LangGraph 记录）

```http
DELETE /api/threads/{thread_id}
```

### 删除 Thread 及其本地文件

LangGraph thread 删除后，调用 Gateway 端点清理本地文件：

```http
DELETE /api/threads/{thread_id}
```

> 本接口删除 `backend/.deer-flow/threads/{thread_id}` 目录。失败时返回 500，但 LangGraph thread 本身已删除。

---

## 完整调用序列

```
Client              Nginx              Gateway API
  │                   │                    │
  ├─── GET /health ──────────────────────►│
  │◄── 200 OK ────────────────────────────│
  │                   │                    │
  ├─── GET /api/v1/auth/setup-status ───►│
  │◄── {needs_setup} ────────────────────│
  │                   │                    │
  ├─── POST /api/v1/auth/login/local ────►│  → Set-Cookie: access_token
  │◄── 200 OK + cookie ──────────────────│
  │                   │                    │
  ├─── GET /api/models ──────────────────►│
  │◄── {models: [...]} ───────────────────│
  │                   │                    │
  ├─── GET /api/skills ───────────────────►│
  │◄── {skills: [...]} ───────────────────│
  │                   │                    │
  ├─── POST /api/threads ─────────────────►│
  │◄── {thread_id} ──────────────────────│
  │                   │                    │
  ├─── POST /api/threads/{id}/uploads ───►│  (optional)
  │◄── {files: [...]} ───────────────────│
  │                   │                    │
  ├─── POST /api/threads/{id}/runs/stream ►│  ← 核心对话请求
  │◄─── SSE stream ──────────────────────│
  │   events: values, messages, custom...   │
  │◄─── event: end ─────────────────────│
  │                   │                    │
  ├─── GET /api/threads/{id}/messages ───►│
  │◄── {data: [...]} ────────────────────│
```

---

## Nginx 路由规则

无论本地模式（`make start`）还是 Docker 模式（`scripts/deploy.sh start`），路由规则一致：

| 路径 | 目标 | 说明 |
|------|------|------|
| `/api/langgraph/*` | Gateway LangGraph Runtime | Agent 对话、Thread、Run 操作 |
| `/api/*`（其他） | Gateway REST API | Models、MCP、Skills、Uploads 等 |
| `/` | Frontend (3000) | Web UI |

---

## 认证与用户隔离

- **有认证模式**：所有非公开路由需要登录。用户数据按 `user_id` 隔离，Thread/Memory/Agents 均存储在 `backend/.deer-flow/users/{user_id}/` 下。
- **无认证模式**：所有请求使用默认用户 `user_id="default"`。

---

## 附录：cURL 快速测试

```bash
# 健康检查
curl http://localhost:2026/health

# 创建 Thread
curl -X POST http://localhost:2026/api/threads \
  -H "Content-Type: application/json" \
  -d '{}'

# 发送消息并流式接收
curl -X POST http://localhost:2026/api/threads/{thread_id}/runs/stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "Hello"}]},
    "stream_mode": ["values", "messages-tuple", "custom"]
  }'

# 获取历史消息
curl http://localhost:2026/api/threads/{thread_id}/messages
```
