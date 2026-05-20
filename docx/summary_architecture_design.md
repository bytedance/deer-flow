# DeerFlow 架构设计与优化方案

## 一、原始架构问题分析

| 原始设计 | 问题 | DeerFlow 实际方案 |
|---------|------|-----------------|
| Redis + Postgres 会话存储 | DeerFlow **不使用 Redis**，仅支持 Postgres/SQLite | langgraph store (Postgres/SQLite) |
| Kafka / Redis 任务队列 | DeerFlow **无 Kafka 依赖** | 内置 ThreadPoolExecutor |
| Ray / Celery Worker | DeerFlow **无 Ray/Celery** | SubagentExecutor (内置) |
| 独立 Session Service | Session 通过 langgraph store 管理 | Thread → Store 直接映射 |
| API Gateway (Auth/LB) | nginx 仅做反向代理，无认证 | 需额外组件或二次开发 |

---

## 二、修正后架构设计

```
┌──────────────────────────────────────────────────────────────────┐
│                        客户端层                                   │
│              Web / Mobile / IM Channels                          │
│           (Feishu / Slack / Telegram / WeChat)                   │
└────────────────────────────┬─────────────────────────────────────┘
                             │ SSE 流式 / REST
                             ↓
┌──────────────────────────────────────────────────────────────────┐
│                     nginx (port 2026)                            │
│              反向代理 + SSL终止 + 基础路由分发                        │
│                                                                     │
│   /api/langgraph/* → LangGraph Server (2024)                      │
│   /api/*          → Gateway API (8001)                             │
│   /               → Frontend (3000)                               │
└────────────────────────────┬─────────────────────────────────────┘
                             │
            ┌────────────────┴────────────────┐
            ↓                                 ↓
┌─────────────────────────┐     ┌─────────────────────────────────┐
│  LangGraph Server        │     │         Gateway API              │
│  (port 2024)             │     │  (port 8001, FastAPI)           │
│                          │     │                                  │
│  Lead Agent              │     │  ├─ /api/threads/*  (Thread CRUD)│
│  Middleware Chain (18)    │     │  ├─ /api/threads/{id}/runs/*    │
│  SubagentExecutor        │     │  ├─ /api/models/*   (模型配置)    │
│  Tools Registry          │     │  ├─ /api/mcp/*     (MCP管理)    │
│  Checkpointer/Store     │     │  ├─ /api/skills/*  (技能管理)    │
└─────────────────────────┘     │  ├─ /api/memory/*   (记忆系统)    │
                               │  ├─ /api/uploads/*  (文件上传)    │
                               │  └─ /api/channels/* (IM集成)      │
                               └──────────────┬──────────────────────┘
                                              │
                    ┌─────────────────────────┴────────────────────────┐
                    ↓                                                   ↓
     ┌─────────────────────────────┐           ┌─────────────────────────────┐
     │   Frontend (Next.js)        │           │   IM Channels              │
     │   (port 3000)               │           │   Feishu / Slack / etc.    │
     │                             │           └─────────────────────────────┘
     │  ├─ Chat UI                 │
     │  ├─ Workspace               │
     │  └─ BI Dashboard            │
     └─────────────────────────────┘

                              LangGraph Server 内部
     ┌─────────────────────────────────────────────────────────────────┐
     │                    Lead Agent (主调度Agent)                       │
     │  ┌─────────────────────────────────────────────────────────────┐ │
     │  │                   Middleware Chain (18个)                    │ │
     │  │                                                              │ │
     │  │  1. ThreadDataMiddleware    — 创建线程隔离目录               │ │
     │  │  2. UploadsMiddleware       — 注入上传文件                   │ │
     │  │  3. SandboxMiddleware       — 获取沙箱环境                   │ │
     │  │  4. DanglingToolCallMiddleware — 修复中断的ToolCalls       │ │
     │  │  5. LLMErrorHandlingMiddleware — 错误标准化                 │ │
     │  │  6. GuardrailMiddleware     — 预授权检查                    │ │
     │  │  7. SandboxAuditMiddleware  — 安全审计日志                │ │
     │  │  8. ToolErrorHandlingMiddleware — 异常转ToolMessage        │ │
     │  │  9. SummarizationMiddleware  — 上下文压缩                   │ │
     │  │  10. TodoListMiddleware      — 任务跟踪 (plan模式)          │ │
     │  │  11. TokenUsageMiddleware     — Token计量                   │ │
     │  │  12. TitleMiddleware         — 生成会话标题                 │ │
     │  │  13. MemoryMiddleware        — 异步记忆更新                 │ │
     │  │  14. ViewImageMiddleware     — 视觉模型图片注入             │ │
     │  │  15. DeferredToolFilterMiddleware — 隐藏延迟工具           │ │
     │  │  16. SubagentLimitMiddleware — 强制最多3并发子Agent        │ │
     │  │  17. LoopDetectionMiddleware  — 循环检测                    │ │
     │  │  18. ClarificationMiddleware  — 拦截澄清请求 (最后)        │ │
     │  └─────────────────────────────────────────────────────────────┘ │
     │                            ↓                                     │
     │  ┌─────────────────────────────────────────────────────────────┐│
     │  │                    Agent Brain (LLM)                        ││
     │  │   系统Prompt + 工具Schema + 用户输入 → LLM → Action/Response││
     │  └─────────────────────────────────────────────────────────────┘ │
     └────────────────────────────┬──────────────────────────────────────┘
                                  │
                    ┌─────────────┴──────────────┐
                    ↓                            ↓
     ┌──────────────────────────┐     ┌──────────────────────────────────┐
     │   SubagentExecutor       │     │         Tools Registry            │
     │   (子Agent执行器)          │     │                                   │
     │                           │     │  ├─ 内置工具:                       │
     │  ├─ 3个线程池              │     │  │   present_files (输出文件)       │
     │  │   - scheduler_pool      │     │  │   ask_clarification (澄清请求)   │
     │  │   - execution_pool      │     │  │   view_image (图片读取)          │
     │  │   - isolated_loop_pool  │     │  │   task (子Agent委托)             │
     │  │                         │     │  │   tool_search (工具搜索)         │
     │  ├─ 最大3并发              │     │  │   setup_agent (Agent设置)        │
     │  ├─ 默认15分钟超时          │     │  │                                  │
     │  └─ 状态: PENDING/RUNNING/ │     │  ├─ Sandbox工具:                   │
     │       COMPLETED/FAILED/    │     │  │   bash / ls / read_file /       │
     │       CANCELLED/TIMED_OUT  │     │  │   write_file / str_replace       │
     │                           │     │  │                                  │
     │  (委托给子Agent处理复杂任务)  │     │  ├─ Community工具:                │
     │                           │     │  │   tavily (搜索)                  │
     │                           │     │  │   jina_ai (网页抓取)             │
     │                           │     │  │   firecrawl (爬虫)               │
     │                           │     │  │   image_search (图片搜索)        │
     │                           │     │  │                                  │
     │                           │     │  └─ MCP工具 (动态加载)              │
     └──────────────────────────┘     └──────────────────────────────────┘

                              数据与存储层
     ┌─────────────────────────────────────────────────────────────────┐
     │                                                             │
     │  ┌─────────────────┐    ┌─────────────────┐                │
     │  │   Thread State   │    │    Agent State   │                │
     │  │   (langgraph     │    │    (langgraph     │                │
     │  │    checkpointer)  │    │     checkpointer) │                │
     │  └────────┬─────────┘    └────────┬─────────┘                │
     │           │                        │                           │
     │           └───────────┬────────────┘                           │
     │                       ↓                                         │
     │            ┌──────────────────────┐                             │
     │            │   langgraph Store    │                             │
     │            │   (可配置后端)        │                             │
     │            │                      │                             │
     │            │  ├─ memory (开发)    │                             │
     │            │  ├─ sqlite (单机)   │                             │
     │            │  └─ postgres (生产)  │                             │
     │            └──────────────────────┘                             │
     │                                                               │
     │  ┌─────────────────────────────────────────────────────────┐  │
     │  │              Thread Working Directory                    │  │
     │  │   .deer-flow/threads/{thread_id}/user-data/             │  │
     │  │                                                           │  │
     │  │   ├─ /workspace   (Agent工作目录)                        │  │
     │  │   ├─ /uploads     (用户上传文件)                          │  │
     │  │   └─ /outputs     (Agent生成输出)                        │  │
     │  └─────────────────────────────────────────────────────────┘  │
     │                                                               │
     │  ┌─────────────────────────────────────────────────────────┐  │
     │  │                    外部数据源                             │  │
     │  │   ├─ SQL Agent → ClickHouse / PostgreSQL / MySQL       │  │
     │  │   ├─ MCP工具   → 外部系统 API (CRM / ERP / etc.)        │  │
     │  │   └─ Web工具   → Tavily / Jina AI / Firecrawl           │  │
     │  └─────────────────────────────────────────────────────────┘  │
     └─────────────────────────────────────────────────────────────────┘
```

