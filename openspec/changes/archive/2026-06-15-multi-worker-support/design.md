## Context

DeerFlow 后端当前所有有状态组件的默认后端都是进程本地的：

| 组件 | 默认后端 | 多 Worker |
|------|----------|:---:|
| Checkpointer | `InMemorySaver` | ❌ |
| LangGraph Store | `InMemoryStore` | ❌ |
| Stream Bridge | `MemoryStreamBridge` (asyncio.Queue) | ❌ |
| Agent Memory | `FileMemoryStorage` (JSON 文件) | ❌ |
| RAG 向量库 | ChromaDB (本地文件) | ❌ |
| Run/Feedback Store | `MemoryRunStore` / `None` | ❌ |
| Cost Storage | JSON 文件 | ❌ |
| KB 索引调度 | `asyncio.create_task` | ❌ |
| IM 渠道 | 进程内轮询/WebSocket | ❌ |

代码层面，PostgreSQL 后端（checkpointer、store、run repository）和 Redis 后端（stream bridge、rate limit）已经实现。`StoreMemoryStorage` 已通过 `ThreadPoolExecutor` + `run_coroutine_threadsafe` 解决了 sync/async 桥接问题，可直接复用。Agent Memory 和 KB 索引调度仍只有进程本地实现。

**核心约束**：不能改变现有默认行为。所有变更必须通过 opt-in 机制激活。

## Goals / Non-Goals

**Goals:**

- 提供 opt-in 的多 worker 部署模式（环境变量或配置项）
- 启用多 worker 模式后，所有有状态组件自动切换到共享后端（PostgreSQL + Redis）
- 完全向后兼容：不启用多 worker 模式时行为与现有完全一致
- Agent Memory 跨 worker 读写安全（乐观合并策略）

**Non-Goals:**

- K8s 自动扩缩容（HPA）— 属于部署层面，本方案只提供健康检查支持
- 跨地域多活部署 — 当前只需要单机多 worker
- 完全无状态化 — Agent Memory 和 KB 索引仍依赖 PostgreSQL，不算"无状态"
- IM 渠道多实例热备 — 只做主从选举，不做故障自动转移
- 修改现有默认后端配置

## Decisions

### Decision 1: 多 Worker 模式开关（扩展现有 _apply_database_defaults）

**选择**：新增 `deployment.mode` 配置项 + `DEER_FLOW_MULTI_WORKER=1` 环境变量，在现有 `_apply_database_defaults()` 方法中扩展 multi-worker 分支

```yaml
# config.yaml — 启用多 worker 模式
deployment:
  mode: multi_worker   # "single_worker" (默认) | "multi_worker"

# 或环境变量
# DEER_FLOW_MULTI_WORKER=1
```

**与现有机制的关系**：代码已有 `_apply_database_defaults()`（app_config.py:283-356），当 `database.backend=postgres` 时自动覆盖 memory/rag/cost 子系统。`deployment.mode: multi_worker` 扩展该方法的逻辑，新增对 stream_bridge、indexing、im 等非 database 子系统的覆盖。

**优先级规则**（高→低）：
1. 用户显式配置（config.yaml 中的字段值）
2. `deployment.mode: multi_worker` 自动覆盖
3. `database.backend=postgres` 自动覆盖（现有逻辑）
4. 组件默认值

启用后自动覆盖各组件默认值：

| 组件 | 单 worker（默认） | 多 worker 模式 |
|------|-------------------|----------------|
| database.backend | memory | postgres |
| stream_bridge.type | memory | redis |
| rag.vector_store_backend | chroma | pgvector |
| rate_limit.backend | memory | redis |
| cost.storage_backend | json | postgres |
| indexing.dispatcher_mode | local | queue |
| im.coordination_mode | none | redis |
| memory.storage_class | FileMemoryStorage | StoreMemoryStorage |

**替代方案**：直接改默认值。否决原因：破坏性变更，现有用户升级会宕机。

### Decision 2: Agent Memory 复用 StoreMemoryStorage

**选择**：multi-worker 模式下直接使用现有的 `StoreMemoryStorage` + PostgreSQL BaseStore，**不创建新的存储类**

**为什么不用独立 PostgresMemoryStorage**：代码已有 `StoreMemoryStorage`（storage.py:237-343），通过 `ThreadPoolExecutor` + `run_coroutine_threadsafe` 解决 sync/async 桥接问题。这是生产可用的方案，不需要重新发明轮子。

