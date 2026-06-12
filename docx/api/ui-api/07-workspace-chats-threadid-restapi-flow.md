# 工作区 Chat 页面 REST API 调用流程

> 目标 URL：`http://localhost:2026/workspace/chats/94a82533-9527-4f95-bea5-c73a20b54411`
> 范围：从用户浏览器访问到页面就绪（无任何用户交互）所触发的全部 REST API。

---

## 一、完整流程图

```
用户浏览器: GET http://localhost:2026/workspace/chats/94a82533-9527-4f95-bea5-c73a20b54411
   │
   ▼
┌────────────────────────────────────────────────────────────┐
│ ① SSR (Next.js 服务端渲染 workspace/layout.tsx)            │
│    getServerSideUser()                                      │
└────────────────────────────────────────────────────────────┘
   │  GET /api/v1/auth/me
   ▼
[返回用户信息]  →  渲染 HTML 发送给浏览器
   │
   ▼
┌────────────────────────────────────────────────────────────┐
│ ② 客户端 Hydration (React 接管)                            │
│    QueryClientProvider 初始化                                │
│    ChatProviders 包裹 (Subtasks/Artifacts/PromptInput)      │
└────────────────────────────────────────────────────────────┘
   │
   ▼
┌────────────────────────────────────────────────────────────┐
│ ③ WorkspaceSidebar 挂载 → RecentChatList 渲染               │
│    useThreads()                                            │
└────────────────────────────────────────────────────────────┘
   │  POST /api/langgraph/threads/search
   ▼
┌────────────────────────────────────────────────────────────┐
│ ④ ChatPage 挂载                                            │
│    useThreadChat()        → 解析 URL 中 thread_id (无 API)  │
│    useThreadSettings()    → 本地状态 (无 API)                │
│    useLocalSettings()     → 本地状态 (无 API)                │
│    useModels()                                              │
└────────────────────────────────────────────────────────────┘
   │  GET /api/models
   ▼
┌────────────────────────────────────────────────────────────┐
│ ⑤ useThreadTokenUsage() (若 token_usage 开关开启)            │
└────────────────────────────────────────────────────────────┘
   │  GET /api/threads/{id}/token-usage
   ▼
┌────────────────────────────────────────────────────────────┐
│ ⑥ useThreadStream()                                        │
│    ├─ useStream (LangGraph SDK)                             │
│    │   ├─ fetchStateHistory                                 │
│    │   └─ reconnectOnMount=true → join active run            │
│    └─ useThreadHistory()                                    │
│        ├─ useThreadRuns()                                   │
│        └─ 对每个未加载的 run 拉取消息                        │
└────────────────────────────────────────────────────────────┘
   │  ┌─ GET /api/langgraph/threads/{id}/state
   │  ├─ POST /api/langgraph/threads/{id}/history
   │  ├─ GET /api/langgraph/threads/{id}/runs/{run_id}/stream  (若有活跃 run)
   │  ├─ GET /api/langgraph/threads/{id}/runs
   │  └─ GET /api/threads/{id}/runs/{run_id}/messages (N 次)
   ▼
[页面就绪,显示历史消息,等待用户输入]
```

---

## 二、关键说明

- **`/api/langgraph/*` 路径**经 nginx 改写为 `/api/*` 后转发到 Gateway：
  ```nginx
  location /api/langgraph/ {
      rewrite ^/api/langgraph/(.*) /api/$1 break;
  }
  ```
- **POST / PUT / DELETE / PATCH 请求**自动注入 `X-CSRF-Token` 头（来自 `csrf_token` cookie）。
- **所有请求**自动带 `Cookie: access_token=...` （HttpOnly 登录态）。
- **401 响应**自动重定向到 `/login`。
- **`useStream`** 是 `@langchain/langgraph-sdk/react` 的 React Hook，base URL 由 `getLangGraphBaseURL()` 拼出。

---

## 三、每一步的 curl 命令

### 3.1 前置：登录并保存 Cookie

