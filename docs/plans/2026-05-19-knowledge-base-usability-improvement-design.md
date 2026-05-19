# 知识库可用性改造设计方案

> **范围**：针对 [2026-05-19 知识库诊断报告](#) 列出的 12 条问题，给出从配置默认值、检索打分语义、异步索引到前端体验的端到端改造设计。**不修改**已落地的多级权限模型 / DSL 模板平台 / 上传链路的契约边界，只在内部实现层做收口。
>
> **关联文档**：
> - 多级知识库设计：[2026-05-10-multi-level-knowledge-base-design.md](./2026-05-10-multi-level-knowledge-base-design.md)
> - 多级知识库 Sprint：[2026-05-10-multi-level-kb-sprint-plan.md](./2026-05-10-multi-level-kb-sprint-plan.md)
> - PostgreSQL 存储迁移：[2026-05-08-postgresql-storage-migration-design.md](./2026-05-08-postgresql-storage-migration-design.md)
> - 后端架构指南：[backend/CLAUDE.md](../../backend/CLAUDE.md)
> - 前端架构指南：[frontend/CLAUDE.md](../../frontend/CLAUDE.md)
>
> **创建日期**：2026-05-19
>
> **作者**：诊断责任人 → Claude

---

## 1. 背景

知识库（KB）模块当前 6 个测试文件 / 140 用例全绿，权限模型、SQL 仓储、检索拓扑、HTTP 路由的契约层面没有问题。但通过对运行时代码、配置默认值、异步范式、跨 KB 排序逻辑、前端交互的走查，发现 12 条会让"代码看似正确但实际不好用"的问题。

诊断结论按优先级汇总：

| ID | 优先级 | 主题 | 影响域 |
|----|--------|------|--------|
| D-01 | P0 | `allow_no_auth_kb=False` 默认值导致无登录场景静默失败 | 配置 / 中间件 / 工具 |
| D-02 | P0 | 上传时同步阻塞索引，大文件让 HTTP 长时间挂起 | Gateway 路由 / 索引服务 |
| D-03 | P0 | 跨 KB per-KB min-max 归一化使分数失去物理含义 | 多 KB 检索排序 |
| D-04 | P1 | RagMiddleware / RAG tools 中 async-in-sync 事件循环反模式 | Agent 中间件 / 工具 |
| D-05 | P1 | Embedding 模型与向量库维度耦合且无防护 | Embedding / 向量库 |
| D-06 | P1 | Chroma 距离→分数公式假设 cosine，不一定成立 | 向量库后端 |
| D-07 | P1 | `retrieval_top_k` 与 `max_injection_chunks` 不一致造成空跑 | 配置 |
| D-08 | P2 | 文件上传错误粒度过粗 | Gateway 路由 |
| D-09 | P2 | `KbPermissionRepository.__new__` 短路在缺依赖时炸 | Service 构造 |
| D-10 | P2 | 前端选择器只在 mount 时清理一次失效 KB ID | 前端组件 |
| D-11 | P2 | 后台任务路径下租户上下文易丢成 `default` | 向量库后端 |
| D-12 | P2 | `pdf_converter: auto` 缺依赖时静默回退到弱实现 | 上传 / 文件转换 |

> **指导原则**：以"少改契约、多改实现"为核心，所有改动保持向后兼容；任何会动公开 API/CLI 行为的修改都以"配置开关 + 默认旧行为"先行，下个 Sprint 再切换默认。

---

## 2. 设计目标

### 2.1 必须满足

1. 12 条诊断结论全部得到处置，每条都有"改造方案 + 验收检查 + 回归测试"。
2. 所有现存 140 个 KB 测试用例继续通过，不允许修改既有契约测试以"绕过"问题。
3. 默认配置下，未登录场景的失败行为对开发者**可见**（日志或 API 错误结构化提示），不再静默 short-circuit。
4. 大文件上传（≤20 MB）的 HTTP 请求 P95 ≤ 3 s（实际索引在后台跑）。
5. 多 KB 检索结果的相对顺序由"原始相似度"主导，关闭归一化后单 KB 检索结果不变。
6. 关键路径（中间件、agent tool）的事件循环不再每次新建。

### 2.2 非目标

1. **不**重写多级权限模型（RBAC + visibility）。
2. **不**重做 RAG ingestion 的切块策略 / 语义切分；`chunk_strategy` 维持 `recursive`。
3. **不**引入 Redis / RabbitMQ 等新基础设施；后台索引 worker 用 `asyncio.Task` 池 + DB-backed 状态机即可。
4. **不**强制启用 reranker；保留 `reranker_enabled=false` 默认值。
5. **不**在本期切换向量库后端从 Chroma 到 pgvector（PG 迁移有独立设计文档）。

---

## 3. 总体架构变更示意

```
                          ┌────────────────────────────────────────────┐
                          │   Gateway Routers (FastAPI)                │
                          │   /api/knowledge-bases/...                 │
                          └───────────────┬────────────────────────────┘
                                          │
            ┌─────────────────────────────┼──────────────────────────────┐
            │                             │                              │
   sync (read paths)              ★ async upload return 202         ★ explicit error mapper
            │                             │                              │
            ▼                             ▼                              ▼
   KnowledgeBaseService           KnowledgeBaseService          UploadErrorMapper
                                          │ enqueue
                                          ▼
                              ★ IndexingDispatcher (new)
                                  ├── DB-backed job queue (IndexJobRow)
                                  ├── single-process asyncio.Task pool
                                  └── tenant_id propagation via JobContext
                                          │
            ┌─────────────────────────────┴──────────────────────────────┐
            │                                                            │
            ▼                                                            ▼
   ★ Async-native RAG tools                            ★ MultiKbRetriever (refactored)
   (LangChain @tool async; reuse loop)                  ├── absolute-score path (default)
                                                        ├── optional per-KB normalization
   ★ RagMiddleware (async hooks)                        ├── cross-encoder rerank stage
                                                        └── Chroma metric-aware score()

                                          │
                                          ▼
                         ★ Vector store layer
                            ├── Chroma: enforce hnsw:space=cosine
                            ├── KB-bound embedding_model + dim
                            └── tenant ContextVar guard

(★ = changed in this design)
```

---

## 4. 详细设计

> 每条诊断结论一节，结构：**现状 → 目标 → 设计 → 影响面 → 测试**。

### 4.1 D-01 — 默认配置在无登录场景必须"可见地失败"

**现状**

[backend/packages/harness/deerflow/config/rag_config.py:108-112](../../backend/packages/harness/deerflow/config/rag_config.py#L108-L112)

```python
allow_no_auth_kb: bool = Field(default=False, ...)
```

[rag_middleware.py:153-156](../../backend/packages/harness/deerflow/agents/middlewares/rag_middleware.py#L153-L156) 与 [rag/tools.py:103,163](../../backend/packages/harness/deerflow/rag/tools.py#L103) 在 `user_id == "default"` 且 `allow_no_auth_kb=False` 时直接 `return None` 或返回错误 JSON，且仅 `logger.debug`。

**目标**

- 不放宽默认值（生产安全）。
- 让"被拒绝"在**任何模式**下都对开发者可见——无论是 SSE 调试、agent tool 输出还是 Gateway 日志。

**设计**

1. 新增 `RagDecisionEvent` dataclass（`deerflow/rag/decisions.py`），携带：
   - `decision`: `"injected" | "blocked" | "skipped"`
   - `reason`: 枚举字符串（`"no_auth"`, `"rag_disabled"`, `"injection_disabled"`, `"empty_query"`, `"db_unavailable"`, `"no_results"`）
   - `query_preview`: 前 80 字符
   - `tenant_id`, `user_id`
2. `RagMiddleware._is_no_auth_kb_blocked` 与 `rag/tools.py` 阻断分支统一改成：
   - `logger.warning` 升级（不再 debug）
   - 写入 `_rag_retrieval_context` 一个 `decision_event` 字段
   - `after_agent` 把 event 序列化进 `additional_kwargs[KB_DECISION_KEY]`
3. `search_knowledge_base` 工具返回新的 JSON 结构：

```json
{
  "results": [],
  "decision": {
    "outcome": "blocked",
    "reason": "no_auth",
    "hint": "Knowledge base access requires authentication. Set rag.allow_no_auth_kb=true for dev mode."
  }
}
```

LLM 看到 `hint` 字段会自然地解释给用户而不是默默吞掉。

4. 启动期日志：`AppConfig.from_file()` 加载完成后，若 `rag.enabled=true` 且 `auth.enabled=true` 且 `rag.allow_no_auth_kb=false`，打印一行 `INFO`："KB access requires authenticated user; default user will be denied. (rag.allow_no_auth_kb=false)"。

**影响面**

- `agents/middlewares/rag_middleware.py`: 阻断分支注入 decision；新增字段 `KB_DECISION_KEY = "knowledge_base_decision"`。
- `rag/tools.py`: 工具响应 schema 增加 `decision` 字段（向后兼容——已有 `error` 字段保留）。
- `app/gateway/app.py`: 启动日志一行。
- 前端可选：`message` 渲染时检测到 `decision.reason == "no_auth"` 显示 toast，但属于 P3 nice-to-have。

**测试**

- `tests/test_rag_decision_logging.py`（新）：
  - `test_no_auth_blocked_emits_decision_event`
  - `test_rag_disabled_emits_skipped_decision`
  - `test_blocked_decision_serialized_to_message_kwargs`

---

### 4.2 D-02 — 上传文件后台异步索引

**现状**

[knowledge_bases.py:471-529](../../backend/app/gateway/routers/knowledge_bases.py#L471-L529) 上传路径同步等待 `create_document_with_access_check`，内部 [indexing.py:68-74](../../backend/packages/harness/deerflow/knowledge_base/indexing.py#L68-L74) 用 `asyncio.to_thread(ingestor.ingest_text, ...)` 在请求生命周期内跑切块 + embedding。20 MB PDF 实际 P95 = 解析 + chunking + 几十次 embedding RPC ≈ 20–120 s。

**目标**

- HTTP `POST /api/knowledge-bases/{kb_id}/documents/upload` P95 ≤ 3 s。
- 客户端立即获得 `document_id` 与 `index_status="pending"`，前端轮询 `GET /{kb_id}/documents/{doc_id}` 查看状态变化（`pending → indexing → ready | failed`）。
- 不丢任务：进程重启后未完成的 `IndexJobRow` 在启动期重新拉起。

**设计**

1. 新增 `IndexingDispatcher`（`deerflow/knowledge_base/dispatcher.py`）：
   - 单例，应用启动期由 `langgraph_runtime` 拉起，存到 `app.state.index_dispatcher`。
   - 内部维护：
     - `asyncio.Queue[IndexJobRef]`（容量 1024，溢出转写 DB 排队）
     - `asyncio.Task` 池（默认 `concurrency = 2`，可配 `rag.indexing_workers`）
     - 每个 worker 循环：`await queue.get() → load job → set running → execute → finalize`
   - `submit(job_ref)` 公共方法：先把 `IndexJobRow.status="queued"`，再 `queue.put_nowait`。
   - 启动钩子 `recover()`：扫描 `IndexJobRow.status in ("queued","running")` 重新入队（`running` 视为孤儿，重置为 `queued`）。
2. `IndexingService.execute_index_job` 不变（已经是 async），但**只**通过 dispatcher 调度，不再被路由直接 await。
3. 路由改造：
   - `create_document_with_access_check` 内部不再 `await self._indexing.execute_index_job(...)`；改为 `await self._dispatch.submit(...)`，立即返回 `index_status="pending"`。
   - `upload_document` 同上。
4. 文档表新增字段（迁移见 §5.1）：
   - `index_status` 已存在，扩展枚举：`pending | indexing | ready | failed | cancelled`。
   - `index_queued_at: datetime | None`。
5. **跟踪 ID 不重复**：dispatcher 用 `(kb_id, doc_id, version)` 作幂等键；同 doc 同 version 重复 submit 直接跳过（已有未完成 job）。
6. **优雅停机**：`langgraph_runtime` 的 finally 阶段，dispatcher `aclose()` 等待当前 worker 完成（最长 30 s）；超时则把这些 job 状态保持 `running`，下次启动 `recover()` 接管。

**影响面**

- 新文件：`deerflow/knowledge_base/dispatcher.py`、`tests/test_indexing_dispatcher.py`。
- 修改：`app/gateway/deps.py` 在 `langgraph_runtime` 中注入 dispatcher；`knowledge_base/service.py` 的 `create_document_with_access_check` / `upload_document` / `update_document_with_access_check` / `reindex_document_with_access_check` 改为 `await dispatcher.submit(...)`。
- API 响应：`DocumentResponse` 仍带 `index_status` 字段，前端无需改 schema；只需轮询行为微调。
- 配置：`rag_config.py` 新增 `indexing_workers: int = 2`、`indexing_queue_size: int = 1024`。

**测试**

- `test_dispatcher_submit_then_completes`
- `test_dispatcher_recovers_orphan_running_jobs_on_startup`
- `test_dispatcher_rejects_duplicate_kb_doc_version`
- `test_upload_returns_202_pending_status`
- 端到端：`test_e2e_upload_pdf_returns_quickly_then_indexes`（mock embedding，断言 ≤ 3 s 返回 + 5 s 内变 ready）

---

### 4.3 D-03 — 多 KB 检索打分使用绝对相似度

**现状**

[knowledge_base/retrieval.py:195-200](../../backend/packages/harness/deerflow/knowledge_base/retrieval.py#L195-L200) 每个 KB 独立 `normalize_scores`（min-max → [0,1]），导致每个 KB 的最高分都是 1.0。两个 KB 的最高 chunk 在合并排序中并列。

**目标**

- 合并多 KB 结果时使用**原始相似度分数**（已是 [0,1] 区间，因为 Chroma backend 输出 `1 - distance/2`）。
- 仍允许**单 KB 内部**的 min-max 用于"相对排序信号"，但这只用于 rerank 阶段的特征，不参与跨 KB 排序。
- `score_threshold` 字段重新生效。

**设计**

1. `multi_kb_retrieve` 新行为：
   - 不再调用 `normalize_scores(kb_results)`。
   - 直接 `all_results.extend(kb_results)`。
   - 排序前按 `score_threshold` 过滤（之前因为归一化形同虚设）。
2. 配置新增 `cross_kb_score_strategy: Literal["absolute", "normalized", "rrf"] = "absolute"`：
   - `absolute`（默认）：本期目标行为。
   - `normalized`：保留旧行为做回归测试。
   - `rrf`（reciprocal rank fusion）：Stretch，下一期再开（rank-based fusion，对 score 敏感低）。
3. **排序稳定性**：`score` 相同时退化为 `(kb_priority, doc_id, chunk_index)`：
   - `kb_priority`：visibility 优先级 `private(3) > tenant(2) > public(1)`，让用户私有库的相同分稍占优。
4. 单 KB 检索调用方（`_search_single_collection`）走的也是 `multi_kb_retrieve`，本次不变（行为等价，因为 1 个 KB 的归一化已经把相似度抹平到 1.0，反而比"绝对分"更不准——单 KB 同样收益）。
5. 日志加固：每次 `multi_kb_retrieve` 结束打印一行 `INFO`：`per_kb=[{kb_id,kb_name,raw_max,raw_min,returned}], threshold=X, total=Y`，便于线上诊断检索质量。

**影响面**

- 修改：`knowledge_base/retrieval.py`、`config/rag_config.py`、`tests/test_knowledge_base_retrieval.py`（不破坏既有断言；新增"绝对分胜过 0.95 → 0.5"的场景）。
- 不影响契约：返回的 `SearchResult.score` 还是 [0,1] 浮点。
- 不影响前端：trace 字段不变。

**测试**

- `test_multi_kb_uses_absolute_scores_by_default`
- `test_multi_kb_legacy_normalization_when_strategy_normalized`
- `test_score_threshold_filters_in_absolute_mode`
- `test_kb_priority_breaks_score_ties`

---

### 4.4 D-04 — 中间件与工具异步原生化

**现状**

[rag_middleware.py:142-150](../../backend/packages/harness/deerflow/agents/middlewares/rag_middleware.py#L142-L150) 与 [rag/tools.py:72-79](../../backend/packages/harness/deerflow/rag/tools.py#L72-L79) 都用：

```python
_resolve_pool = ThreadPoolExecutor(max_workers=2)

def _run_async():
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
_resolve_pool.submit(_run_async).result(timeout=10)
```

每次都 new + close 事件循环，aiosqlite/SQLAlchemy 连接池无法复用；`max_workers=2` 全进程瓶颈；`timeout` 触发只看到一行 timeout 不知道底层错。

**目标**

- 单一长期运行的事件循环（即 LangGraph runtime 主循环）。
- 任何 KB 异步调用直接 `await`，不再跨 executor。
- 错误分类：超时、DB 不可达、维度不匹配各自有独立异常类型。

**设计**

1. **RagMiddleware 异步化**：LangChain Agent middleware 已支持 `async def before_agent` / `async def after_agent`（`AgentMiddleware` 协议）。改造：
   - `class RagMiddleware(AgentMiddleware[State])` 的 `before_agent` 改成 `async def before_agent`。
   - `_resolve_kb_selection` / `_retrieve_from_selected_kbs` 变 async，直接 `await resolve_runtime_kb_selection(runtime)` / `await repo.resolve_accessible_by_ids(...)`。
   - `_resolve_pool` 整体删除。
2. **Tool 异步化**：LangChain `@tool` 接受 `async def`。改造：
   - `search_knowledge_base` 标注 `async def`。
   - `_resolve_kb_selection` / `_search_selected_kbs` / `_search_single_collection` 全部 async。
3. **多 KB 检索内部仍可并行**：保留 `ThreadPoolExecutor` 用于 `retriever.retrieve(...)`（同步调用 chroma），但把外层包装改成 `asyncio.gather(asyncio.to_thread(...))`，事件循环本身不动。
4. **错误分类**（新建 `deerflow/rag/errors.py`）：
   - `KbResolutionError(reason: Literal["timeout", "db_unavailable", "permission_denied"])`
   - `EmbeddingDimensionMismatchError(expected: int, actual: int, model: str)`（D-05 用）
   - `VectorStoreError(reason: str)`
5. **日志结构**：失败时走 `logger.exception(...)`，附带 `tenant_id` / `user_id` / `kb_ids`，便于 grep。

**影响面**

- 修改：`agents/middlewares/rag_middleware.py`、`rag/tools.py`、新增 `rag/errors.py`、`tests/test_rag_middleware_async.py`、`tests/test_rag_tools_async.py`。
- LangGraph runtime 已经在 async 上下文跑，所以 middleware/tool async 化不会破坏宿主调度。
- 单元测试要 `pytest-asyncio` 标注 `@pytest.mark.asyncio`。

**测试**

- `test_middleware_before_agent_is_async`
- `test_middleware_no_event_loop_creation`（assert no `asyncio.new_event_loop` calls during tests via monkeypatch counter）
- `test_tool_returns_dimension_mismatch_error_when_raised`
- `test_kb_resolution_timeout_logs_exception_not_swallowed`

---

### 4.5 D-05 — Embedding 模型与维度绑定到 KB

**现状**

[backend/packages/harness/deerflow/rag/embeddings.py](../../backend/packages/harness/deerflow/rag/embeddings.py) 中 `_resolve_dimension` 探测失败 → 默认 1536；Chroma collection 创建时按首个写入的向量定维度，**没有持久化**。换 embedding provider 时，所有老 collection 的写入立刻报"dimension mismatch"。

**目标**

- 每个 KB 在第一次写入文档时绑定 `embedding_model + embedding_dim`，作为该 KB 终身不可变属性（除非走"重建索引"路径）。
- 任何写入 / 检索路径都用 KB 自身的 embedding 配置，而非全局 `rag_config.embedding_model`。
- 维度不匹配立即 raise `EmbeddingDimensionMismatchError`，UI 给出明确错误。

**设计（探测时机：lazy / 第一次 `execute_index_job`）**

> **统一约定**：KB 创建时**只**记录 `embedding_model = rag_config.embedding_model`（从全局快照），`embedding_dim = 0`（占位），**不**做探测。真正的维度探测发生在该 KB 的第一次 `IndexingService.execute_index_job` 内（dispatcher worker 上下文）。这样 KB 创建路径完全离线、可幂等、不依赖 embedding provider 可达性。

1. **数据模型**（`KnowledgeBaseRow`）增加：
   - `embedding_model: str`（创建时写入，如 `openai:text-embedding-v4`）
   - `embedding_dim: int`（默认 0，第一次 `execute_index_job` 探测后回写）
   - 老数据迁移见 §5.2 + §5.3（**Alembic 迁移**）。
2. **创建 KB**：
   - `KnowledgeBaseService.create_knowledge_base(...)` 把当前全局 `rag_config.embedding_model` 拍照存入 KB row；`embedding_dim=0`。
   - **不**调用 embedding provider；KB 创建路径不依赖 embedding 服务可达性。
3. **第一次写入索引**（`IndexingService.execute_index_job`）：
   - 加载 KB row → 用 `kb.embedding_model` 实例化 embedding provider；
   - 用第一段 chunk 探测维度，得到 `actual_dim`；
   - 若 `kb.embedding_dim == 0`（lazy 首探）：把 `actual_dim` 写回 KB row（同事务）；
   - 若 `kb.embedding_dim > 0`（已绑定）：断言 `actual_dim == kb.embedding_dim`，否则 raise `EmbeddingDimensionMismatchError`；
   - 写入 chroma collection 时，metadata 里记一份 `{"embedding_model": ..., "embedding_dim": ...}`（冗余但便于校验/迁移）。
4. **检索**：
   - `DocumentRetriever.retrieve(query, collection)` 接收新参数 `embedding_model`（由调用方从 KB row 注入）；
   - 如果 KB row `embedding_dim == 0`（从未成功索引过），检索路径直接 raise `KbResolutionError(reason="embedding_not_bound")` 并提示"该 KB 还没有任何文档被成功索引"；
   - `multi_kb_retrieve` 对每个 KB 用各自模型生成查询向量。**这意味着多 KB 选择跨不同模型时，会发起多次 embedding 调用**——可接受，因为不同模型只能各自检索。
5. **管理工具**：新增 `POST /api/knowledge-bases/{kb_id}/reindex-all`（admin only），强制用当前全局 `embedding_model` 重新索引该 KB 的所有文档；老 chunks 在新写入完成后批量删除（详细流程见 §4.6 关于 Chroma collection 重建的说明）。

**影响面**

- 数据库迁移：`knowledge_bases` 表加两列，已有行通过启动期一次性后台任务回填（默认值取 `rag_config.embedding_model` + 探测一次维度；若探测失败则填 `unknown` / `0`，标记为 "stale"，禁止检索直到 reindex）。
- 修改：`persistence/knowledge_base/model.py`、`persistence/knowledge_base/repository.py`、`knowledge_base/service.py`、`rag/embeddings.py`、`rag/retrieval.py`、`rag/ingestion.py`。
- 配置：无变化。

**测试**

- `test_kb_creation_persists_embedding_model_and_dim`
- `test_indexing_raises_on_dim_mismatch`
- `test_retrieval_uses_kb_embedding_model_not_global`
- `test_reindex_all_updates_chunks_atomically`

---

### 4.6 D-06 — Chroma 距离公式按 metric 适配

**现状**

[rag/backends/chroma.py:91](../../backend/packages/harness/deerflow/rag/backends/chroma.py#L91) `score = 1.0 - (distance / 2.0)` 假设 cosine distance ∈ [0,2]，但 Chroma 默认 `hnsw:space=l2`，distance 是 L2 平方，可能远超 2，公式输出负值。

**目标**

- 所有 KB collection 强制使用 cosine 度量。
- 已存在的非 cosine collection 在启动期检测，标记 `stale=true` 不参与检索，由 admin 触发 `reindex-all`。

**关键约束（Chroma collection metadata 不可变）**

> Chroma 的 `collection.metadata["hnsw:space"]` 在 collection 创建后**不可修改**。要把一个 L2 collection 改为 cosine，必须：先 `client.delete_collection(name=old_name)`，再 `client.get_or_create_collection(name=new_name, metadata={"hnsw:space":"cosine"})`，然后重新写入所有 chunks。这就是 §4.5 的 `reindex-all` 路由必须存在的原因：metric 修正是一次"删旧→建新→重写"的离线迁移，而不是"改 metadata"的就地操作。

**设计**

1. **创建 collection 时**：

```python
col = client.get_or_create_collection(
    name=col_name,
    metadata={"hnsw:space": "cosine"},  # 强制
)
```

2. **检索时根据 metric 选公式**（防御性）：

```python
metric = col.metadata.get("hnsw:space", "l2")
if metric == "cosine":
    score = 1.0 - distance / 2.0
elif metric == "ip":
    score = (distance + 1.0) / 2.0
else:  # l2
    score = 1.0 / (1.0 + distance)  # bounded but not directly comparable cross-metric
```

3. **启动检查**：`KnowledgeBaseService.startup_consistency_check()`（新方法，由 `langgraph_runtime` 调用——见 §4.11 注入点）：
   - 遍历当前租户下所有 KB collection，检查 `metadata["hnsw:space"]`。
   - 非 cosine → 写入 KB row 字段 `vector_metric_stale: bool`，并 `logger.warning`。
   - 让 `multi_kb_retrieve` 跳过 stale KB，trace 中标 `skipped_reason="vector_metric_stale"`。

4. **`reindex-all` 路由的 metric-aware 流程**（admin only）：
   - Step 1: 把 KB.index_status 置为 `reindexing`，阻塞读路径。
   - Step 2: `client.delete_collection(name=old_col_name)`（**整个 collection 删除**，不是只删 chunks——因为 metadata 不可改）。
   - Step 3: `client.get_or_create_collection(name=new_col_name, metadata={"hnsw:space":"cosine"})`（实务上 `new_col_name == old_col_name`，因为 collection 已被删）。
   - Step 4: 把所有 `documents` 重新派发到 dispatcher（按 doc 粒度），dispatcher 写新 chunks 进新 collection。
   - Step 5: 全部 doc `ready` 后把 KB row 的 `vector_metric_stale=false`、`index_status` 切回正常。
   - Step 6: 失败回滚——若 Step 4 中途某 doc 失败，KB 保持 `reindexing`，由人工或重试机制处理；不会回到"看似正常但分数错"的状态。

**影响面**

- 修改：`rag/backends/chroma.py`、`knowledge_base/service.py`（新增 startup check）。
- 数据库迁移：`knowledge_bases` 表加 `vector_metric_stale: bool default false`。

**测试**

- `test_chroma_create_collection_sets_cosine_metric`
- `test_chroma_search_score_formula_per_metric`
- `test_startup_check_marks_l2_collections_stale`
- `test_stale_kb_skipped_in_multi_retrieve`

---

### 4.7 D-07 — `retrieval_top_k` 与 `max_injection_chunks` 一致化

**现状**

[config.yaml:211,215](../../config.yaml#L211-L215)

```
retrieval_top_k: 5
max_injection_chunks: 3
```

每次检索都拉 5 条但只注入 3 条，多查 2 条 = 多花 1 次向量检索 + token 估算成本。

**目标**

- 让"检索量"由"实际下游需要量"决定。
- 同时保留 reranker 启用时的"召回多于注入"原则。

**设计**

1. `multi_kb_retrieve(top_k=...)` 调用方传入 `effective_top_k = max(max_injection_chunks, rerank_topk_factor * max_injection_chunks if reranker_enabled else 0)`。
2. 配置新增 `rerank_recall_factor: int = 3`，当 `reranker_enabled=true` 时 `effective_top_k = max_injection_chunks * rerank_recall_factor`。
3. `retrieval_top_k` 字段保留为"上限保护"，参与 `min(effective_top_k, retrieval_top_k)` 截断。
4. 中间件内部消费 `max_injection_chunks` 不变；agent tool 仍用 `retrieval_top_k` 作为"显式工具调用时的召回量"——它是 LLM 主动检索，可能想看更多。

**影响面**

- 修改：`agents/middlewares/rag_middleware.py:_retrieve_from_selected_kbs`、`config/rag_config.py`、`config.yaml`。
- 不破坏外部契约。

**测试**

- `test_middleware_retrieves_exactly_max_injection_chunks_when_no_rerank`
- `test_middleware_retrieves_3x_when_rerank_enabled`
- `test_tool_retrieves_retrieval_top_k_chunks`

---

### 4.8 D-08 — 上传错误粒度细化

**现状**

[knowledge_bases.py:546](../../backend/app/gateway/routers/knowledge_bases.py#L546) `Failed to convert file to text` 不区分 pandoc 缺失 / PDF 加密 / 编码错乱 / 空文档。

**目标**

- 4 类失败给 4 种 4xx + 4 种错误码，前端按 code 文案化。

**设计**

1. `convert_file_to_markdown` 改造为返回 `Result(content: str, error: ConversionError | None)` 而非 `Path | None`。
2. 新增枚举：

```python
class ConversionErrorCode(str, Enum):
    CONVERTER_NOT_INSTALLED = "converter_not_installed"
    PDF_ENCRYPTED = "pdf_encrypted"
    DECODE_FAILED = "decode_failed"
    EMPTY_RESULT = "empty_result"
    UNKNOWN = "unknown"
```

3. 路由层映射：

| Code | HTTP | detail |
|---|---|---|
| `CONVERTER_NOT_INSTALLED` | 503 | "PDF/DOCX converter not installed on server. Install pandoc/markitdown." |
| `PDF_ENCRYPTED` | 422 | "PDF is password-protected." |
| `DECODE_FAILED` | 415 | "Could not decode file content." |
| `EMPTY_RESULT` | 422 | "Converted file produced no text content." |
| `UNKNOWN` | 500 | "Conversion failed unexpectedly." |

4. 响应 body 统一：

```json
{
  "detail": {
    "code": "pdf_encrypted",
    "message": "PDF is password-protected.",
    "hint": "Decrypt the PDF locally before uploading."
  }
}
```

**影响面**

- 修改：`utils/file_conversion.py`、`app/gateway/routers/knowledge_bases.py`、前端 [knowledge-base-uploader.tsx](../../frontend/src/components/workspace/knowledge-base-uploader.tsx)（按 code 文案化 toast）。

**测试**

- `test_convert_pdf_encrypted_returns_422`
- `test_convert_no_pandoc_returns_503`
- `test_upload_router_maps_conversion_codes`

---

### 4.9 D-09 — `KbPermissionRepository` 强制依赖

**现状**

[service.py:30](../../backend/packages/harness/deerflow/knowledge_base/service.py#L30)

```python
self._perm_repo = permission_repo or KbPermissionRepository.__new__(KbPermissionRepository)
```

`__new__` 路径产出未初始化对象，调用 `grant/revoke/list` 立即 `AttributeError`。

**目标**

- 永远不允许 None。
- 测试桩里漏传依赖时应该立刻 raise 明确错误。

**设计**

1. 删除 `or KbPermissionRepository.__new__(...)` 短路；改为：

```python
if permission_repo is None:
    raise ValueError(
        "KnowledgeBaseService requires a permission_repo. "
        "Pass KbPermissionRepository(session_factory) explicitly."
    )
self._perm_repo = permission_repo
```

2. 检查所有现存调用点（`app/gateway/deps.py:147-152`）确认都传了 `permission_repo`。
3. 测试桩用 `unittest.mock.AsyncMock(spec=KbPermissionRepository)` 替代未初始化对象。

**影响面**

- 修改：`knowledge_base/service.py`、相关测试（如 test_kb_permission_management.py 的桩）。
- 调用点（`deps.py`）已经传了 perm_repo，无需改 wiring。

**测试**

- `test_service_raises_when_perm_repo_missing`
- 既有权限管理用例继续通过。

---

### 4.10 D-10 — 前端选择器持续清理失效 KB ID

**现状**

[knowledge-base-selector.tsx:41-55](../../frontend/src/components/workspace/knowledge-base-selector.tsx#L41-L55) 用 `hasCleaned.current` 在 mount 后只清理一次。用户在 settings 页删了某 KB，`selection.selected_ids` 仍含该 ID 直到刷新。

**目标**

- 每次 `knowledgeBases` 列表变化都做一次 ID diff。

**设计**

1. 删除 `hasCleaned` ref。
2. 改为：

```tsx
useEffect(() => {
  if (isLoading || !selection?.enabled) return;
  if (knowledgeBases.length === 0) return;
  const validIds = new Set(knowledgeBases.map((kb) => kb.id));
  const filtered = selection.selected_ids.filter((id) => validIds.has(id));
  if (filtered.length !== selection.selected_ids.length) {
    onSelectionChange({
      enabled: filtered.length > 0,
      selected_ids: filtered,
    });
  }
}, [isLoading, knowledgeBases, selection, onSelectionChange]);
```

3. 防止 `onSelectionChange` 引用变化导致死循环：调用方用 `useCallback` 稳定引用（已是常见模式）。

**影响面**

- 仅修改 `knowledge-base-selector.tsx`。
- 增加单元测试：`tests/unit/components/workspace/knowledge-base-selector.test.tsx`。

**测试（Vitest）**

- `removes deleted kb ids when knowledgeBases changes`
- `does not loop when selection is already valid`

---

### 4.11 D-11 — 后台任务路径下租户上下文显式传递

**现状**

[chroma.py:43-46](../../backend/packages/harness/deerflow/rag/backends/chroma.py#L43-L46) `_collection_name` 用 `get_current_tenant_id()` 从 `ContextVar` 取，后者在非 HTTP 路径（Skill 离线索引、CLI、scheduler）默认 `"default"`，会查到 `default_kb_xxx` collection 看起来"KB 数据丢了"。

**目标**

- 后台任务（`IndexingDispatcher` worker）执行时显式 `set_current_tenant_id(job.tenant_id)`。
- 任何 KB 操作在 `tenant_id == "default"` 且未显式允许时，**raise**，而不是静默查错 collection。

**前置依赖（contextvar Token-aware 实现）**

> 当前 [app/gateway/deps.py:372](../../backend/app/gateway/deps.py#L372) 调用 `set_current_tenant_id(user.tenant_id)` 是**丢弃返回值**的写法。`with_kb_context` 要正确 reset，要求底层 `set_current_tenant_id` / `set_effective_user_id` 都返回 `Token` 对象，并提供 `reset_*` API。Sprint B.4.1 启动前必须先 grep 确认（或升级）这两个 setter 的实现，否则 reset 路径会静默失败。

**设计**

1. **JobContext 包装**（`deerflow/rag/job_context.py`）：

```python
@asynccontextmanager
async def with_kb_context(*, tenant_id: str, user_id: str):
    tenant_token = set_current_tenant_id(tenant_id)
    user_token = set_effective_user_id(user_id)
    try:
        yield
    finally:
        reset_current_tenant_id(tenant_token)
        reset_effective_user_id(user_token)
```

2. `IndexingDispatcher` worker 在执行 `IndexingService.execute_index_job` 前 `async with with_kb_context(tenant_id=job.tenant_id, user_id=job.owner_user_id):`。
3. `ChromaVectorStore._collection_name` 增加保护：

```python
def _collection_name(self, collection: str) -> str:
    tid = get_current_tenant_id()
    config = get_rag_config()
    if tid == _DEFAULT_TENANT_ID and not config.allow_no_auth_kb:
        raise VectorStoreError(
            "Tenant context is 'default' and allow_no_auth_kb is False. "
            "Use with_kb_context() in background tasks."
        )
    return f"{tid}_{collection}"
```

4. **`startup_consistency_check` 调用注入点**：在 [app/gateway/deps.py](../../backend/app/gateway/deps.py) 的 `langgraph_runtime` 中，`app.state.kb_service` 实例化（见现有 lines 140-154）之后追加：

```python
if app.state.kb_service is not None:
    try:
        await app.state.kb_service.startup_consistency_check()
    except Exception as exc:
        logger.warning("KB startup consistency check failed: %s", exc)
        # 不阻塞启动，让 KB 在自身路径上 raise 友好错误
```

`startup_consistency_check` 内部对每个租户的 KB 遍历时，必须用 `with_kb_context(tenant_id=kb.tenant_id, user_id="system")` 包裹，避免触发 `_collection_name` 的 default-tenant 守卫。

**影响面**

- 修改：`rag/backends/chroma.py`、`rag/backends/pgvector.py`（同等保护）、新增 `rag/job_context.py`、`knowledge_base/dispatcher.py`、`app/gateway/deps.py`（startup_consistency_check 调用）、`tests/test_job_context.py`。

**测试**

- `test_with_kb_context_sets_and_resets_tenant`
- `test_chroma_raises_when_tenant_default_without_allow_no_auth`
- `test_dispatcher_worker_runs_in_correct_tenant_context`
- `test_set_current_tenant_id_returns_token`（前置守卫，保证 reset 路径有效）

---

### 4.12 D-12 — `pdf_converter: auto` 透明化

**现状**

[config.yaml:103](../../config.yaml#L103) `pdf_converter: auto`。auto 找不到 pandoc/markitdown 时落到最弱实现，输出经常空白 / 乱码，但 indexing 照样切块产出"垃圾 chunk"。

**目标**

- 启动期日志告知"PDF converter 选用 X"。
- 输出长度低于阈值（200 字符）时拒绝创建文档。
- 给 admin 一个 `GET /api/system/pdf-converter` 接口看当前选用项。

**设计**

1. `utils/file_conversion.py` 添加 `resolve_pdf_converter() -> ResolvedConverter`：
   - 返回 `(name, available, version)`，启动期 `INFO` 日志一行。
   - 缓存一次结果。
2. `_convert_binary_file` 在 length < 200 时返回 `ConversionErrorCode.EMPTY_RESULT`（与 D-08 联动）。
3. 路由 `GET /api/system/pdf-converter`（admin only）返回 `{"name", "version", "available_converters": [...]}`。

**影响面**

- 修改：`utils/file_conversion.py`、`app/gateway/app.py`（启动日志）、`app/gateway/routers/system.py`（新增或既有路由）。

**测试**

- `test_resolve_pdf_converter_logs_selection`
- `test_short_output_rejected_with_empty_result`

---

## 5. 数据模型变更

### 5.1 `knowledge_base_documents` 表

| 字段 | 类型 | 说明 | 默认 |
|------|------|------|------|
| `index_status` | str | 已存在；扩展枚举 `pending/indexing/ready/failed/cancelled` | 既有 |
| `index_queued_at` | datetime nullable | 新增；`pending` 状态写入时间 | NULL |

### 5.2 `knowledge_bases` 表

| 字段 | 类型 | 说明 | 默认 |
|------|------|------|------|
| `embedding_model` | varchar(128) | 新增；KB 创建时绑定的 embedding 模型名 | `''`（启动期回填） |
| `embedding_dim` | int | 新增；首次写入探测得到的向量维度 | 0（启动期回填） |
| `vector_metric_stale` | bool | 新增；启动检查发现非 cosine 时置 true | false |

### 5.3 迁移策略（Alembic baseline migration，SQLite/PG 同源）

**关键背景**：项目当前使用 `Base.metadata.create_all`（见 [persistence/engine.py](../../backend/packages/harness/deerflow/persistence/engine.py)），它**只创建缺失的表**，**不会**给已有表加列。Sprint 中所有需要新增列的 Story（A.10 / B.1.2 / B.3.1）必须先有 Alembic 迁移，否则 SQLite 上 `create_all` 不报错也不加列，运行时第一次 `SELECT new_column` 才会炸。

1. **接入 Alembic（一次性）**：
   - 新增 `backend/alembic/` 目录 + `alembic.ini` + `env.py`，对接现有 `Base.metadata`。
   - 启动期 `init_engine_from_config()` 之后调用 `alembic upgrade head`（如使用 SQLite 内存模式则跳过）。
   - 现有 `Base.metadata.create_all` 调用保留作为"全新空库"的快路径，但 Alembic head 是 source of truth。

2. **Baseline 迁移 `00XX_kb_baseline_for_usability_sprint.py`**（一次性涵盖三处加列）：

   ```python
   # downgrade 用 op.drop_column；不再赘述
   def upgrade():
       # B.1.2 — 文档表索引状态扩展
       op.add_column("knowledge_base_documents",
                     sa.Column("index_queued_at", sa.DateTime(timezone=True), nullable=True))
       # 注：index_status 字段已存在；新枚举值 pending / cancelled 由应用层校验
       # （SQLite 没有真正的 ENUM，PG 上若使用 ENUM 类型则需 ALTER TYPE ADD VALUE）

       # A.10 — KB 表向量度量状态
       op.add_column("knowledge_bases",
                     sa.Column("vector_metric_stale", sa.Boolean(), nullable=False, server_default=sa.false()))

       # B.3.1 — KB 表 embedding 绑定
       op.add_column("knowledge_bases",
                     sa.Column("embedding_model", sa.String(128), nullable=False, server_default=""))
       op.add_column("knowledge_bases",
                     sa.Column("embedding_dim", sa.Integer(), nullable=False, server_default="0"))
   ```

3. **PostgreSQL `index_status` ENUM 扩展**：现有列若是 `sa.Enum` 类型，PG 上要 `ALTER TYPE knowledge_base_index_status ADD VALUE 'pending'` / `'cancelled'`。该操作在 PG 14+ 不能在 transaction 中跑，迁移文件需 `op.execute("COMMIT")` 配合或使用 `with op.get_context().autocommit_block()`。

4. **启动期回填**（一次性后台任务，幂等，**派发到 dispatcher 而非 lifespan 同步阻塞**）：
   - 扫描 `embedding_dim == 0` 的 KB → 不直接调用 embedding，仅记 INFO 日志"等待第一次 execute_index_job 时 lazy 探测"（与 §4.5 设计一致）。
   - 扫描 `vector_metric_stale == true` 的 KB → 在 KB 详情页显示 stale 徽标，admin 可触发 `reindex-all`。
   - 启动期回填**不**阻塞 Gateway 启动；`startup_consistency_check` 只做 metric 检测和 stale 标记，不做 embedding 调用。

---

## 6. 配置变更

### 6.1 `config.yaml` 新增字段（均带默认值）

```yaml
rag:
  # 既有字段不变
  cross_kb_score_strategy: absolute        # absolute | normalized | rrf
  rerank_recall_factor: 3                  # 仅在 reranker_enabled=true 时生效
  indexing_workers: 2                      # 后台索引并发度
  indexing_queue_size: 1024                # 队列缓冲
  # allow_no_auth_kb 默认仍为 false，但启动期会打印一行 INFO 提示
```

### 6.2 兼容性

- 所有新字段都有保守默认值，旧 `config.yaml` 启动后行为等价于"开了 absolute 排序 + 异步索引"，**没有需要用户主动改动的字段**。

---

## 7. 实施分阶段（Sprint Plan）

> 详细 Story 拆分、依赖关系、实施顺序与状态跟踪见 [2026-05-19-knowledge-base-usability-improvement-sprint-plan.md](./2026-05-19-knowledge-base-usability-improvement-sprint-plan.md)。下文仅给出阶段轮廓与容量上限。

### Sprint A（Week 1-2，MVP 解阻断 + Alembic baseline）

| # | Story | SP | 文件 |
|---|-------|----|------|
| A.0 | **Alembic 接入 + baseline 迁移**（5 列：`index_queued_at` / `vector_metric_stale` / `embedding_model` / `embedding_dim`，PG `index_status` ENUM 扩展） | 1 | `backend/alembic/`(新)、`persistence/engine.py` |
| A.1 | D-01 RagDecisionEvent + 启动日志 | 3 | `rag/decisions.py`、`rag_middleware.py`、`rag/tools.py`、`app.py` |
| A.2 | D-03 cross_kb_score_strategy=absolute 默认 | 3 | `knowledge_base/retrieval.py`、`config/rag_config.py` |
| A.3 | D-06 Chroma cosine 强制 + metric-aware score + startup check（依赖 A.0） | 3 | `rag/backends/chroma.py`、`knowledge_base/service.py`、`persistence/.../model.py`、`app/gateway/deps.py` |
| A.4 | D-07 召回量 = injection_chunks ×（1 或 rerank_recall_factor） | 1 | `rag_middleware.py`、`rag_config.py` |
| A.5 | D-09 强制 perm_repo 非 None | 1 | `service.py`、修复测试桩 |
| A.6 | 单元 + 集成测试覆盖以上 5 项 | 3 | `tests/test_*` |

容量 ≈ 15 SP（2 周内可完成，含缓冲）。

### Sprint B（Week 3-4，核心异步化 + KB-bound embedding）

| # | Story | SP |
|---|-------|----|
| B.1 | D-02 IndexingDispatcher（队列 + 工作池 + recover + service 6 个调用点切换 + sync fallback） | 11 |
| B.2 | D-04 RagMiddleware / search_knowledge_base 异步原生化（含 LangChain async hook compat smoke） | 5.5 |
| B.3 | D-05 KB-bound embedding_model + dim（lazy 探测）+ reindex-all 路由 | 5 |
| B.4 | D-11 with_kb_context + dispatcher 内部使用 + chroma raise 保护（含 setter Token-aware 前置） | 3.5 |
| B.5 | 端到端测试 + 性能 smoke（20 MB PDF P95 ≤ 3 s） + sync fallback 测试 | 3 |

容量 ≈ 28 SP（按双周 sprint 推进，含 LangChain 兼容 / setter Token 前置 / 6 调用点扩展 / sync fallback）。

### Sprint C（Week 5-6，体验收尾）

| # | Story | SP |
|---|-------|----|
| C.1 | D-08 ConversionErrorCode + 路由映射 + 前端文案 | 3 |
| C.2 | D-10 前端 selector 持续清理 + 单测（useCallback + 渲染计数 ≤ 3） | 1 |
| C.3 | D-12 pdf_converter 透明化 + admin 路由 | 2 |
| C.4 | 文档更新（README / CLAUDE.md / docs/RAG.md） | 2 |

容量 ≈ 8 SP（1 周完成）。

**总容量** ≈ 51 SP（A=15 / B=28 / C=8）。

---

## 8. 测试策略

### 8.1 既有 140 用例

- 不允许修改现有断言来"绕开"诊断结论。
- 必须全部继续通过。CI 中以 `pytest tests/test_kb_*.py tests/test_knowledge_base_*.py` 作为门槛。

### 8.2 新增测试模块

| 文件 | 覆盖 |
|------|------|
| `tests/test_rag_decisions.py` | D-01 |
| `tests/test_indexing_dispatcher.py` | D-02 |
| `tests/test_multi_kb_score_strategies.py` | D-03 |
| `tests/test_rag_middleware_async.py` | D-04 |
| `tests/test_rag_tools_async.py` | D-04 |
| `tests/test_kb_embedding_binding.py` | D-05 |
| `tests/test_chroma_metric_aware.py` | D-06 |
| `tests/test_recall_factor.py` | D-07 |
| `tests/test_conversion_error_codes.py` | D-08 |
| `tests/test_kb_service_dependency_guard.py` | D-09 |
| `frontend/tests/unit/components/workspace/knowledge-base-selector.test.tsx` | D-10 |
| `tests/test_job_context.py` | D-11 |
| `tests/test_pdf_converter_resolution.py` | D-12 |

### 8.3 性能 smoke

- `tests/perf/test_upload_async.py`：mock embedding 100 ms/调用，断言上传响应时间 < 3 s（20 MB DOCX，估计 200 chunk）。
- `tests/perf/test_multi_kb_retrieval_latency.py`：5 个 KB × 100 文档，断言 P95 < `per_kb_timeout_ms × 1.2`。

### 8.4 回归

- `tests/test_harness_boundary.py`：保证新文件（`dispatcher.py`、`job_context.py`、`decisions.py`）位于 `packages/harness/deerflow/`，不引入 `app.*` 依赖。
- 对外契约：`KnowledgeBaseResponse` / `DocumentDetailResponse` 结构不变，前端 contract test 不破坏。

---

## 9. 风险与回滚

### 9.1 风险

| 风险 | 严重度 | 缓解 |
|------|--------|------|
| dispatcher 单进程瓶颈：高并发上传时队列堆积 | 中 | `indexing_queue_size` 可调；满队列时 503 + 文档保持 `pending` 状态可重试 |
| `cross_kb_score_strategy=absolute` 导致用户感知"召回变少" | 低 | 配置开关回退 `normalized`；trace 字段记录策略名便于支持 |
| Embedding 维度回填失败时 KB 长期 stale | 中 | 启动期 warning + admin `reindex-all` 工具；UI 在 KB 详情页显示 `stale` 徽标 |
| 异步 middleware 与现有 sync agent runtime 不兼容 | 低 | LangChain Agent Middleware 已支持 async hooks；本期前在 dev 分支跑 1 周 e2e |
| Chroma collection metric 强制 cosine 后，旧 l2 collection 全部 stale | 中 | 启动检查只标记不删除；admin 触发 `reindex-all` 重建后自动转 cosine |

### 9.2 回滚路径

- **A.x 系列**：所有改动都通过配置项控制（`cross_kb_score_strategy`、新决策日志），出问题改 `config.yaml` 切回旧行为，无需回滚代码。
- **A.0 Alembic baseline**：保留 `downgrade()` 回滚函数；如启动后 Alembic 出问题，回滚迁移版本即可（数据列保留，应用层不读）。
- **B.x dispatcher**：通过 `rag.indexing_workers=0` 退化为同步路径——`KnowledgeBaseService.create_document_with_access_check` / `update_document_with_access_check` / `reindex_document_with_access_check` / `create_document` / `update_document` / `reindex_document` 6 处统一保留分支：`if config.rag.indexing_workers == 0: await self._indexing.execute_index_job(...) else: await dispatcher.submit(...)`。该分支由 Sprint B.5.1 的 `test_dispatcher_disabled_falls_back_to_sync` 测试覆盖，标 `# TODO: remove after Sprint B+1`。
- **embedding_model 绑定**：迁移失败的 KB 走 `embedding_model=''` fallback 到全局配置（兼容旧路径），同时 `logger.warning`。`embedding_dim=0` 的 KB 在第一次成功写入时由 lazy 探测路径自动回填。

---

## 10. 文档更新清单

| 文档 | 改动 |
|------|------|
| [backend/CLAUDE.md](../../backend/CLAUDE.md) | RAG 章节加 IndexingDispatcher、async middleware、KB-bound embedding 描述 |
| [README.md](../../README.md) | 用户可见配置项 `rag.cross_kb_score_strategy` / `rag.indexing_workers` 列入 |
| `docs/RAG.md`（如不存在则新建） | 记录三种 cross_kb_score_strategy 的取舍、reindex-all 操作流 |
| [frontend/CLAUDE.md](../../frontend/CLAUDE.md) | 上传错误码 → 文案映射表 |

---

## 11. DoD（Definition of Done）

- [ ] 12 条诊断结论全部映射到具体 Story 并完成
- [ ] **Alembic baseline 迁移已合入并验证可在 SQLite/PG 上 `upgrade head` 幂等**
- [ ] 既有 140 个 KB 测试全部通过，新增测试 ≥ 25 个
- [ ] `pytest tests/test_harness_boundary.py` 通过——所有新增 harness 文件（`dispatcher.py`、`decisions.py`、`errors.py`、`job_context.py`）不引入 `app.*` 依赖
- [ ] `make test` 全绿
- [ ] 上传 20 MB PDF P95 ≤ 3 s，索引 5 min 内 ready（mock embedding 时 < 30 s）
- [ ] 多 KB 检索的 trace 字段含 `strategy` / `per_kb_raw_max` / `skipped_reason`
- [ ] `rag.allow_no_auth_kb=false` 模式下，未登录 agent 调用得到结构化 `decision.reason="no_auth"` JSON 而非空结果
- [ ] `KnowledgeBaseRow` 含 `embedding_model + embedding_dim`，新建 KB 写入 `embedding_model`（`embedding_dim` lazy 探测）
- [ ] Chroma collection metadata 有 `hnsw:space=cosine`；老 L2 collection 通过 `reindex-all` 走 `delete_collection + recreate` 流程升级
- [ ] `set_current_tenant_id` / `set_effective_user_id` 已确认是 Token-aware（B.4.1 前置守卫测试通过）
- [ ] `rag.indexing_workers=0` 时回退到同步索引路径（B.5.1 fallback 测试通过）
- [ ] 前端选择器在 KB 列表变化时自动清理失效 ID（Vitest 断言 + useCallback 渲染计数 ≤ 3）
- [ ] [backend/CLAUDE.md](../../backend/CLAUDE.md) / [README.md](../../README.md) 已更新

---

## 12. 附录

### 12.1 相关文件路径速查

| 模块 | 路径 |
|------|------|
| 配置 | [backend/packages/harness/deerflow/config/rag_config.py](../../backend/packages/harness/deerflow/config/rag_config.py) |
| 服务 | [backend/packages/harness/deerflow/knowledge_base/service.py](../../backend/packages/harness/deerflow/knowledge_base/service.py) |
| 索引 | [backend/packages/harness/deerflow/knowledge_base/indexing.py](../../backend/packages/harness/deerflow/knowledge_base/indexing.py) |
| 检索 | [backend/packages/harness/deerflow/knowledge_base/retrieval.py](../../backend/packages/harness/deerflow/knowledge_base/retrieval.py) |
| 中间件 | [backend/packages/harness/deerflow/agents/middlewares/rag_middleware.py](../../backend/packages/harness/deerflow/agents/middlewares/rag_middleware.py) |
| Agent 工具 | [backend/packages/harness/deerflow/rag/tools.py](../../backend/packages/harness/deerflow/rag/tools.py) |
| Chroma | [backend/packages/harness/deerflow/rag/backends/chroma.py](../../backend/packages/harness/deerflow/rag/backends/chroma.py) |
| Embedding | [backend/packages/harness/deerflow/rag/embeddings.py](../../backend/packages/harness/deerflow/rag/embeddings.py) |
| Gateway 路由 | [backend/app/gateway/routers/knowledge_bases.py](../../backend/app/gateway/routers/knowledge_bases.py) |
| 前端选择器 | [frontend/src/components/workspace/knowledge-base-selector.tsx](../../frontend/src/components/workspace/knowledge-base-selector.tsx) |
| 前端 API | [frontend/src/core/knowledge-base/api.ts](../../frontend/src/core/knowledge-base/api.ts) |

### 12.2 决策事件 JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "RagDecisionEvent",
  "type": "object",
  "required": ["outcome", "reason"],
  "properties": {
    "outcome": {"type": "string", "enum": ["injected", "blocked", "skipped"]},
    "reason": {
      "type": "string",
      "enum": [
        "ok",
        "no_auth",
        "rag_disabled",
        "injection_disabled",
        "empty_query",
        "db_unavailable",
        "no_results",
        "timeout",
        "vector_metric_stale",
        "embedding_dim_mismatch"
      ]
    },
    "hint": {"type": "string"},
    "tenant_id": {"type": "string"},
    "user_id": {"type": "string"},
    "kb_ids": {"type": "array", "items": {"type": "string"}}
  }
}
```

### 12.3 Story → 文件改动矩阵（速查）

| Story | 主要文件 | 测试 |
|-------|----------|------|
| A.0 / Alembic baseline | `backend/alembic/`(新)、`persistence/engine.py` | `tests/test_alembic_baseline_migration.py` |
| A.1 / D-01 | `rag/decisions.py`(新)、`rag_middleware.py`、`rag/tools.py`、`app/gateway/app.py` | `test_rag_decisions.py` |
| A.2 / D-03 | `knowledge_base/retrieval.py`、`config/rag_config.py` | `test_multi_kb_score_strategies.py` |
| A.3 / D-06 | `rag/backends/chroma.py`、`knowledge_base/service.py`、`persistence/knowledge_base/model.py`、`app/gateway/deps.py`(注入 startup_consistency_check) | `test_chroma_metric_aware.py` |
| A.4 / D-07 | `agents/middlewares/rag_middleware.py`、`config/rag_config.py` | `test_recall_factor.py` |
| A.5 / D-09 | `knowledge_base/service.py`、`tests/test_kb_permission_management.py`(桩) | `test_kb_service_dependency_guard.py` |
| B.1 / D-02 | `knowledge_base/dispatcher.py`(新)、`app/gateway/deps.py`、`knowledge_base/service.py`(6 个 `execute_index_job` 调用点 + sync fallback) | `test_indexing_dispatcher.py`、`test_dispatcher_disabled_falls_back_to_sync.py` |
| B.2 / D-04 | `agents/middlewares/rag_middleware.py`、`rag/tools.py`、`rag/errors.py`(新) | `test_rag_*_async.py`、`test_langchain_async_middleware_compat.py` |
| B.3 / D-05 | `persistence/knowledge_base/model.py`、`knowledge_base/service.py`、`rag/embeddings.py`、`rag/retrieval.py` | `test_kb_embedding_binding.py` |
| B.4 / D-11 | `rag/job_context.py`(新)、`rag/backends/chroma.py`、`rag/backends/pgvector.py`、`config/tenant.py`(setter Token-aware 前置) | `test_job_context.py`、`test_set_current_tenant_id_returns_token.py` |
| C.1 / D-08 | `utils/file_conversion.py`、`app/gateway/routers/knowledge_bases.py` | `test_conversion_error_codes.py` |
| C.2 / D-10 | `frontend/.../knowledge-base-selector.tsx` | `knowledge-base-selector.test.tsx`（含 useCallback 渲染计数 ≤ 3 断言）|
| C.3 / D-12 | `utils/file_conversion.py`、`app/gateway/routers/system.py` | `test_pdf_converter_resolution.py` |

---

> **下一步**：本设计落地后由 Sprint Owner 把 §7 的三个 Sprint 拆成实际工单（建议在 [docs/plans/2026-05-19-knowledge-base-usability-improvement-sprint-plan.md](#) 中维护实施进度）。
