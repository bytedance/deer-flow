# DeerFlow curl 快速参考

本文档提供 DeerFlow REST API 的 curl 命令示例，基于实际验证。

**Base URL**: `http://localhost:2026`

---

## 前置条件

1. 登录后 cookie 保存在 `/tmp/cookies.txt`
2. 后续请求需要带上 CSRF token

```bash
# 登录前先清理旧 cookie
rm -f /tmp/cookies.txt

# 提取 CSRF token（用于后续请求）
CSRF=$(grep "csrf_token" /tmp/cookies.txt | awk '{print $7}')
```

---

## 1. 登录 (Teller 模式)

使用 `/api/v1/auth/login/local/teller` 端点登录。

- **请求方式**: POST
- **user 参数**: 通过 query string 传递，自动拼接为 `{user}@96262.com`
- **password**: 自动设为 `{user}-888`

```bash
curl -c /tmp/cookies.txt -X POST "http://localhost:2026/api/v1/auth/login/local/teller?user=A00010"
```

**响应示例**:
```json
{"success":true,"message":"User A00010 logged in successfully","expires_in":604800}
```

> ⚠️ 注意：这是 POST 请求，user 参数通过 query string 传递。

---

## 2. 提取 CSRF Token

登录成功后，从 cookie 文件中提取 CSRF token：

```bash
CSRF=$(grep "csrf_token" /tmp/cookies.txt | awk '{print $7}')
echo $CSRF
```

---

## 3. 创建 Thread

```bash
curl -b /tmp/cookies.txt -X POST http://localhost:2026/api/threads \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{}'
```

**响应示例**:
```json
{
  "thread_id": "d99a3b45-b077-486e-b183-80f667d181c0",
  "status": "idle",
  "created_at": "2026-05-29T06:54:11.934745+00:00",
  "updated_at": "2026-05-29T06:54:11.934745+00:00",
  "metadata": {},
  "values": {},
  "interrupts": {}
}
```

记录返回的 `thread_id`，用于后续请求。

---

## 4. 提问（流式 SSE）

使用第3步返回的 `thread_id` 发送问题：

```bash
# 假设 thread_id = e72e127e-cbfd-48f9-90e1-197e13897dd8
curl -b /tmp/cookies.txt -X POST http://localhost:2026/api/threads/e72e127e-cbfd-48f9-90e1-197e13897dd8/runs/stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "什么是deerflow"}]},
    "stream_mode": ["values", "messages-tuple", "custom"]
  }'
```

**SSE 响应格式说明**:

| Event | 说明 |
|-------|------|
| `metadata` | 包含 `run_id` 和 `thread_id` |
| `values` | 消息列表和线程数据 |
| `messages` | AI 响应内容，可能分多个 chunk 发送 |
| `end` | 流结束标记 |

**典型响应流程**:
```
event: metadata
data: {"run_id": "6e1dbbbe-af6f-4429-a8f2-dda06202569d", "thread_id": "e72e127e-cbfd-48f9-90e1-197e13897dd8"}

event: values
data: {"messages": [...], "thread_data": {...}, "artifacts": [], "viewed_images": {}}

event: messages
data: [{"type": "AIMessageChunk", "content": "<think>...", ...}, {...}]

event: messages
data: [{"type": "ai", "content": "DeerFlow 是一个开源的 AI Agent 框架...", "usage_metadata": {...}}]

event: end
data: {}
```

---

## 5. 获取历史消息

```bash
curl -b /tmp/cookies.txt http://localhost:2026/api/threads/e72e127e-cbfd-48f9-90e1-197e13897dd8/messages \
  -H "X-CSRF-Token: $CSRF"
```

**响应示例**:
```json
{
  "data": [
    {"type": "human", "content": "什么是deerflow"},
    {"type": "ai", "content": "DeerFlow 是一个开源的 AI Agent 框架..."}
  ],
  "has_more": false
}
```

---

## 6. 获取可用模型

```bash
curl -b /tmp/cookies.txt http://localhost:2026/api/models \
  -H "X-CSRF-Token: $CSRF"
```

**响应示例**:
```json
{
  "models": [
    {"name": "MiniMax-M27", "display_name": "MiniMax-M2.7", "supports_thinking": false},
    {"name": "deepseek-v4-flash", "display_name": "DeepSeek V4 Flash", "supports_thinking": true}
  ],
  "token_usage": {"enabled": false}
}
```

---

## 注意事项

1. **CSRF Token**: 除登录外，所有需要认证的请求都需要 `X-CSRF-Token` header
2. **Cookie**: `-b /tmp/cookies.txt` 自动带上 `access_token` 和 `csrf_token`
3. **Content-Type**: 登录（Teller 模式）为 POST + query string，其他为 `application/json`
4. **HttpOnly Cookie**: `access_token` 无法被 JavaScript 读取，安全但需用 curl 管理

---

## 完整流程汇总

```bash
#!/bin/bash

# 1. 登录（保存 cookie）
curl -c /tmp/cookies.txt -X POST "http://localhost:2026/api/v1/auth/login/local/teller?user=A00010"

# 2. 提取 CSRF token
CSRF=$(grep "csrf_token" /tmp/cookies.txt | awk '{print $7}')

# 3. 创建 Thread
echo "创建 Thread..."
THREAD_RESPONSE=$(curl -b /tmp/cookies.txt -X POST http://localhost:2026/api/threads \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{}')

echo "Thread 响应: $THREAD_RESPONSE"
THREAD_ID=$(echo $THREAD_RESPONSE | jq -r '.thread_id')
echo "Thread ID: $THREAD_ID"

# 4. 提问
echo "提问: 什么是deerflow"
curl -b /tmp/cookies.txt -X POST http://localhost:2026/api/threads/$THREAD_ID/runs/stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "什么是deerflow"}]},
    "stream_mode": ["values", "messages-tuple", "custom"]
  }'
```

> 💡 在实际使用时，只需将脚本中的 `user=A00010` 替换为实际的用户名即可。