```python
# storage.py 现有实现（已解决 sync/async 桥接）
class StoreMemoryStorage(MemoryStorage):
    def load(self, agent_name=None, *, user_id=None) -> dict:
        store = self._get_store()
        ns = self._ns(agent_name, user_id=user_id)
        # 在 event loop 中调用时，通过 worker thread dispatch
        try:
            asyncio.get_running_loop()
            item = _dispatch_aget(store, ns, "data")
        except RuntimeError:
            item = store.get(ns, "data")
        ...

    def save(self, memory_data, agent_name=None, *, user_id=None) -> bool:
        store = self._get_store()
        ns = self._ns(agent_name, user_id=user_id)
        try:
            asyncio.get_running_loop()
            _dispatch_aput(store, ns, "data", memory_data)
        except RuntimeError:
            store.put(ns, "data", memory_data)
        ...
```

**数据共享**：`StoreMemoryStorage` 使用 LangGraph BaseStore 的 namespace `("memory", tenant_id, user_id, agent_name)`。当 `database.backend=postgres` 时，BaseStore 自动使用 `AsyncPostgresStore`，数据存储在 PostgreSQL 的 `store_items` 表中。多 worker 共享同一 PostgreSQL 实例，自动实现跨 worker 可见性。

**替代方案**：创建独立 `PostgresMemoryStorage` + `agent_memory` 表 + psycopg2 连接池。否决原因：
- 数据分散在两个存储位置（BaseStore + agent_memory 表）
- 额外的连接池（max=5）→ 总连接数增加
- 额外的迁移脚本 → 维护负担
- 重新发明已解决的问题（sync/async 桥接）

### Decision 3: Agent Memory 乐观合并策略（应用层实现）

**选择**：在 memory updater 层实现**读-合并-写**，facts 按内容 hash 去重追加。合并不在存储层实现，而在调用 `save()` 之前。

```python
# memory/updater.py 中的 save 调用链
def save_memory_with_merge(memory_data, agent_name=None, *, user_id=None):
    """保存 memory，先与现有数据合并。"""
    storage = get_memory_storage()

    # 1. 读取当前最新版本
    current = storage.load(agent_name=agent_name, user_id=user_id)

    # 2. 合并 facts（复用现有 _fact_content_key 去重策略）
    merged = _merge_facts(current, memory_data)

    # 3. 调用存储层的 save（StoreMemoryStorage.save()）
    return storage.save(merged, agent_name=agent_name, user_id=user_id)

def _fact_dedup_key(fact: dict) -> str | None:
    """Fact 去重 key，与现有 _fact_content_key 保持一致（casefold 比较）。"""
    content = fact.get("content", "")
    if not isinstance(content, str) or not content.strip():
        return None
    return content.strip().casefold()

def _merge_facts(current: dict, incoming: dict) -> dict:
    """合并 facts：已有 + 新增去重，删除的不再出现。"""
    existing_keys = {_fact_dedup_key(f) for f in current.get("facts", []) if _fact_dedup_key(f)}
    new_facts = [f for f in incoming.get("facts", []) if _fact_dedup_key(f) not in existing_keys]
    return {
        **incoming,
        "facts": current.get("facts", []) + new_facts,
    }
```

**为什么不在存储层实现**：`StoreMemoryStorage` 是通用存储，不应包含业务逻辑（fact 合并）。合并是 memory 领域的业务规则，应放在 memory updater 层。

**为什么不用乐观锁**：乐观锁需要 retry 循环 + 错误传播 + 用户可见的冲突处理，复杂度高。Agent Memory 写入低频（每轮对话 1 次），并发冲突极少。读-合并-写在绝大多数场景下等价于串行执行。

**边界情况**：如果两个 worker 同时执行读-合并-写（精确同时），后写入的会覆盖先写入的。概率极低（微秒级窗口），且丢失的仅是对方刚追加的新 facts（不影响已有 facts）。可接受。

### Decision 4: KB 索引队列

**选择**：PostgreSQL 轮询模式（`SELECT ... FOR UPDATE SKIP LOCKED`）

`IndexingDispatcher` 新增 `queue` 模式：
1. 索引任务写入 `index_jobs` 表（已有）
2. Worker 从 `index_jobs` 表抢占任务（`FOR UPDATE SKIP LOCKED`）
3. 每个 worker 独立轮询，无任务时 sleep 5s（退避到 30s）

**替代方案**：Celery + Redis。否决原因：引入新依赖和运维复杂度。PostgreSQL 轮询足够（KB 索引是低频操作，不需要毫秒级延迟）。

### Decision 5: IM 渠道协调

**选择**：Redis 分布式锁（Lua 脚本原子操作）

锁的获取、续期、释放全部使用 Lua 脚本，避免竞态条件：

```lua
-- 续期：仅当 value 匹配时才续期（防止覆盖其他 worker 的锁）
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("SET", KEYS[1], ARGV[1], "EX", ARGV[2])
end
return 0
```

