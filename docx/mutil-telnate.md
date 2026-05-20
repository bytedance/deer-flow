[用户请求] → [Nginx负载均衡] → [DeerFlow Standard实例集群] → [LLM服务/向量库/工具]
                          ↓                ↓
                        认证鉴权         会话隔离
                          ↓                ↓
                     [Redis缓存]      [Docker沙箱执行]

单体服务：集成 Gateway+LangGraphServer 功能，部署简单
水平扩展：多个实例共享 Redis 缓存和 PostgreSQL 数据库，负载均衡分发请求

2. 多租户隔离实现（三层防护）
会话隔离
每个用户会话生成唯一thread_id，关联user_id和tenant_id
LangGraph Checkpointer 使用tenant_id+user_id+thread_id作为唯一键，确保状态隔离
数据隔离
内置多租户数据过滤器，查询自动添加租户 ID 条件
向量库支持命名空间隔离，每个租户有独立命名空间
安全隔离
工具调用在 Docker 沙箱中执行，限制资源访问
敏感信息加密存储，API 请求签名验证
3. 高并发处理策略（四大优化）
协程并行
基于 LangGraph 1.x 的 asyncio 架构，单实例支持500 + 并发
子 Agent 并行执行，任务效率提升3-5 倍
缓存优化
会话状态缓存到 Redis，减少数据库查询
工具结果内存缓存，TTL 可配置
限流保护
内置令牌桶限流，全局并发控制在 30 以内
每个用户会话限制最大并发子任务数（默认 3 个）
资源管理
动态调整沙箱容器数量，空闲容器自动回收
模型调用超时控制（比如15 秒），防止长时间阻塞