---

## 三、架构分层说明

### 3.1 客户端层

| 组件 | 说明 | DeerFlow 支持 |
|------|------|-------------|
| Web (Chat UI) | Next.js 前端，3000端口 | ✅ 原生支持 |
| BI Dashboard | 可复用前端扩展 | ✅ 可扩展 |
| IM Channels | Feishu/Slack/Telegram等 | ✅ 内置 `app/channels/` |

### 3.2 反向代理层 (nginx)

**职责**：路由分发 + SSL终止 + 基础安全

```
/api/langgraph/* → LangGraph Server (2024)
/api/*           → Gateway API (8001)
/                → Frontend (3000)
```

**注意**：nginx 不负责 Auth/RateLimit，需要在上层或 Gateway 层实现。

### 3.3 网关层 (Gateway API)

**职责**：REST API + SSE 流式响应

| Router | 路径 | 说明 |
|--------|------|------|
| threads | `/api/threads/*` | Thread CRUD |
| thread_runs | `/api/threads/{id}/runs/*` | 流式执行入口 |
| models | `/api/models/*` | 模型配置 |
| mcp | `/api/mcp/*` | MCP服务器管理 |
| skills | `/api/skills/*` | 技能管理 |
| memory | `/api/memory/*` | 记忆系统 |
| uploads | `/api/uploads/*` | 文件上传 |
| channels | `/api/channels/*` | IM渠道配置 |
| artifacts | `/api/artifacts/*` | 文件产物服务 |

