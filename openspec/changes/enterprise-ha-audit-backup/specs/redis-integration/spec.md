## ADDED Requirements

### Requirement: Redis connection management
系统 SHALL 通过 `config.yaml` 的 `redis` 配置段管理 Redis 连接，支持单节点和 Sentinel 模式。

#### Scenario: Single node connection
- **WHEN** `config.yaml` 配置 `redis.url: redis://localhost:6379/0`
- **THEN** 系统启动时建立到该 Redis 实例的连接池

#### Scenario: Sentinel mode connection
- **WHEN** `config.yaml` 配置 `redis.sentinels` 列表和 `redis.master_name`
- **THEN** 系统通过 Sentinel 自动发现主节点

#### Scenario: Missing Redis configuration
- **WHEN** `config.yaml` 中无 `redis` 配置段
- **THEN** 系统降级为进程内内存模式（兼容单节点开发），启动时打印 INFO 日志

### Requirement: Session storage in Redis
用户会话 SHALL 存储在 Redis 中，支持跨 Gateway 实例共享。

#### Scenario: Session shared across instances
- **WHEN** 用户在 Gateway-A 认证获取 session，随后在 Gateway-B 发起请求
- **THEN** Gateway-B 能从 Redis 读取 session 并识别用户身份

#### Scenario: Session expiry
- **WHEN** 用户 session 超过 TTL 未被访问
- **THEN** Redis 自动清除过期 session，下次请求返回 401

### Requirement: Rate limit counters in Redis
速率限制计数器 SHALL 使用 Redis 作为后端，替代进程内内存计数。

#### Scenario: Rate limit enforced across instances
- **WHEN** 用户在 Gateway-A 消耗了 50% 的速率限制配额，随后请求被路由到 Gateway-B
- **THEN** Gateway-B 从 Redis 读取到剩余配额并正确执行限制

#### Scenario: Rate limit window reset
- **WHEN** 速率限制时间窗口过期
- **THEN** Redis 中的计数器自动过期，用户配额重置

### Requirement: Distributed lock for index jobs
知识库索引任务 SHALL 使用 Redis 分布式锁确保同一文档不被并发索引。

#### Scenario: Duplicate index job rejected
- **WHEN** 两个 Gateway 实例同时触发同一 `(kb_id, doc_id, version)` 的索引任务
- **THEN** 仅一个任务执行索引，另一个检测到锁存在后跳过
