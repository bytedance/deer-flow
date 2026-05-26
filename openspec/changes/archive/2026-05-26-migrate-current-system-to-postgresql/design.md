## Context

DeerFlow 已有部分 PostgreSQL 支持：
- `DatabaseConfig` 支持 `memory/sqlite/postgres` 三种后端
- 16 个 ORM 模型已定义（users, tenants, threads, runs, agents, knowledge_bases 等）
- `StoreMemoryStorage` 可通过 LangGraph Store 写入
- `DbRunEventStore` 已实现 SQLAlchemy 后端
- `rag/backends/pgvector.py` 已存在（182 行）
- Token 追踪已整合到 `RunRow` + `AgentUsageRow`

但生产部署仍用 SQLite/JSON/Chroma 分散存储，原因：
1. 配置未联动：`database.backend=postgres` 不会自动设置其他子系统
2. 迁移脚本缺失：没有 SQLite→PG 的全表迁移工具
3. 校验缺失：无法验证迁移后数据一致性
4. 文档缺失：没有迁移 runbook 和回滚流程

## Goals / Non-Goals

**Goals:**
- 生产环境 `database.backend=postgres` 时，所有子系统自动使用 PostgreSQL
- 提供可重复执行的迁移脚本，覆盖 16 个 ORM 表
- 提供 Chroma→pgvector 重索引脚本，适配 KB-bound embedding 架构
- 提供启动校验，拒绝生产环境的分裂配置
- 提供完整的迁移 runbook 和回滚流程

**Non-Goals:**
- 不改变现有 ORM 模型结构
- 不实现热迁移（需要停机窗口）
- 不支持 SQLite↔PostgreSQL 运行时切换
- 不迁移文件存储（uploads/artifacts 保留在文件系统）
- 不实现双写（迁移期间停止写入）

## Decisions

### Decision 1: 配置联动实现位置

**选择**：在 `AppConfig.post_init()` 中根据 `database.backend` 自动设置其他子系统配置。

**理由**：
- 集中逻辑，避免各子系统重复判断
- 启动时一次性设置，运行时不可变
- 便于添加校验和警告

**替代方案**：
- 各子系统自行判断 → 拒绝：逻辑分散，难以维护
- 配置文件预处理 → 拒绝：增加配置解析复杂度

**实现**：
```python
def post_init(self):
    if self.database.backend == "postgres":
        if not self.run_events.backend_explicitly_set:
            self.run_events.backend = "db"
        if not self.memory.storage_class_explicitly_set:
            self.memory.storage_class = "StoreMemoryStorage"
        if not self.rag.vector_store_backend_explicitly_set:
            self.rag.vector_store_backend = "pgvector"
        if not self.cost.storage_backend_explicitly_set:
            self.cost.storage_backend = "postgres"
```

### Decision 2: 分裂配置校验策略

**选择**：启动时校验，生产模式拒绝分裂配置，开发模式仅警告。

**理由**：
- 生产环境必须一致性（PG 数据 + JSON 成本 = 数据丢失风险）
- 开发环境允许灵活性（测试不同组合）
- 通过 `DEER_FLOW_ENV=production` 环境变量控制

**替代方案**：
- 运行时校验 → 拒绝：问题发现太晚，已造成数据不一致
- 完全禁止分裂 → 拒绝：阻碍开发调试

**实现**：
```python
def validate_config_consistency(self):
    if self.database.backend == "postgres":
        conflicts = []
        if self.cost.storage_backend != "postgres":
            conflicts.append("cost.storage_backend")
        # ... 其他检查
        
        if conflicts and os.getenv("DEER_FLOW_ENV") == "production":
            raise ConfigError(f"Split backend config in production: {conflicts}")
        elif conflicts:
            logger.warning(f"Split backend config (dev mode): {conflicts}")
```

### Decision 3: SQLite→PostgreSQL 迁移策略

**选择**：批量读取 + 批量写入，支持幂等重跑，提供校验报告。