### 3.4 Agent 运行时层 (LangGraph Server)

**核心组件**：

| 组件 | 说明 | 并发能力 |
|------|------|---------|
| Lead Agent | 主Agent，协调所有子Agent | 1 |
| Middleware Chain | 18个中间件，顺序执行 | - |
| SubagentExecutor | 子Agent执行器 | 最大3并发 |
| Tools Registry | 工具注册表 | - |
| Checkpointer | 状态持久化 | - |

### 3.5 存储层

| 存储类型 | 用途 | DeerFlow 实现 |
|---------|------|--------------|
| langgraph store | Thread/Agent 状态持久化 | memory / sqlite / postgres |
| Thread 目录 | 隔离的工作目录 | 本地文件系统 |
| 外部数据源 | SQL / API / Web | Tools 扩展 |

---

## 四、与 DeerFlow 组件的映射

| 你的架构模块 | DeerFlow 组件 | 文件位置 |
|-------------|--------------|---------|
| API Gateway | Gateway API (FastAPI) | `backend/app/gateway/` |
| Session Service | Thread 管理 | `backend/app/gateway/routers/threads.py` |
| LangGraph Orchestrator | Lead Agent + Middleware Chain | `packages/harness/deerflow/agents/` |
| 简单问答路径 | Lead Agent Direct | `packages/harness/deerflow/agents/lead_agent/agent.py` |
| 复杂任务路径 | SubagentExecutor + task tool | `packages/harness/deerflow/subagents/executor.py` |
| Worker Cluster | SubagentExecutor (内置) | 同上 |
| SQL Agent | 需扩展 Tool | 可通过 MCP 集成 |
| Tool Registry | get_available_tools() | `packages/harness/deerflow/tools/tools.py` |
| Result Store | langgraph store | `packages/harness/deerflow/runtime/store/` |

---

## 五、100 并发支持能力分析

### DeerFlow 原生限制

