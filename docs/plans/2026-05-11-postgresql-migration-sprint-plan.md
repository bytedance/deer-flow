# PostgreSQL 存储迁移 Sprint 计划

> 基于 [技术设计方案](./2026-05-08-postgresql-storage-migration-design.md) §14 实施进度，按"配置收口 → 结构化数据切换 → 运行态持久化切换 → 向量存储切换 → 旧存储退役"顺序编排。

---

## 团队容量估算

| 参数 | 值 |
| --- | --- |
| 团队规模 | 2 名后端工程师 |
| Sprint 周期 | 2 周（10 工作日） |
| 每人每 Sprint 可用 SP | 20 SP |
| 总容量 | 40 SP |
| Buffer（20%） | 8 SP |
| 可承诺容量 | 32 SP / Sprint |

---

## Sprint 0：环境准备（前置）

**Sprint Goal:** PostgreSQL 基础设施就绪，CI 支持 PostgreSQL 容器测试，团队具备 LangGraph Checkpointer/Store 表结构基础认知。

**Duration:** 1 周  
**Committed:** 10 SP / 3 Stories  
**Buffer:** N/A（前置准备，不占正式 Sprint 容量）

### Stories

| # | Story | SP | Owner | 依赖 | AC |
| --- | --- | --- | --- | --- | --- |
| 0.1 | PostgreSQL 环境搭建 | 3 | BE-1 | 无 | 开发/测试/预发环境各有 PostgreSQL 15+ 实例；pgvector 扩展已安装；连接串已配置到 `config.yaml` |
| 0.2 | CI PostgreSQL 容器集成 | 5 | BE-2 | 无 | GitHub Actions 使用 `pgvector/pgvector:pg16` service container；`make test` 可选 `DATABASE_BACKEND=postgres` 运行 |
| 0.3 | LangGraph Checkpointer/Store 表结构调研 | 2 | BE-1 | 无 | 输出文档：SQLite 与 PostgreSQL 版 checkpointer 表 schema 对比；确认是否可直接表级搬迁 |

---

## Sprint 1：配置收口与基础正式化

**Sprint Goal:** PostgreSQL 模式下所有子系统配置自动收口，启动期拒绝分裂组合，`token_usage` 正式纳入 ORM/Alembic。

**Duration:** 2 周  
**Committed:** 30 SP / 6 Stories  
**Buffer:** 2 SP

### Stories

| # | Story | SP | Owner | 依赖 | AC |
| --- | --- | --- | --- | --- | --- |
| 1.1 | 实现启动期配置一致性校验 | 5 | BE-1 | 无 | `database.backend=postgres` 时拒绝 `run_events=memory`、`cost=json`、`memory=file`、`rag=chroma` 组合；启动失败时输出明确错误信息 |
| 1.2 | 实现 postgres 模式子系统默认值自动继承 | 5 | BE-1 | 1.1 | `database.backend=postgres` 时 `run_events`/`cost`/`memory` 自动选择 postgres 路径；`pgvector_connection_string` 为空时继承 `postgres_url` |
| 1.3 | 旧 `checkpointer` 配置段 deprecation warning | 3 | BE-1 | 无 | 启动时检测到旧 `checkpointer` 段打印 warning；功能不受影响 |
| 1.4 | `token_usage` ORM Model + Repository | 8 | BE-2 | 无 | 新增 `TokenUsageRow` Model、`TokenUsageRepository` CRUD、Alembic migration |
| 1.5 | `cost` 中间件切换到 `TokenUsageRepository` | 5 | BE-2 | 1.4 | postgres 模式下 `TokenUsageMiddleware` 写入 ORM 表；JSON fallback 仅在 sqlite 模式保留 |
| 1.6 | 单元测试：配置校验 + token_usage CRUD | 4 | BE-2 | 1.1, 1.4 | 覆盖：校验拒绝分裂组合、继承逻辑、Repository CRUD 幂等性；覆盖率 ≥ 80% |

