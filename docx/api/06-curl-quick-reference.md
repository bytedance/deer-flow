# DeerFlow curl 快速参考

本文档提供 DeerFlow REST API 的 curl 命令示例，基于实际验证。

**Base URL**: `http://localhost:2026`

---

## 前置条件

登录后 cookie 保存在 `/tmp/cookies.txt`，后续请求需要带上 CSRF token。

```bash
# 提取 CSRF token（后续命令需要）
CSRF=$(grep "csrf_token" /tmp/cookies.txt | awk '{print $7}')
```

---

## 1. 登录

```bash
curl -c /tmp/cookies.txt -X POST http://localhost:2026/api/v1/auth/login/local \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=raidery%40gmail.com&password=Pass1234"
```

**响应**:
```json
{"expires_in":604800,"needs_setup":false}
```

> 注意：登录使用 `application/x-www-form-urlencoded`，不是 JSON。

---

## 2. 创建 Thread

```bash
curl -b /tmp/cookies.txt -X POST http://localhost:2026/api/threads \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{}'
```

**响应**:
```json
{
  "thread_id": "1443d699-9e03-4e45-b6cf-f1d850b06218",
  "status": "idle",
  "created_at": "2026-05-29T02:52:46.762398+00:00",
  ...
}
```

---

## 3. 提问（流式 SSE）

把 `{thread_id}` 替换为第2步返回的 `thread_id`。

```bash
curl -b /tmp/cookies.txt -X POST http://localhost:2026/api/threads/{thread_id}/runs/stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "什么是deerflow"}]},
    "stream_mode": ["values", "messages-tuple", "custom"]
  }'
```

**SSE 响应格式**:
```
event: metadata
data: {"run_id": "...", "thread_id": "..."}

event: values
data: {"messages": [...], "title": "..."}

event: messages
data: {"content": "DeerFlow 是一个开源的 AI Agent 框架...", "type": "ai"}

event: end
data: {}
```

---

## 4. 获取历史消息

```bash
curl -b /tmp/cookies.txt http://localhost:2026/api/threads/{thread_id}/messages \
  -H "X-CSRF-Token: $CSRF"
```

**响应**:
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

## 5. 获取可用模型

```bash
curl -b /tmp/cookies.txt http://localhost:2026/api/models \
  -H "X-CSRF-Token: $CSRF"
```

**响应**:
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
3. **Content-Type**: 登录用 `application/x-www-form-urlencoded`，其他用 `application/json`
4. **HttpOnly Cookie**: `access_token` 无法被 JavaScript 读取，安全但需用 curl 管理

---

## 完整流程汇总

```bash
# 1. 登录（保存 cookie）
curl -c /tmp/cookies.txt -X POST http://localhost:2026/api/v1/auth/login/local \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=raidery%40gmail.com&password=Pass1234"

# 2. 创建 Thread
CSRF=$(grep "csrf_token" /tmp/cookies.txt | awk '{print $7}')
curl -b /tmp/cookies.txt -X POST http://localhost:2026/api/threads \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{}'

# 3. 提问（替换 {thread_id}）
curl -b /tmp/cookies.txt -X POST http://localhost:2026/api/threads/{thread_id}/runs/stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "什么是deerflow"}]},
    "stream_mode": ["values", "messages-tuple", "custom"]
  }'
```