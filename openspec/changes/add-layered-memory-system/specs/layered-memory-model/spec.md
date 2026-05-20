## ADDED Requirements

### Requirement: Three-layer memory scope model

The memory subsystem SHALL define exactly three layers — `session`, `user`, `domain` — each with a deterministic scope tuple, lifecycle, and primary writer. No record SHALL exist outside these three layers.

| Layer | Scope tuple | Lifecycle | Primary writer |
|---|---|---|---|
| `session` | `(tenant_id, user_id, thread_id)` (+ optional `agent_name`) | Bound to thread; archived when thread is deleted | `MemoryMiddleware` automatic + `SummarizationMiddleware` hook |
| `user`    | `(tenant_id, user_id)` (+ optional `agent_name`) | Long-lived, decay-eligible | `MemoryMiddleware` automatic (confidence ≥ 0.7) + REST manual CRUD |
| `domain`  | `(tenant_id, domain, entity_id?)`                | Long-lived, decay-eligible, tenant-shareable | Explicit `record_domain_memory` tool (confidence ≥ 0.8) + tenant-admin REST |

`tenant_id` MUST always be present. `user_id` is required for `session` and `user` layers. `thread_id` is required for `session`. `domain` is required for the `domain` layer; `entity_id` is OPTIONAL on the `domain` layer (null entity_id represents tenant-wide common knowledge).

Layer assignment SHALL be derived from scope at write-time and SHALL NOT mutate after creation; promoting a record between layers (e.g. session → user) MUST create a new record and optionally retain a back-reference in `metadata.promoted_from`.

#### Scenario: Session record bound to thread scope

- **WHEN** a user message in thread `thr_abc` says "本会话用 PDF 不要 Markdown" and `MemoryMiddleware` extracts a preference
- **THEN** the resulting record SHALL be written with `scope.layer="session"`, `scope.tenant_id=<current>`, `scope.user_id=<current>`, `scope.thread_id="thr_abc"`, and SHALL NOT appear in any other thread's prompt composition

#### Scenario: User record outlives thread

- **WHEN** the LLM extracts a preference "用户偏好简短回答" with `confidence=0.85` from thread `thr_abc`
- **THEN** the record SHALL be written with `scope.layer="user"`, no `thread_id`, and SHALL be retrievable from any new thread for the same `(tenant_id, user_id)`

#### Scenario: Domain record shared across users in tenant

- **WHEN** a tenant admin or an authorized SOUL writes "设备 pump-123 第 4 次轴温异常根因 = 联轴器对中偏差" via the explicit tool path
- **THEN** the record SHALL be written with `scope.layer="domain"`, `scope.domain="equipment"`, `scope.entity_id="pump-123"`, and SHALL be retrievable by any user within the same `tenant_id` who queries equipment `pump-123`

#### Scenario: Tenant_id missing rejects write

- **WHEN** any caller attempts to write a record with `scope.tenant_id` empty or null
- **THEN** the write SHALL fail with `MemoryScopeForbidden` and no record SHALL be persisted

### Requirement: Unified MemoryRecord schema

Every memory record across all three layers SHALL conform to a single `MemoryRecord` Pydantic schema with the following required fields: `id` (string, opaque), `scope` (MemoryScope), `kind` (one of `preference | fact | episode | domain_assertion | context_summary`), `content` (string, non-empty), `source` (one of `middleware_auto | tool_explicit | user_manual | import`), `confidence` (float 0..1), `created_at` (UTC ISO-8601).

OPTIONAL fields: `embedding` (list[float], present only on Domain layer or when service auto-vectorizes), `valid_from`/`valid_to` (UTC datetimes), `decay_policy` (string `never` or `linear:days=N` or `exponential:half_life_days=N`), `tags` (list[string]), `metadata` (dict).

`kind` value MUST be consistent with layer: `context_summary` valid in all layers; `domain_assertion` valid ONLY in `domain` layer; `preference`/`fact`/`episode` valid in all layers.

#### Scenario: Schema rejects empty content

- **WHEN** any caller submits a record with `content=""` or whitespace-only
- **THEN** validation SHALL fail before storage I/O

#### Scenario: domain_assertion in user layer rejected

- **WHEN** a write specifies `kind="domain_assertion"` with `scope.layer="user"`
- **THEN** the write SHALL be rejected with a schema validation error

