# DeerFlow 输出显示 REST API 调用流程

本文档描述 DeerFlow 会话中 Agent 输出结果的查询、显示、反馈的完整 API 调用流程。

**Base URL**: `http://localhost:2026`

---

## 1. 输出显示相关 API 端点总览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/threads/{thread_id}/state` | 获取 Thread 完整状态（含消息、Artifact、标题） |
| GET | `/api/threads/{thread_id}/messages` | 获取消息列表 |
| GET | `/api/threads/{thread_id}/artifacts/{path}` | 获取生成的文件/Artifact |
| POST | `/api/threads/{thread_id}/suggestions` | 生成跟进问题建议 |
| GET | `/api/threads/{thread_id}/token-usage` | 获取 Token 使用统计 |
| GET | `/api/threads/{thread_id}/runs` | 获取 Run 历史列表 |
| GET | `/api/threads/{thread_id}/runs/{run_id}` | 获取单个 Run 的详细信息 |
| GET | `/api/threads/{thread_id}/runs/{run_id}/events` | 获取 Run 的完整事件流（调试/审计） |

### Feedback（反馈）端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/threads/{thread_id}/runs/{run_id}/feedback` | 创建反馈 |
| GET | `/api/threads/{thread_id}/runs/{run_id}/feedback` | 获取反馈列表 |
| PUT | `/api/threads/{thread_id}/runs/{run_id}/feedback` | 更新反馈 |
| DELETE | `/api/threads/{thread_id}/runs/{run_id}/feedback` | 删除反馈 |
| GET | `/api/threads/{thread_id}/runs/{run_id}/feedback/stats` | 获取反馈统计 |
| GET | `/api/runs/{run_id}/feedback` | 获取 Run 反馈（跨 Thread） |

---

## 2. SSE 流式输出的完整事件类型

当使用 `POST /api/threads/{thread_id}/runs/stream` 时，SSE 流返回以下事件类型：

### 事件类型详解

| 事件类型 | 说明 | 典型用途 |
|----------|------|----------|
| `values` | 完整状态快照 | 更新 UI 状态（标题、消息列表、Artifact） |
| `messages` | 增量消息/工具调用 | 实时显示 AI 回复、工具调用进度 |
| `custom` | 自定义事件 | 显示 Artifact、特殊内容 |
| `end` | 流结束 | 标记对话完成，可显示跟进建议 |

### SSE 事件格式示例

```text
event: values
data: {"values": {"messages": [...], "title": "文档分析", "artifacts": [...]}}

event: messages
data: {"type": "human", "content": "帮我分析这份PDF"}

event: messages
data: {"type": "ai", "content": "我来帮你分析这份文档..."}

event: messages
data: {"type": "ai", "content": "首先，让我读取文档内容..."}

event: messages
data: {"type": "tool_call", "name": "read_file", "input": {"path": "/mnt/user-data/uploads/doc.pdf"}}

event: messages
data: {"type": "tool_result", "tool_call_id": "abc123", "content": "文档内容..."}

event: messages
data: {"type": "ai", "content": "根据文档内容，我发现了以下几点..."}

event: custom
data: {"type": "artifact", "data": {"path": "/mnt/user-data/outputs/summary.md"}}

event: end
data: {"run_id": "run456", "usage": {"total_tokens": 12345}}
```

---

## 3. 会话结束后获取输出

### 获取 Thread 完整状态

```http
GET /api/threads/{thread_id}/state
```

**响应：**
```json
{
  "values": {
    "messages": [
      {"type": "human", "content": "帮我分析这份文档"},
      {"type": "ai", "content": "我来帮你分析..."},
      {"type": "tool", "name": "bash", "content": "ls /mnt/user-data"},
      {"type": "ai", "content": "根据分析结果..."}
    ],
    "artifacts": [
      {
        "path": "/mnt/user-data/outputs/summary.md",
        "type": "text"
      }
    ],
    "title": "文档分析",
    "todos": [],
    "thread_data": {}
  },
  "next": [],
  "metadata": {
    "created_at": "2024-01-15T10:30:00Z",
    "checkpoint_id": "1a2b3c"
  },
  "checkpoint_id": "1a2b3c"
}
```

### 获取消息历史

```http
GET /api/threads/{thread_id}/messages
```

**响应：**
```json
{
  "data": [
    {"type": "human", "content": "帮我分析这份文档", "id": "msg1"},
    {"type": "ai", "content": "我来帮你分析...", "id": "msg2"},
    {"type": "tool", "name": "bash", "content": "ls /mnt/user-data", "id": "msg3"},
    {"type": "ai", "content": "根据分析结果...", "id": "msg4"}
  ],
  "has_more": false
}
```

### 获取单个 Run 的详细信息

```http
GET /api/threads/{thread_id}/runs/{run_id}
```