**理由**：
- 批量操作性能优于逐行插入
- 幂等性允许中断后继续
- 校验报告提供迁移信心

**替代方案**：
- 逐行迁移 → 拒绝：性能差，16 个表耗时过长
- 一次性全量 → 拒绝：中断后无法恢复
- 双写同步 → 拒绝：复杂度高，需要长时间并行运行

**实现**：
```python
def migrate_table(session, table_name, batch_size=1000):
    # 1. 从 SQLite 批量读取
    sqlite_rows = sqlite_session.execute(select(Table)).fetchall()
    
    # 2. 过滤已存在（幂等）
    existing_ids = get_existing_ids(pg_session, table_name)
    new_rows = [r for r in sqlite_rows if r.id not in existing_ids]
    
    # 3. 批量写入 PostgreSQL
    pg_session.bulk_insert_mappings(Table, new_rows)
    
    # 4. 校验
    assert pg_session.query(Table).count() == len(sqlite_rows)
    
    return MigrationReport(table_name, len(new_rows), "success")
```

### Decision 4: Chroma→pgvector 重索引策略

**选择**：按 KnowledgeBase 维度重索引，复用每个 KB 的 `embedding_model` 和 `embedding_dim`。

**理由**：
- Sprint B 引入了 KB-bound embedding（每个 KB 独立的 embedding 模型和维度）
- 不能全局统一 embedding 模型
- 需要按 KB 逐个处理

**替代方案**：
- 直接复制 Chroma 向量 → 拒绝：Chroma 内部格式不透明，且维度可能不匹配
- 全局统一 embedding → 拒绝：破坏 KB-bound embedding 架构

**实现**：
```python
def reindex_knowledge_base(kb_id: str):
    # 1. 获取 KB 的 embedding 配置
    kb = get_knowledge_base(kb_id)
    embedding_model = kb.embedding_model
    embedding_dim = kb.embedding_dim
    
    # 2. 获取所有 documents
    documents = get_documents(kb_id)
    
    # 3. 重新分块
    chunks = chunk_documents(documents)
    
    # 4. 生成 embeddings（使用 KB 的模型）
    embeddings = generate_embeddings(chunks, model=embedding_model)
    
    # 5. 写入 pgvector（带维度校验）
    insert_pgvector_rows(chunks, embeddings, expected_dim=embedding_dim)
    
    # 6. 校验
    assert pgvector_count(kb_id) == len(chunks)
```

### Decision 5: token_usage.json 处理策略

**选择**：审计后归档，不迁移到新表。

**理由**：
- Token 数据已在 `RunRow.total_tokens` 和 `AgentUsageRow.token_input/output` 中
- 创建独立的 `TokenUsage` 表是冗余
- 归档保留历史数据，不丢失

**替代方案**：
- 迁移到 `TokenUsage` 表 → 拒绝：与现有 ORM 结构冲突
- 直接删除 → 拒绝：可能丢失审计数据

**实现**：
```python
def archive_token_usage():
    # 1. 审计：检查 JSON 数据是否已在 ORM 中
    json_data = load_json("token_usage.json")
    orm_data = query_agent_usage()
    
    if json_data.total_tokens != orm_data.total_tokens:
        logger.warning("Token usage mismatch, review before archiving")
        return False
    
    # 2. 归档
    shutil.move("token_usage.json", "backups/token_usage.json.bak")
    return True
```

## Risks / Trade-offs

**风险 1: 迁移期间数据丢失**
- **缓解**：迁移前完整备份（SQLite + JSON + Chroma），迁移后校验报告，回滚流程文档化
- **Trade-off**：需要停机窗口（预计 2-4 小时）

**风险 2: KB-bound embedding 重索引失败**
- **缓解**：按 KB 维度重索引，单个 KB 失败不影响其他 KB，支持断点续传
- **Trade-off**：重索引耗时较长（预计 4-8 小时，取决于文档数量和 embedding API 速率限制）

