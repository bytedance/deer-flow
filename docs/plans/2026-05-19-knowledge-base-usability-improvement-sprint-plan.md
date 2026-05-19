# 知识库可用性改造 Sprint 计划

> **关联设计文档**: [docs/plans/2026-05-19-knowledge-base-usability-improvement-design.md](./2026-05-19-knowledge-base-usability-improvement-design.md)
> **创建日期**: 2026-05-19
> **作者**: Claude

---

## Sprint 概览

| 属性 | 值 |
|------|-----|
| Sprint Goal | 闭环 12 条诊断结论（D-01 ~ D-12），让知识库在生产配置下"可见、可用、可恢复" |
| Duration | 3 Sprints × 2 周 = 6 周（含每周 Demo 与回归窗口） |
| 总估算 | 51 Story Points（A=15 / B=28 / C=8） |
| 涉及模块 | rag config / middleware / tools / vector backend / indexing pipeline / Gateway router / 前端 selector / Alembic |
| 主要约束 | 不破坏现有 140 个 KB 测试用例；不引入 Redis/MQ；默认配置向后兼容；harness boundary（`tests/test_harness_boundary.py`）必须通过 |

诊断结论与 Sprint 映射：

| Sprint | 涉及诊断 ID | 主题 |
|--------|--------------|------|
| A（Week 1-2） | A.0 Alembic baseline + D-01 / D-03 / D-06 / D-07 / D-09 | 配置默认值、跨 KB 排序、Chroma 度量、依赖守卫 |
| B（Week 3-4） | D-02 / D-04 / D-05 / D-11 | 异步索引调度、async-native middleware、KB-bound embedding（lazy）、租户上下文 |
| C（Week 5-6） | D-08 / D-10 / D-12 | 上传错误码、前端选择器、PDF converter 透明化、文档收尾 |

---

## Sprint A：解阻断 + 配置默认收口（Week 1-2）

**Sprint Goal**: 让默认配置下未登录场景的失败"可见"；纠正跨 KB 打分语义；统一 Chroma 度量与召回量；消除 `KbPermissionRepository` 短路依赖；**接入 Alembic 并落地后续两个 Sprint 都依赖的 5 列 baseline 迁移**。所有改动均通过配置开关或保守默认值控制，无需用户修改 `config.yaml` 即可获得正确行为。

**容量**: ~15 Story Points

### Stories

| # | Story | Points | 优先级 | 依赖 | 涉及文件 |
|---|-------|--------|--------|------|----------|
| A.0 | **Alembic 接入 + baseline 迁移**（5 列：`index_queued_at` / `vector_metric_stale` / `embedding_model` / `embedding_dim`，PG `index_status` ENUM 扩展 `pending`/`cancelled`） | 1 | P0 | 无 | `backend/alembic/`(新)、`alembic.ini`(新)、`backend/alembic/env.py`(新)、`backend/alembic/versions/00XX_kb_baseline_for_usability_sprint.py`(新)、`persistence/engine.py` |
| A.1 | RagDecisionEvent dataclass + 枚举 reason + 序列化 helper | 1 | P0 | 无 | `rag/decisions.py`(新) |
| A.2 | RagMiddleware 阻断分支注入 decision，warning 升级 | 1 | P0 | A.1 | `agents/middlewares/rag_middleware.py` |
| A.3 | `search_knowledge_base` tool 返回 `decision` 字段 | 1 | P0 | A.1 | `rag/tools.py` |
| A.4 | 启动期 INFO 日志：allow_no_auth_kb=false 提示 | 0.5 | P1 | A.1 | `app/gateway/app.py` |
| A.5 | `cross_kb_score_strategy` 配置项 + retrieval.py 切换为 absolute 默认 | 2 | P0 | 无 | `config/rag_config.py`、`knowledge_base/retrieval.py` |
| A.6 | KB 优先级打破分数平局（`private > tenant > public`） | 1 | P1 | A.5 | `knowledge_base/retrieval.py` |
| A.7 | `multi_kb_retrieve` 加 INFO 日志：`per_kb=[{kb_id, raw_max, raw_min, returned}]` | 0.5 | P2 | A.5 | `knowledge_base/retrieval.py` |
| A.8 | Chroma `get_or_create_collection` 强制 `hnsw:space=cosine` | 1 | P0 | A.0 | `rag/backends/chroma.py` |
| A.9 | Chroma 检索按 collection metadata metric 选公式 | 1 | P0 | A.8 | `rag/backends/chroma.py` |
| A.10 | KB 表新增 `vector_metric_stale` 字段 + `startup_consistency_check`（在 `langgraph_runtime` 中调用） | 1.5 | P0 | A.0, A.8 | `persistence/knowledge_base/model.py`、`knowledge_base/service.py`、`app/gateway/deps.py` |
| A.11 | `effective_top_k` 计算 + `rerank_recall_factor` 配置 | 1 | P1 | 无 | `agents/middlewares/rag_middleware.py`、`config/rag_config.py` |
| A.12 | 删除 `KbPermissionRepository.__new__` 短路，改 raise ValueError | 0.5 | P0 | 无 | `knowledge_base/service.py` |
| A.13 | 单元 + 集成测试覆盖 A 系列 | 2 | P0 | A.0-A.12 | `tests/test_alembic_baseline_migration.py`(新)、`tests/test_rag_decisions.py`、`tests/test_multi_kb_score_strategies.py`、`tests/test_chroma_metric_aware.py`、`tests/test_recall_factor.py`、`tests/test_kb_service_dependency_guard.py` |