### 依赖图

```
1.1 → 1.2
1.1 → 1.6
1.4 → 1.5
1.4 → 1.6
1.3 (独立)
```

### 风险

| 风险 | 缓解 |
| --- | --- |
| 配置校验可能误拒合法组合 | 增加 `database.strict_validation: false` escape hatch，默认 true |
| `PgUsageStorage` 原型与新 ORM 表字段不一致 | 以设计文档 §7.2.1 schema 为准，原型代码标记 deprecated |

---

## Sprint 2：运行态状态切换

**Sprint Goal:** `run_events` 和 `memory` 在 postgres 模式下默认使用数据库后端，pgvector 表正式纳入 Alembic。

**Duration:** 2 周  
**Committed:** 31 SP / 6 Stories  
**Buffer:** 1 SP

### Stories

| # | Story | SP | Owner | 依赖 | AC |
| --- | --- | --- | --- | --- | --- |
| 2.1 | `run_events` postgres 模式默认切换为 `db` | 3 | BE-1 | Sprint 1 完成 | `database.backend=postgres` 时 `run_events` 自动选择 `db`；无需手动配置 |
| 2.2 | `memory` postgres 模式默认切换为 `StoreMemoryStorage` | 5 | BE-1 | Sprint 1 完成 | postgres 模式下 memory 自动走 Store；sqlite 模式保持文件版 |
| 2.3 | pgvector 表正式建模 + Alembic migration | 8 | BE-2 | 无 | `rag_chunks` 表定义含 tenant_id/collection/embedding/HNSW 索引；`CREATE EXTENSION vector` 在 migration 中执行 |
| 2.4 | pgvector 后端对接正式表 | 5 | BE-2 | 2.3 | `rag/backends/pgvector.py` 使用 ORM 表而非运行时 DDL；检索功能不变 |
| 2.5 | 集成测试：run_events + memory + pgvector | 5 | BE-1 | 2.1, 2.2, 2.4 | PostgreSQL 容器启动 → 建表 → run_events 写入/查询 → memory 持久化/注入 → pgvector 索引/检索 |
| 2.6 | `run_events` DB 后端性能基线 | 5 | BE-2 | 2.1 | 10K events 写入 < 5s；分页查询 P99 < 100ms；建立归档/保留策略文档 |

### 依赖图

```
Sprint 1 → 2.1, 2.2
2.3 → 2.4
2.1, 2.2, 2.4 → 2.5
2.1 → 2.6
```

### 风险

| 风险 | 缓解 |
| --- | --- |
| pgvector 扩展在目标 PostgreSQL 版本不可用 | 要求 PostgreSQL 15+ 且预装 pgvector；CI 使用 `pgvector/pgvector:pg16` 镜像 |
| `run_events` 高频写入导致表膨胀 | 2.6 中建立保留策略；后续 Sprint 实现自动归档 |
| `StoreMemoryStorage` 在高并发下的一致性 | LangGraph Store 内部已有锁机制；集成测试覆盖并发写入场景 |

---

## Sprint 3：迁移脚本与数据回填

**Sprint Goal:** 完成全部离线迁移脚本，支持从 SQLite/JSON/Chroma 一键迁移到 PostgreSQL。

**Duration:** 2 周  
**Committed:** 37 SP / 7 Stories  
**Buffer:** -5 SP（超容量，可将 3.6 移至 Sprint 2 并行或由 BE-1 加班消化）

### Stories