**风险 3: 配置联动破坏现有部署**
- **缓解**：开发模式仅警告不拒绝，生产模式通过 `DEER_FLOW_ENV` 显式启用，提供配置迁移指南
- **Trade-off**：需要运维团队更新配置文件

**风险 4: 回滚复杂性**
- **缓解**：保留 SQLite/JSON/Chroma 备份至少 7 天，回滚脚本文档化，测试环境预演
- **Trade-off**：回滚需要另一个停机窗口

## Migration Plan

### 阶段 0: 准备（1 小时）
1. 部署 PostgreSQL 15+，安装 `vector` 和 `pgcrypto` 扩展
2. 创建数据库和用户
3. 备份现有数据：
   - `cp -r .deer-flow/data backups/sqlite`
   - `cp -r .deer-flow/memory backups/memory_json`
   - `cp -r .deer-flow/chroma backups/chroma`
4. 通知用户停机窗口

### 阶段 1: 配置和校验（30 分钟）
1. 更新 `config.yaml`：
   ```yaml
   database:
     backend: postgres
     postgres_url: postgresql://user:pass@host:5432/deerflow
   ```
2. 设置环境变量：`DEER_FLOW_ENV=production`
3. 启动服务，观察配置联动和校验日志
4. 如果校验失败，修复配置后重启

### 阶段 2: SQLite→PostgreSQL 迁移（1-2 小时）
1. 停止服务
2. 运行迁移脚本：
   ```bash
   python scripts/migrate_sqlite_to_postgres.py \
     --sqlite-path .deer-flow/data/deerflow.db \
     --postgres-url postgresql://user:pass@host:5432/deerflow \
     --validate
   ```
3. 检查迁移报告，确认 16 个表全部成功
4. 启动服务，测试核心功能（创建 thread、运行 agent、上传文档）

### 阶段 3: memory.json→Store 迁移（30 分钟）
1. 停止服务
2. 运行迁移脚本：
   ```bash
   python scripts/migrate_memory_to_store.py \
     --memory-path .deer-flow/memory \
     --postgres-url postgresql://user:pass@host:5432/deerflow
   ```
3. 启动服务，测试 memory 注入功能

### 阶段 4: Chroma→pgvector 重索引（4-8 小时）
1. 停止服务
2. 运行重索引脚本（支持断点续传）：
   ```bash
   python scripts/reindex_rag_to_pgvector.py \
     --chroma-path .deer-flow/chroma \
     --postgres-url postgresql://user:pass@host:5432/deerflow \
     --batch-size 100 \
     --resume
   ```
3. 检查重索引报告，确认所有 KB 成功
4. 启动服务，测试 RAG 检索功能

### 阶段 5: 清理和监控（持续）
1. 归档遗留文件：
   ```bash
   mv .deer-flow/data/deerflow.db backups/
   mv .deer-flow/memory backups/
   mv .deer-flow/chroma backups/
   ```
2. 监控 PostgreSQL 性能（连接池、查询延迟、表大小）
3. 7 天后删除备份（确认无问题）

### 回滚流程
如果迁移失败：
1. 停止服务
2. 恢复备份：
   ```bash
   cp backups/sqlite/deerflow.db .deer-flow/data/
   cp -r backups/memory_json .deer-flow/memory
   cp -r backups/chroma .deer-flow/chroma
   ```
3. 修改 `config.yaml`：
   ```yaml
   database:
     backend: sqlite
   ```
4. 启动服务，验证功能正常
5. 分析失败原因，修复后重新迁移

## Open Questions

1. **停机窗口时间**：需要与运维团队协调，选择低峰时段（建议 UTC 02:00-06:00）
2. **embedding API 速率限制**：重索引期间可能触发速率限制，需要实现退避重试
3. **大表迁移性能**：`runs` 和 `run_events` 表可能很大，需要分批迁移和索引优化
4. **监控告警**：迁移后需要添加 PostgreSQL 连接池、查询延迟、表大小的监控告警