| 限制项 | 默认值 | 可调整性 |
|--------|-------|---------|
| Subagent 并发数 | 3 | ✅ 可配置 |
| Subagent 超时 | 15分钟 | ✅ 可配置 |
| Thread 状态存储 | Postgres/SQLite | ✅ 可扩展 |
| 前端连接 | - | nginx 限制 |

### 100 并发建议

**可满足**：
- ✅ 100 个并发 Session（每个 Session 可有多个 Subagent）
- ✅ 流式 SSE 输出
- ✅ Thread 状态持久化

**需增强**：
- ⚠️ 单 Gateway 实例建议控制在 50 并发内（FastAPI + ASGI）
- ⚠️ LangGraph Server 单实例并发取决于 LLM 提供商限制
- ⚠️ nginx 需要调整 worker 连接数

**水平扩展方案**：
```
                    ┌─────────────────┐
                    │  Load Balancer  │
                    │  (Nginx / HAProxy)│
                    └────────┬────────┘
                             │
         ┌───────────────────┼───────────────────┐
         ↓                   ↓                   ↓
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  Gateway + LG   │ │  Gateway + LG   │ │  Gateway + LG   │
│   Instance 1    │ │   Instance 2    │ │   Instance 3    │
│   (50 并发)     │ │   (50 并发)     │ │   (50 并发)     │
└─────────────────┘ └─────────────────┘ └─────────────────┘
                             │
                    ┌────────┴────────┐
                    ↓                   ↓
           ┌─────────────────┐ ┌─────────────────┐
           │   PostgreSQL    │ │  Shared Storage │
           │   (统一存储)      │ │  (文件/产物)     │
           └─────────────────┘ └─────────────────┘
```

---

## 六、部署模式选择

| 规模 | 推荐模式 | 说明 |
|------|---------|------|
| < 20 并发 | Gateway mode (`make dev-pro`) | 实验性，架构简单 |
| 20 ~ 100 并发 | Standard mode (`make dev`) | 成熟稳定，推荐 |
| > 100 并发 | Standard mode + 多实例 | 需水平扩展 |

---

## 七、安全建议（内网部署）

> ⚠️ 文档原文：Running on LAN/public cloud without IP allowlisting or authentication gateway is a security risk.

### 推荐措施

1. **IP 白名单**（nginx 层）
   ```nginx
   allow 10.0.0.0/8;
   allow 172.16.0.0/12;
   allow 192.168.0.0/16;
   deny all;
   ```

2. **API 认证**（Gateway 层扩展）
   - API Key 验证
   - JWT Token

3. **Rate Limiting**（nginx 或 Gateway）
   - 限制单 IP 请求频率
   - 限制单用户并发数

4. **敏感数据隔离**
   - Thread 目录权限控制
   - 上传文件扫描

---

## 八、企业级扩展组件实现方案

> 以下组件 DeerFlow 原生未提供，需二次开发实现。

### 8.1 API Gateway (Auth / RateLimit / LB)

DeerFlow 原生 nginx 仅做反向代理，需扩展以下能力：

#### 8.1.1 认证 (Auth)

**实现位置**：`backend/app/gateway/middleware/auth.py`（新建）

```
请求 → Auth Middleware → 验证 JWT → 通过 → 解析 user_id → 注入 request.state
                           ↓ 失败
                        返回 401
```

**核心代码结构**：

```python
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
import jwt

class AuthMiddleware(BaseHTTPMiddleware):
    """JWT 认证中间件"""
    
    PUBLIC_PATHS = {"/api/models", "/health", "/docs", "/openapi.json"}
    
    async def dispatch(self, request: Request, call_next):
        # 跳过公开路径
        if any(request.url.path.startswith(p) for p in self.PUBLIC_PATHS):
            return await call_next(request)
        
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not token:
            raise HTTPException(401, "Missing token")
        
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            request.state.user_id = payload["sub"]
        except jwt.InvalidTokenError:
            raise HTTPException(401, "Invalid token")
        
        return await call_next(request)
```

#### 8.1.2 限流 (RateLimit)

**实现位置**：`backend/app/gateway/middleware/rate_limit.py`（新建）

