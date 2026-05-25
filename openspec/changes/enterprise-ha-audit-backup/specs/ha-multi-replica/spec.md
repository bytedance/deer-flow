## ADDED Requirements

### Requirement: Gateway stateless operation
Gateway 实例 SHALL 不在进程内存中保存任何请求间必须共享的状态。会话数据、限流计数器、分布式锁 SHALL 通过 Redis 后端访问。

#### Scenario: Multiple Gateway instances serve requests
- **WHEN** 同一用户向不同的 Gateway 实例发送连续请求
- **THEN** 用户会话状态在两个请求间保持一致

#### Scenario: Gateway restart without data loss
- **WHEN** 任意 Gateway 实例重启
- **THEN** 用户不需要重新认证，速率限制状态不丢失

### Requirement: Health check endpoints
系统 SHALL 提供 `/health/live` 和 `/health/ready` 端点。

#### Scenario: Liveness probe
- **WHEN** GET `/health/live` 被调用
- **THEN** 进程存活时返回 200，响应体为 `{"status": "ok"}`

#### Scenario: Readiness probe with all dependencies healthy
- **WHEN** GET `/health/ready` 被调用且 PostgreSQL、Redis、LangGraph Server 均可连通
- **THEN** 返回 200，响应体列出各依赖状态 `{"status": "ready", "checks": {"postgres": "ok", "redis": "ok", "langgraph": "ok"}}`

#### Scenario: Readiness probe with failed dependency
- **WHEN** GET `/health/ready` 被调用且 PostgreSQL 不可连通
- **THEN** 返回 503，响应体包含 `{"status": "not_ready", "checks": {"postgres": "error", ...}}`

### Requirement: Load-balanced Gateway
Nginx SHALL 将 `/api/*` 请求分发到多个 Gateway 实例。

#### Scenario: Round-robin distribution
- **WHEN** 10 个请求到达 Nginx
- **THEN** 请求均匀分发到所有健康的 Gateway 实例

#### Scenario: Unhealthy instance excluded
- **WHEN** 某个 Gateway 实例 `/health/ready` 返回非 200
- **THEN** Nginx 停止向该实例分发新请求

### Requirement: SSE sticky session
流式请求 (SSE) SHALL 保持连接到同一后端实例。

#### Scenario: Stream request pinned to same backend
- **WHEN** 客户端发起 SSE 流式请求到 `/api/threads/{id}/runs/stream`
- **THEN** 所有后续 SSE 事件从同一 Gateway 实例发出，直到连接关闭