**响应：**
```json
{
  "run_id": "run123",
  "status": "success",
  "created_at": "2024-01-15T10:30:00Z",
  "ended_at": "2024-01-15T10:31:00Z",
  "metadata": {
    "model_name": "deepseek-v3",
    "thinking_enabled": true
  }
}
```

### 获取 Run 的完整事件流（调试用）

```http
GET /api/threads/{thread_id}/runs/{run_id}/events
```

> 返回完整的调试事件序列，包含 LangGraph 内部的每一步操作。用于排查问题和审计。

---

## 3.5 历史会话浏览（Thread History）

### 获取当前用户的所有 Thread 列表

```http
POST /api/threads/search
Content-Type: application/json

{
  "limit": 20,
  "offset": 0
}
```

**响应：**
```json
{
  "threads": [
    {
      "thread_id": "abc123",
      "status": "idle",
      "created_at": "2024-01-15T10:30:00Z",
      "updated_at": "2024-01-15T11:00:00Z",
      "metadata": {},
      "values": {
        "title": "文档分析",
        "messages": [...]
      }
    },
    {
      "thread_id": "def456",
      "status": "idle",
      "created_at": "2024-01-14T09:00:00Z",
      "updated_at": "2024-01-14T09:30:00Z",
      "metadata": {},
      "values": {
        "title": "代码审查"
      }
    }
  ],
  "total": 50,
  "has_more": true
}
```

**查询参数说明：**

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `limit` | integer | 100 | 最大返回数量（最大 1000） |
| `offset` | integer | 0 | 分页偏移 |
| `metadata` | object | - | 按 metadata 精确过滤 |
| `status` | string | - | 按状态过滤：`idle` / `busy` / `interrupted` / `error` |

### 获取单个 Thread 信息

```http
GET /api/threads/{thread_id}
```

**响应：**
```json
{
  "thread_id": "abc123",
  "status": "idle",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T11:00:00Z",
  "metadata": {},
  "values": {
    "title": "文档分析",
    "messages": [...]
  },
  "interrupts": []
}
```

**Thread 状态说明：**

| 状态 | 说明 |
|------|------|
| `idle` | 空闲，等待用户输入 |
| `busy` | 正在处理请求 |
| `interrupted` | 被中断 |
| `error` | 执行出错 |

### 获取 Thread 的消息历史

```http
GET /api/threads/{thread_id}/messages
```

**响应：**
```json
{
  "data": [
    {"type": "human", "content": "帮我分析这份文档", "id": "msg1"},
    {"type": "ai", "content": "我来帮你分析...", "id": "msg2"},
    {"type": "tool", "name": "bash", "content": "ls /mnt/user-data", "id": "msg3"},
    {"type": "ai", "content": "根据分析结果...", "id": "msg4"}
  ],
  "has_more": false
}
```

**消息类型说明：**

| 类型 | 说明 |
|------|------|
| `human` | 用户消息 |
| `ai` | AI 回复 |
| `tool` | 工具调用结果 |
| `system` | 系统消息 |

### 获取 Thread 的历史快照（Checkpoint History）

```http
POST /api/threads/{thread_id}/history
Content-Type: application/json

{
  "limit": 10,
  "before": null
}
```

> 从检查点（checkpoint）读取历史状态快照，用于回溯会话在某个时间点的完整状态。

**响应：**
```json
{
  "checkpoints": [
    {
      "checkpoint_id": "1a2b3c",
      "created_at": "2024-01-15T10:30:00Z",
      "values": {
        "messages": [
          {"type": "human", "content": "第一轮对话"}
        ],
        "title": "新会话"
      }
    },
    {
      "checkpoint_id": "4d5e6f",
      "created_at": "2024-01-15T10:35:00Z",
      "values": {
        "messages": [
          {"type": "human", "content": "第一轮对话"},
          {"type": "ai", "content": "第一轮回复"}
        ],
        "title": "新会话"
      }
    }
  ],
  "has_more": true,
  "next_cursor": "4d5e6f"
}
```

**分页参数说明：**

| 字段 | 说明 |
|------|------|
| `limit` | 最大返回数量（最大 100） |
| `before` | 分页游标，传入上一次返回的 `next_cursor` 获取更早的数据 |

### 获取 Thread 的所有 Run 历史

```http
GET /api/threads/{thread_id}/runs
```

**响应：**
```json
{
  "runs": [
    {
      "run_id": "run001",
      "status": "success",
      "created_at": "2024-01-15T10:30:00Z",
      "ended_at": "2024-01-15T10:31:00Z"
    },
    {
      "run_id": "run002",
      "status": "success",
      "created_at": "2024-01-15T10:32:00Z",
      "ended_at": "2024-01-15T10:33:00Z"
    }
  ]
}
```

### 获取指定 Run 的消息

```http
GET /api/threads/{thread_id}/runs/{run_id}/messages
```