#### Scenario: Confidence outside 0..1 rejected

- **WHEN** a record is submitted with `confidence=1.5` or `confidence=-0.1`
- **THEN** validation SHALL fail and no record SHALL be persisted

### Requirement: Decay policy and validity windows

Records MAY carry a `decay_policy` of `never` (default), `linear:days=N`, or `exponential:half_life_days=N`. Records MAY also carry `valid_from` / `valid_to` timestamps. The retrieval algorithm SHALL apply both:

- A record with `valid_to < now` SHALL NOT appear in retrieval results (but MUST still be persisted for audit).
- A record with `valid_from > now` SHALL NOT appear in retrieval results.
- For records eligible for retrieval, `effective_score = base_score × decay_factor(now − created_at, decay_policy)` where `decay_factor("never", _) = 1.0`, `decay_factor("linear:days=N", t) = max(0, 1 − t/N_days)`, `decay_factor("exponential:half_life_days=N", t) = 0.5^(t/N_days)`.

#### Scenario: Expired record excluded from retrieval

- **WHEN** a record has `valid_to = 2025-01-01` and the current time is `2026-05-20`
- **THEN** retrieval SHALL exclude the record from results regardless of layer or score

#### Scenario: Exponential decay reduces score over time

- **WHEN** two user-layer records have identical content score but A has `created_at = now − 30 days` and B has `created_at = now − 5 days`, both with `decay_policy = "exponential:half_life_days=14"`
- **THEN** B's `effective_score` SHALL be strictly greater than A's

#### Scenario: Default policy never decays

- **WHEN** a record has no `decay_policy` field set (default `never`)
- **THEN** its `effective_score` SHALL equal its `base_score` regardless of age

### Requirement: Idempotent writes via content fingerprint

The memory subsystem SHALL deduplicate writes within a scope by computing a content fingerprint of `(scope, kind, normalized_content)` where `normalized_content` strips leading/trailing whitespace and collapses internal whitespace runs to a single space. A subsequent write with the same fingerprint SHALL update the existing record's `created_at` (touch) and `confidence` (max of old and new) instead of creating a duplicate.

#### Scenario: Whitespace-different duplicates merged

- **WHEN** the LLM extracts the fact "用户 偏好  简短回答" while a record with content "用户偏好简短回答" already exists in the same `(scope, kind)`
- **THEN** no new record SHALL be created; the existing record's `created_at` SHALL be touched

#### Scenario: Higher confidence wins on touch

- **WHEN** an existing record has `confidence=0.7` and a duplicate write supplies `confidence=0.9`
- **THEN** the stored `confidence` after the write SHALL be `0.9`

### Requirement: Backward-compatible legacy fact migration

Existing data in the legacy `memory.json` file SHALL be migrable to the new schema without loss. Migration SHALL produce User-layer `MemoryRecord` instances using the following mapping:

- `user.workContext.summary` → `kind="context_summary"`, `tags=["work_context"]`, `source="import"`
- `user.personalContext.summary` → `kind="context_summary"`, `tags=["personal_context"]`, `source="import"`
- `user.topOfMind.summary` → `kind="context_summary"`, `tags=["top_of_mind"]`, `source="import"`
- `history.{recentMonths,earlierContext,longTermBackground}.summary` → `kind="context_summary"`, `tags=["history", <key>]`, `source="import"`
- Each entry in `facts[]` → `kind=` mapped from `category` (`preference|knowledge|context|behavior|goal` → `preference|fact|fact|preference|fact`), preserving `id`, `content`, `confidence`, `createdAt` → `created_at`, `source` → `metadata.legacy_source`

Migration SHALL be idempotent: re-running the migration on already-migrated data MUST be a no-op.

#### Scenario: Pre-migration memory.json fully imported

- **WHEN** a legacy `memory.json` contains 3 `user.*.summary` entries, 3 `history.*.summary` entries, and 12 `facts[]` entries
- **THEN** running the migration SHALL produce exactly 18 user-layer records and SHALL leave the original file in place

#### Scenario: Migration is idempotent

- **WHEN** the migration script runs twice on the same user
- **THEN** the second run SHALL detect the sentinel marker and SHALL produce zero new records