### 验收标准

- [ ] **Alembic baseline 迁移在干净 SQLite 上 `upgrade head` 成功；`downgrade -1` 后再 `upgrade head` 幂等**
- [ ] PG 上 `index_status` ENUM 已扩展 `pending` / `cancelled` 值
- [ ] `rag.allow_no_auth_kb=false` + 未登录 → agent tool 返回 `{"results":[],"decision":{"outcome":"blocked","reason":"no_auth","hint":...}}`
- [ ] `RagMiddleware` 阻断时 `additional_kwargs[KB_DECISION_KEY]` 含 `decision` 对象（前端可读）
- [ ] 启动日志 grep `KB access requires authenticated user` 命中一行
- [ ] `cross_kb_score_strategy=absolute`（默认）下，跨 KB 排序按原始 [0,1] 相似度，**且**单 KB 检索 `score_threshold` 重新生效
- [ ] `cross_kb_score_strategy=normalized` 仍可走旧逻辑（回归测试）
- [ ] 新创建的 Chroma collection metadata 含 `{"hnsw:space":"cosine"}`
- [ ] `langgraph_runtime` 在 `app.state.kb_service` 实例化后调用 `startup_consistency_check`，把已有 L2 collection 的 KB 标 `vector_metric_stale=true`，`multi_kb_retrieve` 跳过并标 `skipped_reason="vector_metric_stale"`；`startup_consistency_check` 内部异常被捕获并 `logger.warning`，不阻塞启动
- [ ] `reranker_enabled=false` 时召回 = `max_injection_chunks`；`reranker_enabled=true` 时召回 = `max_injection_chunks × rerank_recall_factor`，且不超过 `retrieval_top_k`
- [ ] `KnowledgeBaseService(permission_repo=None)` 立刻 `ValueError`，所有调用点已传 perm_repo
- [ ] 既有 140 KB 用例全部通过；新增 ≥ 13 个用例
- [ ] **`pytest tests/test_harness_boundary.py` 通过**（A.0 Alembic 落在 `backend/alembic/`，不属于 harness；A.10 在 service.py 调用，无新 harness→app 引用）

### 技术注意事项

- **A.0 为什么是阻塞所有 column-add 故事的前置**：项目当前 `init_engine_from_config` 走 `Base.metadata.create_all`，它**只创建缺失的表**，**不会**给已有表加列。SQLite 上 `create_all` 不报错也不加列；运行时第一次 `SELECT new_column` 才会炸。所以 A.10 / B.1.2 / B.3.1 都必须排在 A.0 后面。
- **A.0 Alembic env.py**：对接现有 `Base.metadata`（即 `deerflow.persistence.knowledge_base.model.Base`），`target_metadata = Base.metadata`。`run_migrations_online()` 复用 `init_engine_from_config()` 拿到的连接。
- **A.0 SQLite vs PG 差异**：SQLite 没有真正的 ENUM；扩展 `index_status` 在应用层做枚举校验即可。PG 有 `sa.Enum` 类型时需 `op.execute("ALTER TYPE knowledge_base_index_status ADD VALUE 'pending'")`，且不能在 transaction 中执行——用 `op.get_context().autocommit_block()` 包裹。
- **A.5 切换风险**：absolute 模式下若用户自定义了 `score_threshold > 0.6`，可能召回变少。Sprint A 的 `score_threshold` 默认值仍为 `0.0`，不会主动收紧；上线后观察 trace 中 `per_kb_raw_max` 分布再决定是否调高。
- **A.8 / A.10 兼容**：现存 collection 是 L2 时 **不删数据**，仅标记 stale。Sprint B 的 `reindex-all` 才真正"删除旧 collection → 创建新 cosine collection → 重新写入"（Chroma metadata 不可改的硬约束）。这是为了把"配置纠错"和"数据迁移"解耦——A 期完成后即使没跑 B 期，KB 行为是"明确不可用"而不是"假装可用还输出垃圾分数"。
- **A.10 startup_consistency_check 注入位置**：在 [app/gateway/deps.py](../../backend/app/gateway/deps.py) 现有 lines 140-154（`app.state.kb_service` 实例化）之后追加 `await app.state.kb_service.startup_consistency_check()`，try/except 包裹，失败 `logger.warning` 但不抛出（避免阻塞 Gateway 启动）。
- **A.11 `effective_top_k`**：`retrieval_top_k=5` 字段保留语义为"显式工具调用召回上限"——agent 主动 `search_knowledge_base("...", top_k=10)` 时仍受 `retrieval_top_k` 截断保护。
- **A.12 测试桩**：现有 `tests/test_kb_permission_management.py` 桩 fixture 若没传 `permission_repo` 需修复，使用 `AsyncMock(spec=KbPermissionRepository)`。

---

## Sprint B：核心异步化 + KB 维度绑定（Week 3-4）

**Sprint Goal**: 把上传请求生命周期从"等索引完成"切到"立即返回 + 后台调度"；中间件与工具异步原生化；embedding 模型与维度绑定到 KB；后台任务路径下租户上下文显式传递。Sprint B 是改动量最大的一期，结束时性能目标（20 MB PDF P95 ≤ 3 s）必须达成。

**容量**: ~28 Story Points