**响应格式同 `/messages`，但仅返回该 Run 相关的消息。**

---

## 4. Artifact（生成文件）访问

### 获取 Artifact 文件内容

```http
GET /api/threads/{thread_id}/artifacts/mnt/user-data/outputs/summary.md
```

**Content-Type 处理策略：**

| 文件类型 | 处理方式 | 说明 |
|----------|----------|------|
| HTML / XHTML / SVG | **强制下载** | 防止 XSS 安全问题 |
| 文本文件（.md, .txt, .json 等） | 内联显示 | 返回纯文本 |
| 二进制文件 | 浏览器默认处理 | PDF、图片等 |
| `.skill` 压缩包内文件 | 提取并返回 | 支持预览 SKILL.md 等 |

**查询参数：**
- `download=true` — 强制下载而非内联显示

### Artifact 路径格式

```
/api/threads/{thread_id}/artifacts/{virtual_path}
```

| 文件位置 | virtual_path 示例 |
|----------|------------------|
| 上传目录 | `mnt/user-data/uploads/document.pdf` |
| 工作区 | `mnt/user-data/workspace/temp.txt` |
| 输出目录 | `mnt/user-data/outputs/summary.md` |

---

## 5. Token 使用统计

### 获取 Token 使用统计

```http
GET /api/threads/{thread_id}/token-usage
```

**响应：**
```json
{
  "thread_id": "abc123",
  "total_tokens": 125000,
  "total_input_tokens": 98000,
  "total_output_tokens": 27000,
  "total_runs": 5,
  "by_model": {
    "deepseek-v3": {
      "tokens": 125000,
      "runs": 5
    }
  },
  "by_caller": {
    "lead_agent": 120000,
    "subagent": 5000,
    "middleware": 0
  }
}
```

---

## 6. 跟进建议（Suggestions）

### 生成跟进问题

```http
POST /api/threads/{thread_id}/suggestions
```

**响应：**
```json
{
  "suggestions": [
    "你能详细解释第一点吗？",
    "能否生成一个可视化的图表？",
    "把结论总结成一段话"
  ]
}
```

> 由 LLM 根据当前对话上下文生成，帮助用户继续探索或深入了解。

---

## 7. Feedback（用户反馈）

### 创建反馈

```http
POST /api/threads/{thread_id}/runs/{run_id}/feedback
Content-Type: application/json

{
  "rating": 1,
  "comment": "回答很详细，但可以更简洁一些",
  "message_id": "msg4"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `rating` | integer | **必填**：`+1`（好评）或 `-1`（差评） |
| `comment` | string | 可选的文字评论 |
| `message_id` | string | 可选，将反馈限定到特定消息 |

**响应：**
```json
{
  "feedback_id": "fb001",
  "run_id": "run123",
  "thread_id": "abc123",
  "user_id": "user1",
  "message_id": "msg4",
  "rating": 1,
  "comment": "回答很详细，但可以更简洁一些",
  "created_at": "2024-01-15T11:00:00Z"
}
```

### 获取反馈列表

```http
GET /api/threads/{thread_id}/runs/{run_id}/feedback
```

**响应：**
```json
[
  {
    "feedback_id": "fb001",
    "run_id": "run123",
    "thread_id": "abc123",
    "rating": 1,
    "comment": "回答很详细",
    "created_at": "2024-01-15T11:00:00Z"
  }
]
```

### 获取反馈统计

```http
GET /api/threads/{thread_id}/runs/{run_id}/feedback/stats
```

**响应：**
```json
{
  "run_id": "run123",
  "total": 10,
  "positive": 8,
  "negative": 2
}
```

### 更新反馈

```http
PUT /api/threads/{thread_id}/runs/{run_id}/feedback
Content-Type: application/json