```bash
# 登录获取 access_token + csrf_token
curl -c /tmp/cookies.txt -X POST "http://localhost:2026/api/v1/auth/login/local" \
  -d "username=raidery@gmail.com&password=Pass1234" -s

# 提取 CSRF token（用于 POST/PUT/DELETE）
CSRF=$(awk '/csrf_token/ {print $7}' /tmp/cookies.txt)
THREAD_ID="94a82533-9527-4f95-bea5-c73a20b54411"
```

> 注：CSRF 中间件只对 POST/PUT/DELETE/PATCH 强制要求 `X-CSRF-Token` 头。

### 3.2 ① SSR 服务端：`getServerSideUser()`

```bash
# Next.js 服务端使用 cookie 转发到后端
curl -b /tmp/cookies.txt -s "http://localhost:2026/api/v1/auth/me"
```

### 3.3 ② 客户端 hydration（无 API）

无网络请求。

### 3.4 ③ RecentChatList 侧边栏：`useThreads()`

```bash
# POST /api/langgraph/threads/search
# 实际经 nginx 改写到 POST /api/threads/search
curl -b /tmp/cookies.txt -X POST "http://localhost:2026/api/langgraph/threads/search" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{
    "limit": 50,
    "sort_by": "updated_at",
    "sort_order": "desc",
    "select": ["thread_id","updated_at","values","metadata"]
  }'
```

### 3.5 ④ ChatPage：`useModels()`

```bash
# GET /api/models
curl -b /tmp/cookies.txt -s "http://localhost:2026/api/models"
```

### 3.6 ⑤ ChatPage：`useThreadTokenUsage()`（按需）

```bash
# GET /api/threads/{id}/token-usage
# 只有当 /api/models 返回 token_usage.enabled=true 时才调用
curl -b /tmp/cookies.txt -s \
  "http://localhost:2026/api/threads/${THREAD_ID}/token-usage"
```

### 3.7 ⑥ `useThreadStream()` — `useStream` (LangGraph SDK)

```bash
# 6.1 GET /api/langgraph/threads/{id}/state   (取最新 state)
curl -b /tmp/cookies.txt -s \
  "http://localhost:2026/api/langgraph/threads/${THREAD_ID}/state"

# 6.2 POST /api/langgraph/threads/{id}/history  (fetchStateHistory: { limit: 1 })
curl -b /tmp/cookies.txt -X POST \
  "http://localhost:2026/api/langgraph/threads/${THREAD_ID}/history" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{"limit": 1}'

# 6.3 GET /api/langgraph/threads/{id}/runs/{run_id}/stream
#     (reconnectOnMount=true 且存在活跃 run 时；返回 text/event-stream)
curl -b /tmp/cookies.txt -N -s \
  "http://localhost:2026/api/langgraph/threads/${THREAD_ID}/runs/<active_run_id>/stream"
```

### 3.8 ⑥ `useThreadStream()` — `useThreadHistory()` → `useThreadRuns()`

```bash
# 6.4 GET /api/langgraph/threads/{id}/runs
curl -b /tmp/cookies.txt -s \
  "http://localhost:2026/api/langgraph/threads/${THREAD_ID}/runs"
```

返回示例（本线程有两个 run）：

```json
[
  {"run_id":"7faf5fbd-0971-43e9-be64-44fc3bd8bdeb", ...},
  {"run_id":"3217c233-345f-4824-83ed-93968c7333b5", ...}
]
```

### 3.9 ⑥ `useThreadStream()` — 对每个 run 拉取消息

```bash
# 6.5 GET /api/threads/{id}/runs/{run_id}/messages   (每个 run 一次)
RUN_ID_1="7faf5fbd-0971-43e9-be64-44fc3bd8bdeb"
RUN_ID_2="3217c233-345f-4824-83ed-93968c7333b5"

curl -b /tmp/cookies.txt -s \
  "http://localhost:2026/api/threads/${THREAD_ID}/runs/${RUN_ID_1}/messages"

curl -b /tmp/cookies.txt -s \
  "http://localhost:2026/api/threads/${THREAD_ID}/runs/${RUN_ID_2}/messages"
```