```
请求 → RateLimit Middleware → 检查计数 → < 限制 → 通过
                                    ↓ 超限
                              返回 429 + Retry-After
```

**核心代码结构**：

```python
from collections import defaultdict
from fastapi import Request, Response
import time

class RateLimitMiddleware(BaseHTTPMiddleware):
    """单机限流中间件"""
    
    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.rpm = requests_per_minute
        self.counters: dict[str, list[float]] = defaultdict(list)
    
    async def dispatch(self, request: Request, call_next):
        key = getattr(request.state, "user_id", request.client.host)
        now = time.time()
        
        # 清理60秒外的记录
        self.counters[key] = [t for t in self.counters[key] if now - t < 60]
        
        if len(self.counters[key]) >= self.rpm:
            return Response(
                status_code=429,
                headers={"Retry-After": "60", "X-RateLimit-Limit": str(self.rpm)}
            )
        
        self.counters[key].append(now)
        return await call_next(request)
```

**注意**：多实例部署需引入 Redis 存储计数器（DeerFlow 原生无 Redis）。

#### 8.1.3 负载均衡 (LB)

**方案：nginx upstream 多实例**

```
                         ┌─────────────────┐
                         │  nginx (LB层)   │
                         │  upstream backend│
                         └────────┬────────┘
                                  │
         ┌────────────────────────┼────────────────────────┐
         ↓                        ↓                        ↓
┌───────────────┐         ┌───────────────┐         ┌───────────────┐
│  Instance 1   │         │  Instance 2   │         │  Instance 3   │
│ Gateway+LG    │         │ Gateway+LG    │         │ Gateway+LG    │
│  (port 8001) │         │  (port 8002)  │         │  (port 8003)  │
└───────────────┘         └───────────────┘         └───────────────┘
```

**nginx 配置**：

```nginx
upstream deerflow_backend {
    least_conn;  # 最少连接优先
    
    server 127.0.0.1:8001 weight=1;
    server 127.0.0.1:8002 weight=1;
    server 127.0.0.1:8003 weight=1;
}

server {
    listen 2026;
    
    location /api/ {
        proxy_pass http://deerflow_backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        
        # SSE 流式响应必需配置
        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding on;
    }
}
```

---

### 8.2 Session Service (用户隔离 / 上下文管理)

#### 8.2.1 用户隔离

DeerFlow 的 Thread 需与 user_id 关联：

**修改点**：

| 文件 | 修改内容 |
|------|---------|
| `packages/harness/deerflow/agents/thread_state.py` | ThreadState 添加 `user_id` 字段 |
| `app/gateway/routers/threads.py` | 创建/查询 Thread 时注入 user_id |
| 新建 `app/gateway/middleware/user_context.py` | 从 Auth 解析 user_id 注入 state |

**Middleware 实现**：

```python
class UserContextMiddleware(BaseHTTPMiddleware):
    """用户上下文注入中间件"""
    
    async def dispatch(self, request: Request, call_next):
        user_id = getattr(request.state, "user_id", None)
        
        # 注入到 LangGraph config
        request.state.langgraph_config = {
            "configurable": {
                "user_id": user_id,
                "thread_id": request.path_params.get("thread_id"),
            }
        }
        
        return await call_next(request)
```

#### 8.2.2 上下文管理

基于 langgraph store 实现用户上下文存储：

```
Session Service
    │
    ├── 用户上下文 (langgraph store)
    │     ├── user_profile: { preferences, ... }
    │     ├── conversation_history: [...]
    │     └── memory: { short_term, long_term }
    │
    └── Thread 上下文 (per-thread)
          ├── AgentState (checkpointer)
          └── ThreadData (工作目录)
```

---

### 8.3 扩展后完整架构图