{
  "rating": -1,
  "comment": "修改后的反馈"
}
```

### 删除反馈

```http
DELETE /api/threads/{thread_id}/runs/{run_id}/feedback
```

---

## 8. 完整调用序列

```
┌─────────────────────────────────────────────────────────────────┐
│                     SSE 流式输出阶段                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Client ──► POST /runs/stream ──► Gateway ──► LangGraph          │
│             Accept: text/event-stream     │                     │
│                                          ▼                      │
│             ◄── event: values ──────────────────────────────────┤
│             ◄── event: messages ── (AI 回复增量) ───────────────┤
│             ◄── event: messages ── (工具调用) ───────────────────┤
│             ◄── event: messages ── (工具结果) ──────────────────┤
│             ◄── event: custom ──── (Artifact) ──────────────────┤
│             ◄── event: end ─────────────────────────────────────┤
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     会话结束后查询阶段                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Client ──► GET /state ─────────────────────────────────────────┤
│             ◄── {values: {messages, artifacts, title}} ────────│
│                                                                  │
│  Client ──► GET /messages ──────────────────────────────────────┤
│             ◄── {data: [...]} ───────────────────────────────────┤
│                                                                  │
│  Client ──► GET /artifacts/{path} ───────────────────────────────┤
│             ◄── file content ───────────────────────────────────┤
│                                                                  │
│  Client ──► GET /token-usage ───────────────────────────────────┤
│             ◄── {total_tokens, by_model, by_caller} ─────────────┤
│                                                                  │
│  Client ──► POST /suggestions ──────────────────────────────────┤
│             ◄── {suggestions: [...]} ───────────────────────────┤
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                       反馈阶段                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Client ──► POST /runs/{run_id}/feedback ───────────────────────┤
│             {rating: 1, comment: "..."}                          │
│             ◄── {feedback_id, ...} ─────────────────────────────┤
│                                                                  │
│  Client ──► GET /runs/{run_id}/feedback ────────────────────────┤
│             ◄── [{feedback_id, rating, ...}] ───────────────────┤
│                                                                  │
│  Client ──► GET /runs/{run_id}/feedback/stats ─────────────────┤
│             ◄── {total, positive, negative} ────────────────────┤
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 9. cURL 快速测试

```bash
# 获取 Thread 状态
curl http://localhost:2026/api/threads/abc123/state

# 获取消息历史
curl http://localhost:2026/api/threads/abc123/messages

# 获取 Artifact 文件
curl http://localhost:2026/api/threads/abc123/artifacts/mnt/user-data/outputs/result.md

# 获取 Token 使用统计
curl http://localhost:2026/api/threads/abc123/token-usage

# 生成跟进建议
curl -X POST http://localhost:2026/api/threads/abc123/suggestions

# 创建反馈
curl -X POST http://localhost:2026/api/threads/abc123/runs/run123/feedback \
  -H "Content-Type: application/json" \
  -d '{"rating": 1, "comment": "回答很好"}'

# 获取反馈列表
curl http://localhost:2026/api/threads/abc123/runs/run123/feedback

# 获取反馈统计
curl http://localhost:2026/api/threads/abc123/runs/run123/feedback/stats

# 获取单个 Run 信息
curl http://localhost:2026/api/threads/abc123/runs/run123

# 获取 Run 列表
curl http://localhost:2026/api/threads/abc123/runs

# 获取完整事件流（调试）
curl http://localhost:2026/api/threads/abc123/runs/run123/events
```

---

## 10. Python SDK 示例

```python
from deerflow import DeerFlowClient

client = DeerFlowClient()
thread_id = "abc123"

# 获取 Thread 完整状态
state = client.get_thread_state(thread_id)
print(f"Title: {state['values']['title']}")
print(f"Messages: {len(state['values']['messages'])}")
print(f"Artifacts: {state['values'].get('artifacts', [])}")

# 获取消息历史
messages = client.get_messages(thread_id)
for msg in messages["data"]:
    print(f"[{msg['type']}] {msg.get('content', '')[:50]}...")

# 获取 Token 统计
usage = client.get_token_usage(thread_id)
print(f"Total tokens: {usage['total_tokens']}")
print(f"By model: {usage['by_model']}")

# 生成跟进建议
suggestions = client.get_suggestions(thread_id)
print(f"Suggestions: {suggestions['suggestions']}")

# 提交反馈
feedback = client.create_feedback(
    thread_id=thread_id,
    run_id="run123",
    rating=1,
    comment="回答很有帮助"
)
print(f"Feedback ID: {feedback['feedback_id']}")

# 获取 Artifact 内容
content, mime_type = client.get_artifact(
    thread_id,
    "mnt/user-data/outputs/summary.md"
)
print(f"Content: {content[:100]}...")

# 获取反馈统计
stats = client.get_feedback_stats(thread_id, "run123")
print(f"Stats: {stats}")
```

---

## 11. Frontend 显示建议

### 推荐的数据获取策略

1. **流式显示**：使用 SSE 流实时显示 AI 回复
   - 监听 `messages` 事件增量更新
   - 监听 `values` 事件更新完整状态

2. **完成后获取**：会话完成后获取完整信息
   - 调用 `/state` 获取完整上下文
   - 调用 `/token-usage` 显示 Token 消耗

3. **按需加载**：用户交互时才获取
   - 点击 Artifact 才调用 `/artifacts/{path}`
   - 用户想继续时才调用 `/suggestions`

### 典型 UI 组件

| UI 组件 | 数据来源 |
|--------|----------|
| 消息列表 | SSE `messages` 事件 或 `/messages` |
| 标题 | SSE `values.title` 或 `/state` |
| 文件列表 | SSE `values.artifacts` 或 `/state` |
| Token 消耗 | `/token-usage` |
| 跟进问题 | `/suggestions` |
| 反馈按钮 | 提交到 `/feedback` |