---

## 四、一键脚本（按顺序自动执行）

```bash
#!/bin/bash
set -e
BASE="http://localhost:2026"
THREAD_ID="94a82533-9527-4f95-bea5-c73a20b54411"

# 登录
curl -c /tmp/cookies.txt -s -X POST "$BASE/api/v1/auth/login/local" \
  -d "username=raidery@gmail.com&password=Pass1234" > /dev/null
CSRF=$(awk '/csrf_token/ {print $7}' /tmp/cookies.txt)

echo "=== ① SSR auth ==="
curl -b /tmp/cookies.txt -s "$BASE/api/v1/auth/me" | head -c 200; echo

echo "=== ③ useThreads() 侧边栏 ==="
curl -b /tmp/cookies.txt -s -X POST "$BASE/api/langgraph/threads/search" \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $CSRF" \
  -d '{"limit":50,"sort_by":"updated_at","sort_order":"desc","select":["thread_id","updated_at","values","metadata"]}' | head -c 200; echo

echo "=== ④ useModels() ==="
curl -b /tmp/cookies.txt -s "$BASE/api/models" | head -c 200; echo

echo "=== ⑤ useThreadTokenUsage() ==="
curl -b /tmp/cookies.txt -s "$BASE/api/threads/${THREAD_ID}/token-usage" | head -c 200; echo

echo "=== ⑥.1 useStream /state ==="
curl -b /tmp/cookies.txt -s "$BASE/api/langgraph/threads/${THREAD_ID}/state" | head -c 200; echo

echo "=== ⑥.2 useStream /history ==="
curl -b /tmp/cookies.txt -s -X POST "$BASE/api/langgraph/threads/${THREAD_ID}/history" \
  -H "Content-Type: application/json" -H "X-CSRF-Token: $CSRF" \
  -d '{"limit":1}' | head -c 200; echo

echo "=== ⑥.4 useThreadRuns() ==="
RUNS_JSON=$(curl -b /tmp/cookies.txt -s "$BASE/api/langgraph/threads/${THREAD_ID}/runs")
echo "$RUNS_JSON" | head -c 200; echo

echo "=== ⑥.5 对每个 run 取 messages ==="
echo "$RUNS_JSON" | python3 -c "
import json,sys
runs=json.load(sys.stdin)
for r in runs:
    print('  run_id =', r['run_id'])
"

echo "$RUNS_JSON" | python3 -c "
import json,sys,subprocess
runs=json.load(sys.stdin)
for r in runs:
    url=f\"$BASE/api/threads/${THREAD_ID}/runs/{r['run_id']}/messages\"
    out=subprocess.run(['curl','-b','/tmp/cookies.txt','-s',url],capture_output=True,text=True)
    print(f'--- {r[\"run_id\"]} ---')
    print(out.stdout[:200])
"
```

执行结果会按 ① → ③ → ④ → ⑤ → ⑥.1 → ⑥.2 → ⑥.4 → ⑥.5 的顺序依次输出每个 API 的真实响应。

---

## 五、用户后续操作触发的额外 API（参考）

| 操作 | API |
|---|---|
| 发送消息 | `POST /api/langgraph/threads/{id}/runs/stream` (SSE) |
| 停止生成 | `POST /api/langgraph/threads/{id}/runs/{run_id}/cancel` |
| 重命名 | `POST /api/langgraph/threads/{id}/state` |
| 删除 | `DELETE /api/langgraph/threads/{id}` + `DELETE /api/threads/{id}` |
| 反馈打分 | `PUT /api/threads/{id}/runs/{run_id}/feedback` |
| 导出 | `GET /api/langgraph/threads/{id}/state` |
| 上传文件 | `POST /api/threads/{id}/uploads` |
| 下载文件 | `GET /api/threads/{id}/uploads/list`、`GET /api/threads/{id}/artifacts/...` |