| # | Story | SP | Owner | 依赖 | AC |
| --- | --- | --- | --- | --- | --- |
| 3.1 | 迁移脚本：`sqlite -> postgres` | 8 | BE-1 | Sprint 2 完成 | 迁移 users/tenants/threads_meta/runs/feedback/knowledge_bases/knowledge_base_documents/index_jobs；幂等（通过业务主键去重：id/thread_id+run_id）；输出记录数对比 |
| 3.2 | 迁移脚本：`token_usage.json -> token_usage` | 5 | BE-2 | 1.4 | 解析 JSON 格式 → 写入 ORM 表；通过 (tenant_id, thread_id, run_id, created_at) 去重；输出迁移统计 |
| 3.3 | 迁移脚本：`memory.json -> Store` | 5 | BE-1 | 2.2 | 遍历 `users/*/memory.json` → 写入对应 Store namespace；通过 (user_id, agent_name) 去重；支持 `--dry-run` |
| 3.4 | 迁移脚本：`feedback.json -> feedback`（历史数据） | 3 | BE-2 | 无 | 若存在历史 `feedback.json` → 导入 SQL 表；通过 (thread_id, run_id, user_id) 去重；幂等 |
| 3.5 | 迁移脚本：`reindex_rag_to_pgvector` | 8 | BE-1 | 2.4 | 以知识库文档为源触发全量 reindex；输出 chunk 数/文档覆盖率；支持 `--collection` 过滤 |
| 3.6 | 迁移脚本：`checkpointer sqlite -> postgres` | 5 | BE-1 | 0.3 | 通过 LangGraph 抽象层读取 SQLite checkpointer → 写入 PostgreSQL；支持 `--thread-id` 过滤；幂等 |
| 3.7 | 迁移脚本集成测试 + 文档 | 3 | BE-2 | 3.1-3.6 | 端到端：SQLite 数据 → 运行全部脚本 → PostgreSQL 验证；更新 README 迁移指南 |

### 依赖图

```
Sprint 2 → 3.1, 3.3, 3.5
1.4 → 3.2
0.3 → 3.6
3.1-3.6 → 3.7
3.4 (独立)
```

### 风险

| 风险 | 缓解 |
| --- | --- |
| 大量历史数据迁移耗时超预期 | 脚本支持 `--batch-size` 分批；3.7 中测量 10K/100K 级别耗时 |
| Chroma 向量维度与 pgvector 配置不匹配 | reindex 从文档重新 embed，不依赖 Chroma 原始向量 |
| `memory.json` 格式在不同版本间有差异 | 脚本增加格式检测和兼容处理；跳过无法解析的条目并记录 |
| Checkpointer SQLite/PostgreSQL schema 版本不一致 | 0.3 调研确认兼容性；若不兼容则走 LangGraph 抽象层逐条读写而非表级搬迁 |
| Sprint 3 超容量（37 SP > 32 SP） | 将 3.6 提前到 Sprint 2 后半段并行启动；或接受 Sprint 3 延期 1-2 天 |

---

## Sprint 4：端到端验收与退役

**Sprint Goal:** 完成 PostgreSQL 模式端到端验收，旧存储标记为只读，更新运维文档。

**Duration:** 2 周  
**Committed:** 31 SP / 7 Stories  
**Buffer:** 1 SP

### Stories

| # | Story | SP | Owner | 依赖 | AC |
| --- | --- | --- | --- | --- | --- |
| 4.1 | 端到端验收测试 | 8 | BE-1 | Sprint 3 完成 | 新建线程→对话→重启→恢复历史；上传知识库→检索→重启→再检索；多用户隔离验证 |
| 4.2 | 多实例并发验证 | 5 | BE-1 | 4.1 | 两个 Gateway 实例同时写入同一 PostgreSQL；验证线程状态、run_events、memory 无冲突；验证 checkpointer 并发安全 |
| 4.3 | 标准切换流程验证 | 5 | BE-2 | 3.7 | 按 §8.3.1 流程执行完整 SQLite→PostgreSQL 切换（注意：`checkpointer.type` 已废弃，仅需设置 `database.backend`）；验证回滚流程（§8.3.2） |
| 4.4 | 旧存储退役：停止写入 + 只读快照 | 3 | BE-1 | 4.1 | postgres 模式下 `token_usage.json`/`memory.json`/Chroma 不再写入；保留只读访问 |
| 4.5 | `run_events`/`token_usage` 归档策略实现 | 3 | BE-2 | 4.1 | 实现基于时间的自动归档（默认保留 90 天）；支持配置 `retention_days`；归档后查询不报错 |
| 4.6 | 运维文档更新 | 5 | BE-2 | 4.1, 4.3 | 更新 CLAUDE.md、README、CONFIGURATION.md；新增迁移操作手册；同步更新设计文档 §8.3.1（删除废弃的 `checkpointer.type`） |
| 4.7 | `content_safety_logs` 表设计（可选） | 2 | BE-1 | 无 | 若决定纳入：新增 ORM Model + Alembic；否则标记为后续 backlog |

