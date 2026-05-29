# DeerFlow 快捷入口提示词规范

第三方开发者在调用 DeerFlow REST API 时，使用以下提示词即可路由到对应的 Skill 或 Dify Workflow。

---

## 快捷入口提示词

| 入口 | 提示词模板 |
|------|-----------|
| 数据分析 | `请使用数据分析技能，简单分析：{用户输入}` |
| AI写作 | `请使用AI写作工作流，帮助我完成以下写作任务：\n{用户输入}` |
| 文档检验 | `请使用文档校验工作流，检验以下文档：\n{用户输入}` |
| 图片识别 | `请使用图片识别工作流，识别图片内容：\n{用户输入}` |

---

## 数据分析使用说明

### 第一轮（简单分析）

用户点击"数据分析"入口后，第一轮使用简单分析提示词：

```
请使用数据分析技能，简单分析一下：{用户需求}
```

### 第二轮及后续（深入分析）

如果用户需要更深入的分析，直接在对话中提出即可，无需特殊提示词。例如：

```
用户：请更详细地分析第二部分的数据
用户：能否做一个趋势预测
用户：把分析结果导出为报告
```

---

## REST API 调用示例

**Base URL**: `http://localhost:2026`

**接口**：`POST /api/threads/{thread_id}/runs/stream`

### 数据分析

```json
{
  "input": {
    "messages": [{
      "role": "user",
      "content": "请使用数据分析技能，简单分析：帮我分析这份销售数据"
    }]
  },
  "stream_mode": ["values", "messages-tuple", "custom"]
}
```

### AI写作

```json
{
  "input": {
    "messages": [{
      "role": "user",
      "content": "请使用AI写作工作流，帮助我完成以下写作任务：\n帮我写一篇关于人工智能的博客文章"
    }]
  },
  "stream_mode": ["values", "messages-tuple", "custom"]
}
```

### 文档检验

```json
{
  "input": {
    "messages": [{
      "role": "user",
      "content": "请使用文档校验工作流，检验以下文档：\n帮我校验这份合同文档"
    }]
  },
  "stream_mode": ["values", "messages-tuple", "custom"]
}
```

### 图片识别

```json
{
  "input": {
    "messages": [{
      "role": "user",
      "content": "请使用图片识别工作流，识别图片内容：\n识别这张发票图片中的文字"
    }]
  },
  "stream_mode": ["values", "messages-tuple", "custom"]
}
```

---

## 提示词组合方式

建议采用追加模式：用户输入内容追加在提示词模板之后。

```
用户输入："我想写一篇关于AI的博客"
快捷入口提示词模板："请使用AI写作工作流，帮助我完成以下写作任务："

实际发送：
"请使用AI写作工作流，帮助我完成以下写作任务：
我想写一篇关于AI的博客"
```

---

## 五大快捷操作 API

### 1. 发送对话

**接口**：`POST /api/threads/{thread_id}/runs/stream`

流式发送消息并接收 AI 回复：

```http
POST /api/threads/{thread_id}/runs/stream
Content-Type: application/json
Accept: text/event-stream

{
  "input": {
    "messages": [{"role": "user", "content": "请使用数据分析技能，简单分析：帮我分析这份销售数据"}]
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

**SSE 响应格式：**

```
event: values
data: {"values": {"messages": [...], "title": "..."}}

event: messages
data: {"type": "ai", "content": "我来帮你分析..."}

event: messages
data: {"type": "tool_call", "name": "read_file", "input": {...}}

event: messages
data: {"type": "tool_result", "tool_call_id": "abc123", "content": "..."}

event: custom
data: {"type": "artifact", "data": {...}}

event: end
data: {"run_id": "run456", "usage": {"total_tokens": 12345}}
```

### 2. 显示输出信息

**接口**：`GET /api/threads/{thread_id}/state`

获取 Thread 完整状态（含消息、Artifact、标题）：

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
  "checkpoint_id": "1a2b3c"
}
```

### 3. 上传文件

**接口**：`POST /api/threads/{thread_id}/uploads`

上传文件到 Thread（支持 PDF、PPT、Excel、Word，自动转换为 Markdown）：

