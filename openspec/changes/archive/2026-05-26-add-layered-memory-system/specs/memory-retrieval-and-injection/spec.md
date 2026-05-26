## ADDED Requirements

### Requirement: Per-layer retrieval algorithm

`MemoryService.read` SHALL apply a layer-specific retrieval algorithm:

- **Session layer**: full-text substring/keyword match on `content` plus reverse chronological ordering. NO embedding. Top-k limited to ≤ 50 by default.
- **User layer**: full-text match plus `effective_score = base_text_match × decay_factor × confidence`. Embedding MAY be used when the layer's record count exceeds an internal threshold (default 200) but is OPTIONAL.
- **Domain layer**: embedding similarity (cosine) is the primary score. Metadata pre-filter on `tenant_id`, `domain`, and `entity_id` (when supplied) SHALL be applied BEFORE the vector search to bound the search space.

When `query` is null, retrieval SHALL fall back to recency-only ordering for Session/User and SHALL return an empty list for Domain (Domain without query is meaningless).

#### Scenario: Session retrieval ignores embedding

- **WHEN** `read` is called with `scope.layer="session"` and a `query`
- **THEN** the implementation SHALL NOT call any embedding provider and SHALL match on substring tokens of `content`

#### Scenario: Domain retrieval pre-filters by entity_id

- **WHEN** `read` is called with `scope.layer="domain"`, `scope.domain="equipment"`, `scope.entity_id="pump-123"`, `query="轴温异常"`, `top_k=5`
- **THEN** the ChromaDB query SHALL include a `where` clause `{"entity_id": "pump-123", "domain": "equipment"}` and SHALL return at most 5 records, all with `scope.entity_id="pump-123"`

#### Scenario: Domain without query returns empty

- **WHEN** `read` is called with `scope.layer="domain"` and `query=None`
- **THEN** the result SHALL be an empty list

### Requirement: Prompt composition with priority budget packing

`MemoryService.compose_for_prompt(*, tenant_id, user_id, thread_id, agent_name, query_hint, budget_tokens)` SHALL:

1. Read top candidates from each layer using the retrieval algorithms above with `query=query_hint` for User and Domain.
2. Greedily pack records into the available token budget in priority order **Session > User > Domain**. Within a layer, ordering follows that layer's retrieval score.
3. Render the output as a single `<memory>` block containing layer sub-blocks: `<memory><session>...</session><user>...</user><domain>...</domain></memory>`. Empty sub-blocks MAY be omitted.
4. If a record cannot fit in the remaining budget it SHALL be skipped (truncation MUST occur on whole records, never mid-record).
5. Emit a `memory_compose_outcome` telemetry event regardless of whether truncation occurred.

#### Scenario: Session always preferred over Domain

- **WHEN** `budget_tokens=400` and `compose_for_prompt` finds 1 Session record (300 tokens), 5 User records (60 tokens each = 300), and 3 Domain records (200 tokens each = 600)
- **THEN** the output SHALL contain the 1 Session record (300 used) plus as many User records as fit (1 record × 60 tokens = 360 cumulative ≤ 400 budget) and 0 Domain records, even though Domain candidates exist

#### Scenario: Empty layers omitted from output

- **WHEN** the User layer returns no records
- **THEN** the output SHALL NOT include an empty `<user></user>` sub-block

#### Scenario: Output never splits a record mid-way

- **WHEN** the next candidate record requires 200 tokens but only 150 tokens remain in budget
- **THEN** that record SHALL be skipped entirely; partial-record output is forbidden

#### Scenario: Compose emits telemetry on every call

- **WHEN** `compose_for_prompt` is invoked by `MemoryMiddleware`
- **THEN** exactly one `memory_compose_outcome` event SHALL be recorded with fields `budget_tokens`, `used_tokens`, `session_n`, `user_n`, `domain_n`, `truncated` (bool)

### Requirement: Telemetry event taxonomy

The memory subsystem SHALL emit the following telemetry events using the in-memory counter + JSONL sink pattern already used by `report_templates.telemetry`:

| Event | Trigger | Required fields |
|---|---|---|
| `memory_write` | Successful `write` | `layer`, `kind`, `source`, `confidence`, `byte_size` |
| `memory_read` | Each `read` call | `layer`, `top_k`, `returned_n`, `has_embedding_query` (bool) |
| `memory_compose_outcome` | Each `compose_for_prompt` | `budget_tokens`, `used_tokens`, `session_n`, `user_n`, `domain_n`, `truncated` |
| `memory_forget` | Each `forget` | `layer`, `deleted_n`, `by` (`record_id` \| `filter`) |
| `memory_migration` | Each migration run | `direction` (`forward`\|`rollback`), `users_n`, `records_n` |
| `memory_embedding_unavailable` | Domain write/read where embedding fails | `layer`, `operation` (`write`\|`read`) |

Event emission SHALL also append a JSON line to `{DEER_FLOW_HOME}/memory/.telemetry.log` unless the env var `DEER_FLOW_MEMORY_TELEMETRY_LOG=0` is set.

A read-only HTTP endpoint `GET /api/telemetry/memory/summary` SHALL return the in-memory counter snapshot.

#### Scenario: Compose outcome event recorded on truncation

- **WHEN** `compose_for_prompt` truncates because budget is exhausted
- **THEN** the recorded `memory_compose_outcome` event SHALL have `truncated=true`

#### Scenario: Telemetry log opt-out respected

- **WHEN** the env `DEER_FLOW_MEMORY_TELEMETRY_LOG=0` is set and a memory write occurs
- **THEN** the in-memory counter SHALL still increment but no JSONL line SHALL be appended

#### Scenario: Summary endpoint returns counter snapshot

- **WHEN** a client issues `GET /api/telemetry/memory/summary`
- **THEN** the response SHALL include counts for all six event types above