### 依赖图

```
Sprint 3 → 4.1, 4.3
4.1 → 4.2
4.1 → 4.4
4.1 → 4.5
3.7 → 4.3
4.1, 4.3 → 4.6
4.7 (独立，可选)
```

### 风险

| 风险 | 缓解 |
| --- | --- |
| 端到端测试发现未覆盖的边界情况 | 4.1 优先覆盖 §11.2 验收标准；发现问题立即修复 |
| 多实例并发写入出现死锁或数据不一致 | LangGraph Provider 内部已有行级锁；4.2 中压测并发场景，必要时调整 pool_size |
| 回滚流程验证不充分 | 4.3 必须在独立环境执行完整回滚并验证数据完整性 |
| 归档策略误删活跃数据 | 归档仅移动到归档表/分区，不物理删除；支持恢复 |
| 文档更新遗漏 | 4.6 使用 checklist 对照 §10 改造清单逐项确认 |

---

## 总览

| Sprint | 目标 | SP | 关键交付 |
| --- | --- | --- | --- |
| Sprint 0 | 环境准备 | 10 | PostgreSQL 实例、CI 容器、Checkpointer schema 调研 |
| Sprint 1 | 配置收口 + token_usage 正式化 | 30 | 启动校验、默认值继承、token_usage ORM |
| Sprint 2 | 运行态切换 + pgvector 正式化 | 31 | run_events/memory 默认切换、pgvector Alembic |
| Sprint 3 | 迁移脚本 | 37 | 6 个迁移脚本 + 集成测试（含 checkpointer） |
| Sprint 4 | 验收与退役 | 31 | E2E 验收、多实例并发、归档策略、文档更新 |
| **合计** | | **139 SP** | **9 周完成全量迁移（含 1 周准备）** |

## 里程碑

| 日期 | 里程碑 |
| --- | --- |
| Sprint 0 结束 | 基础设施就绪，团队对 Checkpointer 迁移方案有结论 |
| Sprint 1 结束 | 配置收口完成，postgres 模式可无分裂启动 |
| Sprint 2 结束 | 所有子系统 postgres 路径就绪，可接受新数据 |
| Sprint 3 结束 | 历史数据可一键迁移，迁移脚本通过集成测试 |
| Sprint 4 结束 | 生产就绪，多实例验证通过，旧存储退役，文档完备 |

## 前置条件

1. PostgreSQL 15+ 实例可用（开发/测试/预发）— Sprint 0 交付
2. pgvector 扩展已安装 — Sprint 0 交付
3. CI 环境支持 PostgreSQL 容器（推荐 `pgvector/pgvector:pg16`）— Sprint 0 交付
4. 团队对 LangGraph Checkpointer/Store 内部表结构有基本了解 — Sprint 0 交付

## Definition of Done

每个 Story 完成标准：

- [ ] 代码通过 `make lint && make test`
- [ ] 新增/修改代码有对应单元测试（覆盖率 ≥ 80%）
- [ ] 不引入新的 harness → app 反向依赖
- [ ] 更新相关 CLAUDE.md 章节（如适用）
- [ ] PR 通过 code review