> **依赖前置**：本 Sprint 多个 Story（B.1.2 状态机扩展、B.3.1 KB embedding 字段）依赖 Sprint A.0 已落地的 Alembic baseline 迁移；启动 B 之前必须验证 `alembic upgrade head` 在测试库上幂等通过。

### Stories

| # | Story | Points | 优先级 | 依赖 | 涉及文件 |
|---|-------|--------|--------|------|----------|
| B.1.1 | `IndexingDispatcher` 类骨架（队列、worker 池、submit/aclose） | 3 | P0 | 无 | `knowledge_base/dispatcher.py`(新) |
| B.1.2 | DB 状态机扩展：`index_status` 枚举加 `pending/cancelled` + `index_queued_at` 字段（**列已由 A.0 Alembic 迁移建好**，本 Story 只补 ORM model + repository 读写路径） | 1 | P0 | A.0 | `persistence/knowledge_base/model.py`、`document_repository.py` |
| B.1.3 | Dispatcher 启动 `recover()`：扫描孤儿 job 重新入队 | 2 | P0 | B.1.1, B.1.2 | `dispatcher.py` |
| B.1.4 | service 层 6 个调用点改 submit + 路由立即返回 202 + `pending`；`indexing_workers==0` 时 fallback 同步 `await execute_index_job` | 3 | P0 | B.1.1 | `app/gateway/routers/knowledge_bases.py`、`knowledge_base/service.py`(`create_document` L161 / `update_document` L226 / `reindex_document` L276 / `create_document_with_access_check` L354 / `update_document_with_access_check` L430 / `reindex_document_with_access_check` L482) |
| B.1.5 | `langgraph_runtime` 注入 dispatcher 到 `app.state.index_dispatcher`，优雅停机等待 worker | 1 | P0 | B.1.1 | `app/gateway/deps.py` |
| B.1.6 | 幂等键 `(kb_id, doc_id, version)` 防重复 submit | 1 | P1 | B.1.1 | `dispatcher.py` |
| B.2.1 | `RagMiddleware.before_agent` 改 async；删除 `_resolve_pool`；**前置：LangChain async hook compat smoke**（在 dev 分支运行 `make test PYTEST_FILTER=test_langchain_async_middleware_compat`，验证 `@override async def before_agent` 与 `state_schema` 类属性在框架升级后语义未变） | 2.5 | P0 | 无 | `agents/middlewares/rag_middleware.py`、`tests/test_langchain_async_middleware_compat.py`(新) |
| B.2.2 | `search_knowledge_base` tool 改 `async def`；删除 `_resolve_pool` | 1 | P0 | 无 | `rag/tools.py` |
| B.2.3 | 多 KB 并行检索：保留 `asyncio.to_thread` 包同步 chroma 调用 | 1 | P1 | B.2.1, B.2.2 | `knowledge_base/retrieval.py` |
| B.2.4 | 错误分类 `rag/errors.py`（`KbResolutionError` / `EmbeddingDimensionMismatchError` / `VectorStoreError`） | 1 | P0 | 无 | `rag/errors.py`(新) |
| B.3.1 | KB 表新增 `embedding_model` / `embedding_dim` 字段（**列已由 A.0 Alembic 迁移建好**） + 创建路径写入 `embedding_model=global_default`、`embedding_dim=0`（占位） | 2 | P0 | A.0 | `persistence/knowledge_base/model.py`、`repository.py`、`knowledge_base/service.py` |
| B.3.2 | `IndexingService.execute_index_job` 首次执行时探测 dim 并回写 `embedding_dim`；后续断言匹配；用 KB row 的 embedding 模型而非全局 | 2 | P0 | B.3.1 | `knowledge_base/indexing.py`、`rag/embeddings.py` |
| B.3.3 | 写入前 dim 断言，失败 raise `EmbeddingDimensionMismatchError` | 1 | P0 | B.3.2 | `rag/ingestion.py`、`rag/backends/chroma.py` |
| B.3.4 | `multi_kb_retrieve` 对每个 KB 用各自 embedding 模型生成查询向量 | 1 | P1 | B.3.2 | `knowledge_base/retrieval.py` |
| B.3.5 | `POST /api/knowledge-bases/{kb_id}/reindex-all`（admin only）：`delete_collection → get_or_create_collection(metadata={"hnsw:space":"cosine"}) → 重派 dispatcher job → 成功后清 vector_metric_stale` | 2 | P1 | B.3.1, B.1.1 | `app/gateway/routers/knowledge_bases.py`、`service.py` |
| B.3.6 | lazy backfill 路径文档：`embedding_dim==0` 的 KB 在首次 `execute_index_job` 时回填，启动期不做阻塞 embedding 调用（与设计 §4.5 收口一致） | 1 | P1 | B.3.1 | `knowledge_base/service.py`、`backend/docs/RAG.md` |
| B.4.1 | `with_kb_context()` async 上下文管理器；**前置：grep `set_current_tenant_id` 调用方，验证现有实现是否 Token-aware**（`backend/packages/harness/deerflow/config/tenant.py`；若 setter 不返回 `Token` 或调用方丢弃 Token——参见 [app/gateway/deps.py#L372](../../backend/app/gateway/deps.py#L372)——则同步升级实现并补 `tests/test_tenant_context_token_reset.py`） | 1.5 | P0 | 无 | `rag/job_context.py`(新)、`config/tenant.py`、`tests/test_tenant_context_token_reset.py`(新) |
| B.4.2 | Dispatcher worker 用 `with_kb_context` 包裹 execute_index_job | 0.5 | P0 | B.4.1, B.1.1 | `dispatcher.py` |
| B.4.3 | `ChromaVectorStore._collection_name` 在 default tenant 且 allow_no_auth_kb=false 时 raise | 0.5 | P0 | B.4.1 | `rag/backends/chroma.py`、`pgvector.py` |
| B.5.1 | 单元测试：dispatcher、async middleware/tool、embedding binding、job_context、**`test_dispatcher_disabled_falls_back_to_sync`**（覆盖设计 §9.2 的 `indexing_workers==0` 回滚路径） | 2 | P0 | B.1-B.4 | `tests/test_indexing_dispatcher.py`、`test_rag_middleware_async.py`、`test_rag_tools_async.py`、`test_kb_embedding_binding.py`、`test_job_context.py` |
| B.5.2 | 性能 smoke：mock embedding 100 ms/调用，断言 20 MB DOCX 上传响应 < 3 s（本地 dev）/< 5 s（CI，由 `os.environ.get("CI") == "true"` 自动切阈值） | 1 | P0 | B.1.4 | `tests/perf/test_upload_async.py` |

### 验收标准

- [ ] `POST /api/knowledge-bases/{kb_id}/documents/upload` 返回 202 + `index_status="pending"`，P95 ≤ 3 s（mock embedding；20 MB DOCX）
- [ ] 5 min 内文档变 `ready`（同 mock embedding 条件下 < 30 s）
- [ ] 进程重启后 `pending`/`running` job 自动恢复执行
- [ ] 重复 submit 同 `(kb_id, doc_id, version)` 不创建第二个 job
- [ ] `RagMiddleware.before_agent` 是 async 协程，全程无 `asyncio.new_event_loop` 调用（monkeypatch 计数器断言为 0）
- [ ] `search_knowledge_base` 工具是 async 协程，错误分类为 `KbResolutionError` / `EmbeddingDimensionMismatchError` / `VectorStoreError`
- [ ] 新建 KB 持久化 `embedding_model` + `embedding_dim`；写入索引时 dim 不匹配立即 raise
- [ ] `reindex-all` 路由能在不丢数据的前提下完成原 chunks → 新 chunks 的原子替换
- [ ] 启动期对 `embedding_dim=0` 的旧 KB 完成回填或标记 stale
- [ ] Dispatcher worker 内 `get_current_tenant_id()` == `job.tenant_id`，**绝不**取到 `default`
- [ ] `tenant_id == "default"` + `allow_no_auth_kb=false` 时调用 `_collection_name` 直接 raise `VectorStoreError`，避免静默查到 `default_kb_xxx`

### 技术注意事项

- **B.1 dispatcher 的并发模型**：单进程 + `asyncio.Task` 池足以应对当前预期负载（1-2 上传/秒）。如果未来要多副本部署，再切换到外部队列（Redis/PG `LISTEN/NOTIFY`），但本期不做。
- **B.1 优雅停机超时**：`langgraph_runtime` 的 finally 等待 dispatcher worker 最长 30 s。超时后剩余 `running` job 在下次启动 `recover()` 时会被重置为 `queued` 重新执行——`IndexingService.execute_index_job` 必须保证幂等（清理旧 chunks → 写新 chunks）。
- **B.2 中间件 async 改造的兼容性**：LangChain Agent Middleware 协议同时支持 sync 和 async hook，`async def before_agent` 与同框架内其他 sync middleware 共存是被官方支持的（见 `langchain.agents.middleware.AgentMiddleware`）。本期前在 dev 分支跑 ≥ 1 周端到端避免回归。
- **B.3 多 KB 跨 embedding 模型查询**：选择 5 个 KB 但跨 3 种 embedding 时，会发起 3 次 embedding 调用（按模型去重）。这是设计上不可避免的——同一 query 必须用同模型生成向量才能与 KB 中的 chunk 比相似度。在 trace 中显式记录 `embedding_models_used: [...]` 以便诊断。
- **B.3 reindex-all 原子性**：写入新 chunks → 删除旧 chunks 必须在同一事务（DB chunks 表）+ 同一批 chroma 操作中完成。失败回滚到旧状态。建议 `chroma.upsert(new_chunks)` 后再 `chroma.delete(old_chunks)`，期间 KB 标 `index_status="reindexing"` 阻止检索路径用到不一致状态。
- **B.4 contextvar 在 `asyncio.Task` 中**：Python 3.7+ 的 `contextvars` 在 `asyncio.create_task` 时会**复制**当前上下文。Dispatcher worker 是常驻 task，启动时 contextvar 是空的，必须在每个 job 内 `with_kb_context()` 显式设置。
- **B.5 性能 smoke 的环境**：CI runner 性能波动大，断言应宽松到 `< 5 s`（≥ 3 s 时 print warning 但不 fail）。本地 dev 环境跑紧的 3 s 断言。

### 实施顺序建议

```
Week 3:
  Day 1-2: B.1.1, B.1.2 (dispatcher 骨架 + DB 字段)
  Day 3-4: B.1.3, B.1.4, B.1.5 (recover + 路由切换 + lifecycle)
  Day 5:   B.1.6 + 单测; 验证 mock embedding 下 P95 ≤ 3s

Week 4:
  Day 1-2: B.2.1 ~ B.2.4 (middleware/tool async 化 + errors)
  Day 3:   B.3.1, B.3.2 (KB embedding 绑定 + indexing 改造)
  Day 4:   B.3.3 ~ B.3.6 (dim 断言 + reindex-all + backfill)
  Day 5:   B.4.1 ~ B.4.3 (job_context + chroma 守卫) + B.5 测试
```

---

## Sprint C：错误码 + 前端体验 + 文档收尾（Week 5-6）

**Sprint Goal**: 把"看起来在动但用户被卡住"的最后几个体验点收掉——上传错误文案化、前端选择器持续清理、PDF converter 透明化；同步更新 README / CLAUDE.md / docs 让运维和开发者了解新行为。

**容量**: ~8 Story Points

### Stories

| # | Story | Points | 优先级 | 依赖 | 涉及文件 |
|---|-------|--------|--------|------|----------|
| C.1.1 | `ConversionErrorCode` 枚举 + `convert_file_to_markdown` 返回 `Result(content, error)` | 1 | P0 | 无 | `utils/file_conversion.py` |
| C.1.2 | 上传路由把 ConversionError 映射到 4xx + structured body | 1 | P0 | C.1.1 | `app/gateway/routers/knowledge_bases.py` |
| C.1.3 | 前端 uploader 按 `code` 文案化 toast | 1 | P1 | C.1.2 | `frontend/src/components/workspace/knowledge-base-uploader.tsx` |
| C.2.1 | 删除 `hasCleaned` ref，改为依赖 `knowledgeBases` 变化的 ID diff effect；`onSelectionChange` 必须用 `useCallback` 稳定引用；Vitest 渲染计数 ≤ 3 次 | 0.5 | P1 | 无 | `frontend/src/components/workspace/knowledge-base-selector.tsx` |
| C.2.2 | Vitest 单测：`removes deleted kb ids when knowledgeBases changes`、`does not loop when selection already stable`、**`render count ≤ 3 on stable props`** | 0.5 | P1 | C.2.1 | `frontend/tests/unit/components/workspace/knowledge-base-selector.test.tsx`(新) |
| C.3.1 | `resolve_pdf_converter()` 工具函数 + 启动 INFO 日志 | 1 | P1 | 无 | `utils/file_conversion.py`、`app/gateway/app.py` |
| C.3.2 | `_convert_binary_file` 输出 < 200 字符返回 `EMPTY_RESULT` | 0.5 | P1 | C.1.1, C.3.1 | `utils/file_conversion.py` |
| C.3.3 | `GET /api/system/pdf-converter`（admin only）返回当前选用项 | 0.5 | P2 | C.3.1 | `app/gateway/routers/system.py` |
| C.4.1 | 更新 [backend/CLAUDE.md](../../backend/CLAUDE.md)：RAG 章节加 dispatcher / async middleware / KB-bound embedding | 0.5 | P0 | Sprint A+B 完成 | `backend/CLAUDE.md` |
| C.4.2 | 更新 [README.md](../../README.md)：列入 `rag.cross_kb_score_strategy` / `rag.indexing_workers` | 0.5 | P1 | Sprint A+B 完成 | `README.md` |
| C.4.3 | 新建 `docs/RAG.md`：三种 cross_kb_score_strategy 取舍 + reindex-all 操作流 | 1 | P1 | Sprint A+B 完成 | `backend/docs/RAG.md`(新) |
| C.4.4 | 更新 [frontend/CLAUDE.md](../../frontend/CLAUDE.md)：上传错误码 → 文案映射表 | 0.5 | P2 | C.1.2 | `frontend/CLAUDE.md` |

### 验收标准

- [ ] 上传加密 PDF → HTTP 422 + `{"detail":{"code":"pdf_encrypted","message":"...","hint":"..."}}`
- [ ] 上传 docx 但服务器没装 markitdown → HTTP 503 + `code:"converter_not_installed"`
- [ ] 前端 uploader 对每种 code 显示对应的中/英文文案（不再统一显示 "Upload failed"）
- [ ] 用户在 settings 页删除 KB-X 后，selector 中的 `selected_ids` 自动剔除 KB-X（无需刷新页面）
- [ ] selector 不会因为 effect 死循环（Vitest 渲染计数 ≤ 3 次）
- [ ] 启动日志 grep `PDF converter selected:` 命中一行
- [ ] 转换输出 < 200 字符的文档创建被拒绝（返回 `empty_result`）
- [ ] `GET /api/system/pdf-converter` 对 admin 返回 `{"name","version","available_converters":[...]}`
- [ ] `backend/CLAUDE.md` / `README.md` / `frontend/CLAUDE.md` 中能搜到 dispatcher、cross_kb_score_strategy、conversion_error_codes 等新概念

### 技术注意事项

- **C.1.3 文案表**：先在 frontend/CLAUDE.md 列出 code → 文案映射，作为 source of truth；i18n 框架接入（如 react-intl）属于后续优化，本期用硬编码 zh-CN map。
- **C.2.1 死循环防护**：`onSelectionChange` 必须用 `useCallback` 稳定引用；Vitest 测试中显式断言"selection 已是合法集合时不触发 onChange"。
- **C.3.2 阈值 200**：来自经验值——一份 1 页 A4 中文 PDF 大约 500-800 字符；阈值 200 既能拦"几乎全空"又不会误伤"故意短的便签"。可后续做成配置 `pdf_min_chars`，本期硬编码。

---

## 依赖关系图

```
Sprint A:
  A.1 → A.2, A.3, A.4
  A.5 → A.6, A.7
  A.8 → A.9, A.10
  A.1-A.12 → A.13

Sprint B:
  B.1.1 → B.1.3, B.1.4, B.1.5, B.1.6 → B.5.2
  B.1.2 → B.1.4
  B.2.1, B.2.2 → B.2.3, B.2.4 (并行)
  B.3.1 → B.3.2 → B.3.3, B.3.4, B.3.5
  B.3.1 → B.3.6
  B.4.1 → B.4.2, B.4.3
  B.1, B.2, B.3, B.4 → B.5.1

Sprint C:
  C.1.1 → C.1.2 → C.1.3
  C.2.1 → C.2.2
  C.3.1 → C.3.2, C.3.3
  Sprint A+B 完成 → C.4.1, C.4.2, C.4.3, C.4.4
```

---

## 风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| Dispatcher 单进程瓶颈，高并发上传时队列堆积 | 中 | 中 | 队列容量 1024 + 满队列时 503；后续多副本时切外部 MQ |
| `cross_kb_score_strategy=absolute` 让用户感知"召回变少" | 低 | 中 | 配置开关回退 `normalized`；trace 字段记录策略名便于支持 |
| Embedding 维度回填失败 → KB 长期 stale | 中 | 低 | 启动期 warning + admin `reindex-all`；UI 在 KB 详情页显示 stale 徽标 |
| async middleware 与 sync agent runtime 不兼容 | 高 | 低 | dev 分支跑 ≥ 1 周 e2e 后再合主干 |
| Chroma 强制 cosine 后旧 L2 collection 全部 stale | 中 | 高 | 启动检查只标记不删除；admin 触发 `reindex-all` 重建 |
| dispatcher 优雅停机超时丢失运行中 job 状态 | 中 | 低 | `recover()` 把 `running` 视为孤儿重置 `queued` + `IndexingService.execute_index_job` 幂等清理 |
| `with_kb_context` 漏在某条新代码路径 → tenant 漂移 | 高 | 中 | `_collection_name` 守卫 raise；CI 加 grep `set_current_tenant_id` 调用方覆盖率 |
| 前端 selector 死循环 | 中 | 低 | `onSelectionChange` 必须 `useCallback`；Vitest 渲染计数断言 |
| reindex-all 长时间运行阻塞其他 worker | 中 | 中 | reindex-all 拆成多个 dispatcher job（按 doc 粒度），不占独立 worker |
| 启动 backfill 任务阻塞 Gateway 启动 | 低 | 低 | backfill 异步派发到 dispatcher，不在 lifespan 同步等待 |

---

## 关键技术决策

1. **改默认值，不改契约**：所有改动通过新增配置项 + 保守默认值落地，旧 `config.yaml` 启动后行为等价于"开了 absolute 排序 + 异步索引"，无需用户主动改字段。
2. **可见地失败优于静默通过**：`RagDecisionEvent` 让"被拒绝"在 SSE / log / agent 输出三处都有迹可循。
3. **数据修复与配置修正解耦**：A 期把"未来新数据走 cosine + KB-bound embedding"，B 期才提供 `reindex-all` 修旧数据。这样即使 B 期延期，A 期单独发布也是"明确不可用"而不是"看起来正常但分数不对"。
4. **dispatcher 单进程足够**：基于当前预期负载（1-2 上传/秒），不引入 Redis/MQ；多副本部署时再换。
5. **embedding 模型与 KB 终身绑定**：换全局 embedding 不会破坏旧 KB；reindex-all 是显式的迁移路径。
6. **优先级打破分数平局**：`private > tenant > public` 让用户私有库的相同分稍占优，匹配大多数用户对"我自己上传的资料应该排前面"的直觉。

---

## Definition of Done

每个 Story 完成标准：

- [ ] 代码实现通过 Code Review（满足 [backend/CLAUDE.md](../../backend/CLAUDE.md) 和 [frontend/CLAUDE.md](../../frontend/CLAUDE.md) 的格式约定）
- [ ] 单元/集成测试编写并通过；新增测试 ≥ 设计文档 §8.2 列出的数量
- [ ] `make test` 全绿；既有 140 个 KB 用例继续通过
- [ ] 不引入新的安全漏洞（权限校验完整，租户上下文不漂移）
- [ ] 向后兼容：旧 `config.yaml` 启动行为正确
- [ ] 相关文档更新到位（具体见 §C.4 stories）

每个 Sprint 完成标准：

- [ ] 所有 Story 已 close
- [ ] Sprint 目标对应的"验收标准"全部达成
- [ ] 性能 smoke（仅 Sprint B）达标
- [ ] **`pytest tests/test_harness_boundary.py` 通过**（每个 Sprint 都必须验证 — Sprint A 因 A.10 注入到 `app/gateway/deps.py`、Sprint B 因 B.1.5 / B.4.1 触及 deps.py 与 harness 边界、Sprint C 因 C.3.3 新增 `app/gateway/routers/system.py`，全部需要确认无新增 harness→app 引用）
- [ ] Sprint Review 演示通过

整个交付完成标准（对齐设计文档 §11）：

- [ ] 12 条诊断结论全部映射到具体 Story 并完成
- [ ] 既有 140 个 KB 测试全部通过，新增测试 ≥ 25 个
- [ ] 上传 20 MB PDF P95 ≤ 3 s，索引 5 min 内 ready（mock embedding 时 < 30 s）
- [ ] 多 KB 检索 trace 字段含 `strategy` / `per_kb_raw_max` / `skipped_reason`
- [ ] `rag.allow_no_auth_kb=false` 模式下未登录调用得到结构化 `decision.reason="no_auth"` 而非空结果
- [ ] `KnowledgeBaseRow` 含 `embedding_model + embedding_dim`；新建 KB 写入正确
- [ ] Chroma collection metadata 含 `hnsw:space=cosine`
- [ ] 前端选择器在 KB 列表变化时自动清理失效 ID
- [ ] [backend/CLAUDE.md](../../backend/CLAUDE.md) / [README.md](../../README.md) 已更新

---

## 实施顺序建议（按周）

```
Week 1: A.1 ~ A.7      (decision event + cross_kb_score)
Week 2: A.8 ~ A.13     (chroma metric + recall factor + perm 守卫 + 测试)
Week 3: B.1.1 ~ B.1.6  (dispatcher 全套 + 路由切换)
Week 3: B.2.1 ~ B.2.4  (并行：async middleware/tool + errors)
Week 4: B.3.1 ~ B.3.6  (KB-bound embedding + reindex-all + backfill)
Week 4: B.4.1 ~ B.4.3  (job_context + chroma 守卫)
Week 4 末: B.5.1 + B.5.2  (测试 + 性能 smoke)
Week 5: C.1 + C.2       (上传错误码 + 前端选择器)
Week 6: C.3 + C.4       (PDF converter 透明化 + 文档更新)
```

每周结束 Demo：
- Week 1: 演示 absolute score + decision event 在 SSE 中可见
- Week 2: 演示 cosine 强制 + 启动 stale 标记
- Week 3: 演示上传 P95 ≤ 3 s + 进程重启后 job 恢复
- Week 4: 演示 reindex-all + 多 KB 跨 embedding 检索
- Week 5: 演示加密 PDF 上传报 422 + 前端 toast 文案 + selector 自动清理
- Week 6: 演示 admin 接口 `/api/system/pdf-converter` + 全套文档更新

---

## 实施状态

> 实施过程中按 Story 粒度更新。每完成一个 Story 把 `[ ]` 改成 `[x]` 并补 1-2 行实测笔记（如发现的边界、被推翻的假设）。

### Sprint A — 待启动

| # | Story | 状态 | 备注 |
|---|-------|------|------|
| A.0 | Alembic 接入 + 5 列 baseline 迁移 | [ ] | P0 阻塞所有 column-add 故事 |
| A.1 | RagDecisionEvent dataclass | [ ] | |
| A.2 | RagMiddleware 阻断分支注入 decision | [ ] | |
| A.3 | search_knowledge_base tool 返回 decision | [ ] | |
| A.4 | 启动期 INFO 日志 | [ ] | |
| A.5 | cross_kb_score_strategy + absolute 默认 | [ ] | |
| A.6 | KB 优先级打破平局 | [ ] | |
| A.7 | multi_kb_retrieve INFO 日志 | [ ] | |
| A.8 | Chroma 强制 cosine | [ ] | |
| A.9 | metric-aware score 公式 | [ ] | |
| A.10 | vector_metric_stale + startup check | [ ] | |
| A.11 | effective_top_k + rerank_recall_factor | [ ] | |
| A.12 | KbPermissionRepository 强制依赖 | [ ] | |
| A.13 | A 系列单测 | [ ] | |

### Sprint B — 待启动

| # | Story | 状态 | 备注 |
|---|-------|------|------|
| B.1.1 | IndexingDispatcher 骨架 | [ ] | |
| B.1.2 | DB 状态机扩展 | [ ] | |
| B.1.3 | recover() 启动钩子 | [ ] | |
| B.1.4 | 路由切换 202 + pending | [ ] | |
| B.1.5 | langgraph_runtime 注入 + 优雅停机 | [ ] | |
| B.1.6 | 幂等键防重复 submit | [ ] | |
| B.2.1 | RagMiddleware async 化 | [ ] | |
| B.2.2 | search_knowledge_base async 化 | [ ] | |
| B.2.3 | 多 KB 并行检索 | [ ] | |
| B.2.4 | rag/errors.py 错误分类 | [ ] | |
| B.3.1 | KB embedding 字段 + 创建写入 | [ ] | |
| B.3.2 | IndexingService 用 KB embedding | [ ] | |
| B.3.3 | dim 断言 + raise | [ ] | |
| B.3.4 | multi_kb_retrieve 跨模型查询 | [ ] | |
| B.3.5 | reindex-all 路由 | [ ] | |
| B.3.6 | 启动 backfill | [ ] | |
| B.4.1 | with_kb_context | [ ] | |
| B.4.2 | dispatcher worker 用 with_kb_context | [ ] | |
| B.4.3 | chroma _collection_name 守卫 | [ ] | |
| B.5.1 | B 系列单测 | [ ] | |
| B.5.2 | 性能 smoke | [ ] | |

### Sprint C — 待启动

| # | Story | 状态 | 备注 |
|---|-------|------|------|
| C.1.1 | ConversionErrorCode + Result 返回 | [ ] | |
| C.1.2 | 路由错误码映射 | [ ] | |
| C.1.3 | 前端 toast 文案化 | [ ] | |
| C.2.1 | selector 持续清理 | [ ] | |
| C.2.2 | selector Vitest 单测 | [ ] | |
| C.3.1 | resolve_pdf_converter + 启动日志 | [ ] | |
| C.3.2 | EMPTY_RESULT 阈值拒绝 | [ ] | |
| C.3.3 | GET /api/system/pdf-converter | [ ] | |
| C.4.1 | backend/CLAUDE.md 更新 | [ ] | |
| C.4.2 | README.md 更新 | [ ] | |
| C.4.3 | 新建 docs/RAG.md | [ ] | |
| C.4.4 | frontend/CLAUDE.md 更新 | [ ] | |

---

## 附录

### A. Story → 诊断 ID 反查

| 诊断 ID | 主题 | Sprint | Story |
|---------|------|--------|-------|
| D-01 | 默认配置可见失败 | A | A.1 / A.2 / A.3 / A.4 |
| D-02 | 后台异步索引 | B | B.1.* / B.5.2 |
| D-03 | 跨 KB 绝对分排序 | A | A.5 / A.6 / A.7 |
| D-04 | async-native middleware/tool | B | B.2.* |
| D-05 | KB-bound embedding | B | B.3.* |
| D-06 | Chroma metric 适配 | A | A.8 / A.9 / A.10 |
| D-07 | retrieval_top_k vs injection 一致化 | A | A.11 |
| D-08 | 上传错误粒度 | C | C.1.* |
| D-09 | KbPermissionRepository 守卫 | A | A.12 |
| D-10 | 前端选择器持续清理 | C | C.2.* |
| D-11 | 后台租户上下文 | B | B.4.* |
| D-12 | pdf_converter 透明化 | C | C.3.* |

### B. 新增 / 修改文件速查

新增：

- `backend/alembic/`（目录）
- `backend/alembic.ini`
- `backend/alembic/env.py`
- `backend/alembic/script.py.mako`
- `backend/alembic/versions/00XX_kb_baseline_for_usability_sprint.py`
- `backend/packages/harness/deerflow/rag/decisions.py`
- `backend/packages/harness/deerflow/rag/errors.py`
- `backend/packages/harness/deerflow/rag/job_context.py`
- `backend/packages/harness/deerflow/knowledge_base/dispatcher.py`
- `backend/docs/RAG.md`
- `backend/tests/test_alembic_baseline_migration.py`
- `backend/tests/test_rag_decisions.py`
- `backend/tests/test_indexing_dispatcher.py`
- `backend/tests/test_multi_kb_score_strategies.py`
- `backend/tests/test_rag_middleware_async.py`
- `backend/tests/test_langchain_async_middleware_compat.py`
- `backend/tests/test_rag_tools_async.py`
- `backend/tests/test_kb_embedding_binding.py`
- `backend/tests/test_chroma_metric_aware.py`
- `backend/tests/test_recall_factor.py`
- `backend/tests/test_conversion_error_codes.py`
- `backend/tests/test_kb_service_dependency_guard.py`
- `backend/tests/test_job_context.py`
- `backend/tests/test_tenant_context_token_reset.py`
- `backend/tests/test_pdf_converter_resolution.py`
- `backend/tests/perf/test_upload_async.py`
- `frontend/tests/unit/components/workspace/knowledge-base-selector.test.tsx`

修改：
- `backend/packages/harness/deerflow/config/rag_config.py`
- `backend/packages/harness/deerflow/agents/middlewares/rag_middleware.py`
- `backend/packages/harness/deerflow/rag/tools.py`
- `backend/packages/harness/deerflow/rag/embeddings.py`
- `backend/packages/harness/deerflow/rag/ingestion.py`
- `backend/packages/harness/deerflow/rag/backends/chroma.py`
- `backend/packages/harness/deerflow/rag/backends/pgvector.py`
- `backend/packages/harness/deerflow/knowledge_base/service.py`
- `backend/packages/harness/deerflow/knowledge_base/indexing.py`
- `backend/packages/harness/deerflow/knowledge_base/retrieval.py`
- `backend/packages/harness/deerflow/persistence/knowledge_base/model.py`
- `backend/packages/harness/deerflow/persistence/knowledge_base/repository.py`
- `backend/packages/harness/deerflow/persistence/knowledge_base/document_repository.py`
- `backend/packages/harness/deerflow/utils/file_conversion.py`
- `backend/app/gateway/app.py`
- `backend/app/gateway/deps.py`
- `backend/app/gateway/routers/knowledge_bases.py`
- `backend/app/gateway/routers/system.py`
- `frontend/src/components/workspace/knowledge-base-selector.tsx`
- `frontend/src/components/workspace/knowledge-base-uploader.tsx`
- `config.yaml`
- `README.md`
- `backend/CLAUDE.md`
- `frontend/CLAUDE.md`

### C. 配置变更速查

```yaml
rag:
  cross_kb_score_strategy: absolute        # 新增；absolute | normalized | rrf
  rerank_recall_factor: 3                  # 新增；reranker_enabled=true 时生效
  indexing_workers: 2                      # 新增；后台索引并发度
  indexing_queue_size: 1024                # 新增；队列缓冲
```

> 所有新增字段都有保守默认值，旧 `config.yaml` 启动后无需修改即可获得正确行为。