```
┌──────────────────────────────────────────────────────────────────────┐
│                         客户端层                                       │
│                    Web / Mobile / IM Channels                         │
└─────────────────────────────┬────────────────────────────────────────┘
                              │ HTTPS
                              ↓
┌──────────────────────────────────────────────────────────────────────┐
│                      nginx (port 2026)                                │
│                                                                       │
│   upstream deerflow_backend {                                         │
│       least_conn;                                                     │
│       server 127.0.0.1:8001 weight=1;                                │
│       server 127.0.0.1:8002 weight=1;  # 扩展实例                      │
│   }                                                                   │
│                                                                       │
│   location /api/ {                                                    │
│       proxy_pass http://deerflow_backend;                             │
│       # SSE 流式配置                                                   │
│       proxy_buffering off;                                           │
│   }                                                                   │
└─────────────────────────────┬────────────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ↓                    ↓                    ↓
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│  Gateway + LG   │   │  Gateway + LG   │   │  Gateway + LG   │
│   Instance 1    │   │   Instance 2    │   │   Instance 3   │
│   (port 8001)   │   │   (port 8002)   │   │   (port 8003)   │
└────────┬────────┘   └────────┬────────┘   └────────┬────────┘
         │                      │                      │
         └──────────────────────┼──────────────────────┘
                                │
         ┌──────────────────────┼──────────────────────┐
         │                      ↓                      │
         │    ┌─────────────────────────────────────┐  │
         │    │        Session Service               │  │
         │    │                                      │  │
         │    │  ┌────────────────────────────────┐  │  │
         │    │  │  Auth Middleware (JWT验证)     │  │  │
         │    │  ├────────────────────────────────┤  │  │
         │    │  │  RateLimit Middleware          │  │  │
         │    │  │  (单机内存/Redis分布式)         │  │  │
         │    │  ├────────────────────────────────┤  │  │
         │    │  │  UserContext Injection        │  │  │
         │    │  └────────────────────────────────┘  │  │
         │    │                                      │  │
         │    │  ┌────────────────────────────────┐  │  │
         │    │  │  LangGraph Store               │  │  │
         │    │  │  ├─ user_contexts (用户配置)  │  │  │
         │    │  │  └─ thread_states (会话状态)   │  │  │
         │    │  └────────────────────────────────┘  │  │
         │    │                                      │  │
         │    │  ┌────────────────────────────────┐  │  │
         │    │  │  Thread Per-User 隔离          │  │  │
         │    │  │  user_id → [thread_ids]        │  │  │
         │    │  └────────────────────────────────┘  │  │
         │    └──────────────────────────────────────┘  │
         │                      │                        │
         │                      ↓                        │
         │    ┌──────────────────────────────────────┐   │
         │    │       Lead Agent + Middlewares        │   │
         │    └──────────────────────────────────────┘   │
         └──────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────┐
│                      PostgreSQL (统一存储)                            │
│                                                                       │
│   ┌─────────────────┐    ┌─────────────────┐                        │
│   │  langgraph store │    │  thread_data    │                        │
│   │  (user_context,  │    │  (per-thread    │                        │
│   │   thread_state)   │    │   filesystem)   │                        │
│   └─────────────────┘    └─────────────────┘                        │
└─────────────────────────────────────────────────────────────────────┘
```

---

### 8.4 实现清单

| 组件 | 文件位置 | 优先级 | 说明 |
|------|---------|--------|------|
| Auth Middleware | `app/gateway/middleware/auth.py` | P0 | JWT 验证 |
| RateLimit Middleware | `app/gateway/middleware/rate_limit.py` | P0 | 单机限流 |
| UserContext Middleware | `app/gateway/middleware/user_context.py` | P0 | 注入 user_id |
| ThreadState.user_id | `packages/harness/deerflow/agents/thread_state.py` | P0 | 用户隔离 |
| nginx upstream | `/etc/nginx/conf.d/deerflow.conf` | P1 | 多实例 LB |
| Redis (可选) | - | P2 | 分布式限流 |

---

## 九、总结

### 修正要点

1. ❌ 去掉 Redis → 使用 langgraph store (Postgres/SQLite)
2. ❌ 去掉 Kafka → 使用内置 SubagentExecutor
3. ❌ 去掉 Ray/Celery → 同上
4. ✅ 保留 Gateway API → DeerFlow 原生提供
5. ✅ 保留 LangGraph Server → DeerFlow 原生提供
6. ✅ 保留 nginx → DeerFlow 原生使用
7. ⚠️ Auth/RateLimit → 需二次开发或外部组件

### 100 并发可行性

✅ **可行**，推荐 Standard mode，50 并发内单实例，超出后水平扩展。
