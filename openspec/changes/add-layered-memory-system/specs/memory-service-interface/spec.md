## ADDED Requirements

### Requirement: MemoryService is the sole public API

All callers — `MemoryMiddleware`, builtin tools, gateway routers, embedded `DeerFlowClient`, channel workers, migration scripts — SHALL access memory exclusively through the `MemoryService` interface defined in `deerflow.agents.memory.service`. Direct invocation of `MemoryStorage`, `BaseStore`, ChromaDB, or filesystem from outside the service module is FORBIDDEN.

The interface SHALL expose at minimum these four methods:

- `read(scope, *, query=None, top_k=10, kinds=None, at_time=None) -> list[MemoryRecord]`
- `write(record: MemoryRecord) -> str` (returns id)
- `forget(scope, *, record_id=None, filter=None) -> int` (returns deleted count)
- `compose_for_prompt(*, tenant_id, user_id, thread_id, agent_name, query_hint, budget_tokens) -> str`

Extension methods (`promote_record`, `bulk_import`, etc.) MAY be added as long as they preserve the four core contracts above.

#### Scenario: Middleware does not import storage directly

- **WHEN** static analysis scans `MemoryMiddleware.py` and any tool implementation under `tools/builtins/`
- **THEN** no module under `deerflow.agents.memory.storage` SHALL be imported outside `deerflow.agents.memory.service` and `tests/`

#### Scenario: Gateway router uses service only

- **WHEN** the gateway memory router handles any request
- **THEN** it SHALL delegate to `MemoryService` methods and SHALL NOT call `FileMemoryStorage` / `StoreMemoryStorage` / `BaseStore` directly

### Requirement: Service composes storage backends per layer

`MemoryService` SHALL internally route to layer-specific storage implementations:

- `session` layer → LangGraph `BaseStore` under namespace `("memory_session", tenant_id, user_id, thread_id)`
- `user` layer → existing `FileMemoryStorage` / `StoreMemoryStorage` under namespace `("memory", tenant_id, user_id, agent_name | "default")` (UNCHANGED from current implementation to preserve compatibility)
- `domain` layer → `BaseStore` under namespace `("memory_domain", tenant_id, domain, entity_id | "_")` for structured fields, plus a tenant-scoped ChromaDB collection named `memory_domain_<tenant_id>` for embeddings

The service SHALL NOT change the user-layer namespace tuple or the on-disk JSON shape that existing tests in `backend/tests/test_memory_*.py` and frontend code depend on.

#### Scenario: User-layer namespace preserved

- **WHEN** `MemoryService.write` is called with `scope.layer="user"`, `tenant_id="t1"`, `user_id="u1"`, `agent_name="default"`
- **THEN** the underlying `BaseStore.aput` SHALL be invoked with namespace `("memory", "t1", "u1", "default")` exactly as the current `StoreMemoryStorage` does

#### Scenario: Domain ChromaDB collection scoped per tenant

- **WHEN** `MemoryService.write` is called with `scope.layer="domain"`, `tenant_id="t1"`
- **THEN** the embedding write SHALL target ChromaDB collection `memory_domain_t1` and SHALL NOT touch any `kb_*` collection used by knowledge bases

### Requirement: Tenant context propagation across async boundaries

`MemoryService` operations invoked from background workers (debounce queue, migration script, sweeper) SHALL restore the originating caller's tenant + user context using the existing `with_kb_context(tenant_id=..., user_id=...)` helper from `deerflow.rag.job_context`. ContextVar leakage across async tasks SHALL NOT silently fall back to the global `default` tenant.

#### Scenario: Debounced write preserves tenant

- **WHEN** a user message arrives under `tenant_id="t1"`, `MemoryMiddleware` enqueues, the 30-second timer fires on a different thread, and the LLM extractor calls `MemoryService.write`
- **THEN** the write SHALL be persisted under `tenant_id="t1"` and not under `"default"`

#### Scenario: Default tenant write rejected when guarded

- **WHEN** `MemoryService.write` is invoked with `scope.tenant_id="default"` and config flag `rag.allow_no_auth_kb=False`
- **THEN** the write SHALL fail with `MemoryScopeForbidden` rather than silently land in a global namespace

### Requirement: Stable error model

`MemoryService` methods SHALL surface a closed set of typed exceptions: `MemoryNotFound` (404-equivalent), `MemoryScopeForbidden` (403-equivalent), `MemoryStorageError` (500-equivalent for backend I/O failures), `MemoryEmbeddingUnavailable` (Domain-only, non-fatal — caller MAY retry without embedding). Generic `Exception` SHALL NOT be raised from public methods. Gateway routers SHALL map these to HTTP 404 / 403 / 500 / 503 respectively.

#### Scenario: Reading missing record raises typed exception

- **WHEN** `MemoryService.read(...)` followed by a record-id lookup finds nothing
- **THEN** the get-by-id path SHALL raise `MemoryNotFound` and NOT a generic `KeyError`

#### Scenario: Embedding service down does not crash write

- **WHEN** the ChromaDB instance is unreachable and a Domain-layer write is attempted
- **THEN** the structured write to `BaseStore` SHALL succeed, the embedding step SHALL emit `MemoryEmbeddingUnavailable` (logged + telemetry), and the record SHALL be persisted with `embedding=None` for later backfill