```http
POST /api/threads/{thread_id}/uploads
Content-Type: multipart/form-data

files: @document.pdf
files: @data.xlsx
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
    },
    {
      "filename": "data.xlsx",
      "size": 98765,
      "virtual_path": "/mnt/user-data/uploads/data.xlsx",
      "markdown_file": "data.md",
      "markdown_virtual_path": "/mnt/user-data/uploads/data.md"
    }
  ],
  "message": "Successfully uploaded 2 file(s)"
}
```

**文件如何传递给 Agent：**

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

### 4. 显示历史对话

**接口**：`GET /api/threads/{thread_id}/messages`

获取消息列表：

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

**获取当前用户的所有 Thread 列表：**

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
      "values": {
        "title": "文档分析",
        "messages": [...]
      }
    }
  ],
  "total": 50,
  "has_more": true
}
```

### 5. 生成建议

**接口**：`POST /api/threads/{thread_id}/suggestions`

生成跟进问题建议：

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

## 完整调用序列

```
┌─────────────────────────────────────────────────────────────────┐
│                       快捷入口操作流程                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. 发送对话                                                     │
│  Client ──► POST /api/threads/{thread_id}/runs/stream           │
│             ◄── SSE stream (values, messages, custom, end)     │
│                                                                  │
│  2. 显示输出信息                                                 │
│  Client ──► GET /api/threads/{thread_id}/state                  │
│             ◄── {values: {messages, artifacts, title}}         │
│                                                                  │
│  3. 上传文件                                                     │
│  Client ──► POST /api/threads/{thread_id}/uploads               │
│             ◄── {success: true, files: [...]}                   │
│                                                                  │
│  4. 显示历史对话                                                 │
│  Client ──► GET /api/threads/{thread_id}/messages               │
│             ◄── {data: [...]}                                   │
│                                                                  │
│  5. 生成建议                                                     │
│  Client ──► POST /api/threads/{thread_id}/suggestions           │
│             ◄── {suggestions: [...]}                            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## cURL 快速测试

```bash
# 1. 发送对话并流式接收
curl -X POST http://localhost:2026/api/threads/{thread_id}/runs/stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "请使用数据分析技能，简单分析：帮我分析这份销售数据"}]},
    "stream_mode": ["values", "messages-tuple", "custom"]
  }'

# 2. 显示输出信息
curl http://localhost:2026/api/threads/{thread_id}/state

# 3. 上传文件
curl -X POST http://localhost:2026/api/threads/{thread_id}/uploads \
  -F "files=@/path/to/document.pdf"

# 4. 显示历史对话
curl http://localhost:2026/api/threads/{thread_id}/messages

# 5. 生成建议
curl -X POST http://localhost:2026/api/threads/{thread_id}/suggestions
```

---

## Python SDK 示例

```python
from deerflow import DeerFlowClient

client = DeerFlowClient()
thread_id = "abc123"

# 1. 发送对话
response = client.run_stream(
    thread_id,
    messages=[{"role": "user", "content": "请使用数据分析技能，简单分析：帮我分析这份销售数据"}],
    stream_mode=["values", "messages-tuple", "custom"]
)
for event in response:
    print(event)

# 2. 显示输出信息
state = client.get_thread_state(thread_id)
print(f"Title: {state['values']['title']}")
print(f"Messages: {len(state['values']['messages'])}")
print(f"Artifacts: {state['values'].get('artifacts', [])}")

# 3. 上传文件
result = client.upload_files(thread_id, ["/path/to/document.pdf"])
print(result)

# 4. 显示历史对话
messages = client.get_messages(thread_id)
for msg in messages["data"]:
    print(f"[{msg['type']}] {msg.get('content', '')[:50]}...")

# 5. 生成建议
suggestions = client.get_suggestions(thread_id)
print(f"Suggestions: {suggestions['suggestions']}")
```

---

## Artifact（生成文件）访问

上传的文件和生成的输出文件都可通过 Artifact 端点访问：

```http
GET /api/threads/{thread_id}/artifacts/mnt/user-data/outputs/summary.md
```

**Content-Type 处理策略：**

| 文件类型 | 处理方式 |
|----------|----------|
| HTML / XHTML / SVG | **强制下载**（防止 XSS） |
| 文本文件（.md, .txt, .json 等） | 内联显示 |
| 二进制文件（.pdf, .xlsx 等） | 浏览器默认行为 |

**查询参数：**
- `download=true` — 强制下载而非浏览器内联显示