```lua
-- 释放：仅当 value 匹配时才删除
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
end
return 0
```

锁 TTL 30s，每 10s 续期。Worker 宕机后锁自动过期，其他 worker 接管。

**替代方案 A**：PostgreSQL advisory lock。可行但与 Redis 方案功能等价，且 Redis 锁 Lua 脚本更成熟。
**替代方案 B**：固定 worker_id 分配。否决原因：worker 数量动态变化时无法预分配。

### Decision 6: 健康检查增强

**选择**：`/health/ready` 端点报告各后端连接状态

```json
{
  "status": "ready",
  "checks": {
    "postgres": {"status": "ok", "latency_ms": 3},
    "redis": {"status": "ok", "latency_ms": 1},
    "vector_store": {"status": "ok", "backend": "pgvector"}
  }
}
```

任一 critical 后端不可达时返回 503。健康检查结果缓存 10 秒，避免高频 probe 对后端产生不必要的负载。

### Decision 7: 连接池调整

多 worker 模式下 PostgreSQL 连接需求增加，需要评估总连接数并调整 `max_connections`。

| 组件 | 文件 | 当前 max | 多 worker 预估 | 说明 |
|------|------|---------|---------------|------|
| Checkpointer (async) | async_provider.py:79 | 5 | 10 | 提升 max_size |
| Checkpointer (sync) | provider.py:92 | 10 | 10 | 保持 |
| Store (async) | async_provider.py:76,152 | 10 | 15 | 提升 max_size |
| Store (sync) | provider.py:88 | 10 | 10 | 保持 |
| App ORM (pool_size + max_overflow) | databaseconfig.py:73-79 | 10 (5+5) | 15 (10+5) | 提升 pool_size |
| KB 索引 | N/A | N/A | 5 | 新增独立连接池 |

**总计**：单 worker 约 50 连接，4 workers 约 200 连接。PostgreSQL 默认 `max_connections=100`，需要调整到 250+。

**建议**：docker-compose 中 PostgreSQL 启动参数增加 `-c max_connections=250`。

### Decision 8: Worker ID 日志传播

多 worker 下所有日志、metrics、trace 应包含 `worker_id`，便于排查问题。

```python
import logging
import uuid

WORKER_ID = str(uuid.uuid4())[:8]

class WorkerIdFilter(logging.Filter):
    def filter(self, record):
        record.worker_id = WORKER_ID
        return True

# 在日志格式中添加 %(worker_id)s
logging.getLogger("deerflow").addFilter(WorkerIdFilter())
```

日志格式示例：`2026-06-13 10:00:00 [a1b2c3d4] INFO deerflow.agents: Processing thread_id=xxx`

### Decision 9: 分阶段实施

| 阶段 | 内容 | 风险 |
|------|------|------|
| Phase 1 | 健康检查 + `deployment.mode` 配置框架 + worker_id 日志 | 低：新增端点 + 配置 |
| Phase 2 | Agent Memory 乐观合并（应用层） | 低：复用 StoreMemoryStorage |
| Phase 3 | KB 索引队列改造 | 中：并发抢占 |
| Phase 4 | IM 渠道协调（Lua 脚本锁） | 低：锁竞争 |
| Phase 5 | docker-compose + Nginx + 连接池配置 | 低：配置变更 |

每个阶段独立可部署、可回滚。

## Risks / Trade-offs

- **[PostgreSQL 单点]** → 多 worker 模式依赖 PostgreSQL，宕机则全系统不可用。缓解：PostgreSQL 主从复制 + 自动故障转移（部署层面）。
- **[Redis 单点]** → Stream bridge 和 IM 锁依赖 Redis。缓解：Redis Sentinel 或 Redis Cluster（部署层面）。
- **[KB 索引轮询延迟]** → PostgreSQL 轮询模式有秒级延迟（对比 Celery 毫秒级）。缓解：KB 索引本身是分钟级操作，秒级延迟可接受。
- **[Agent Memory 合并窗口]** → 读-合并-写存在微秒级竞态窗口，极端情况下丢失对方刚追加的 facts。缓解：概率极低，且仅影响新增 facts，不影响已有数据。
- **[连接池压力]** → 多组件共享 PostgreSQL，4 workers 约需 200 连接。缓解：PostgreSQL `max_connections` 调整到 250+。
- **[向后兼容]** → 完全兼容。`deployment.mode` 默认 `single_worker`，不改变任何现有行为。
- **[开发体验]** → 多 worker 模式需要 PostgreSQL + Redis。缓解：`docker-compose.dev.yml` 一键启动；`DEER_FLOW_DEV_MODE=1` 保留纯内存开发。
