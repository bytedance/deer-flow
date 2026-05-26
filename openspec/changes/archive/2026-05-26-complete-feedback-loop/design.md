## Context

DeerFlow currently has two data-collection subsystems that operate in isolation:

1. **Feedback** — Two parallel storage mechanisms:
   - **SQL-backed** (`persistence.feedback.sql.FeedbackRepository`): Stores +1/-1 ratings with `run_id`, `thread_id`, `user_id`, and optional `comment`. This is the primary path for run-scoped feedback.
   - **JSON-file legacy** (`feedback.storage.FeedbackStorage`): Stores 1-5 star ratings with categories and comments, but lacks `run_id` and `user_id`. Used by the legacy `simple_feedback_router`.
   
   Neither path feeds data downstream. The SQL path can correlate feedback with agents via JOIN with `AgentUsageRow` (which records `agent_name` per `run_id`), but the JSON path cannot.

2. **Closure tickets** (`closed_loop.*`) — Full lifecycle management (pending → assigned → in_progress → pending_verification → closed/rejected) with state machine, audit events, SLA tracking, and overdue scanning. Resolution data is **not stored in dedicated columns** but captured in `ClosureTicketEventRow.payload` during `submit_verification` and `verify_close` transitions (e.g., `verification_summary`, `evidence` pointers). This data is never reused.

The gap: there is no analytical layer, no aggregation, no insight extraction, and no mechanism to feed learnings back into the agent system (prompts, knowledge base, memory). Data flows one way — in, but never back out as improvement.

**Constraints**:
- SQL feedback storage requires database engine (SQLite or PostgreSQL — see `migrate-current-system-to-postgresql` change)
- The system must work in both SQLite and PostgreSQL modes
- The admin dashboard must not add heavy infrastructure (no Prometheus/OTel dependency)
- Improvement signals must respect tenant isolation
- Auto-generated KB entries must have a human review gate before indexing
- Memory fact creation API (`create_memory_fact`) currently hardcodes `source: "manual"` — needs extension to support `source: "feedback_loop"`

## Goals / Non-Goals

**Goals:**
- Close the feedback loop: collected data → analysis → actionable insight → system improvement
- Provide administrators with visibility into feedback trends and closure metrics
- Automatically promote verified closure resolutions into KB entries (with review gate)
- Generate ranked improvement suggestions based on feedback patterns
- Feed verified improvement signals into agent memory for adaptive behavior

**Non-Goals:**
- Real-time feedback processing (batch/daily aggregation is sufficient for MVP)
- Automated prompt rewrites without human review
- Model fine-tuning or retraining pipelines
- Cross-tenant analytics (all insights are tenant-scoped)
- Replacing the existing feedback storage systems — the analytics layer reads from SQL `FeedbackRepository`
- Skill-level feedback correlation in MVP (deferred until skill usage tracking is added to `RunRow`)

## Decisions

### D1: Analytics reads from SQL `FeedbackRepository` with dual JOIN paths

**Decision**: The analytics engine reads from `persistence.feedback.sql.FeedbackRepository` (SQL-backed) and uses two distinct JOIN paths:

1. **Tenant isolation** (required): `FeedbackRow.thread_id` → JOIN `ThreadMetaRow.thread_id` → `ThreadMetaRow.tenant_id`. This path is always reliable — `ThreadMetaRow` is created when the thread is created, `tenant_id` has a default value (`"default"`), and the column is indexed.

2. **Agent correlation** (optional): `FeedbackRow.run_id` → JOIN `AgentUsageRow.run_id` → `AgentUsageRow.agent_name`. This path is nullable — `AgentUsageRow.run_id` may be absent when a run fails before usage recording or when feedback is submitted on a thread without a specific run. Feedback entries without a matching `AgentUsageRow` are counted in overall totals but recorded under `agent_name="unknown"`.

The JSON-file `FeedbackStorage` is excluded from MVP analytics. Aggregation results are cached in a separate `InsightsCache` (JSON-file for now, PostgreSQL-ready interface).

**Rationale**: `FeedbackRow` has no `tenant_id` column, so tenant scoping must go through a JOIN. `ThreadMetaRow` is the correct target — it always has `tenant_id` and is indexed for fast lookups. `AgentUsageRow` is tempting as a single JOIN target (it has both `tenant_id` and `agent_name`), but its `run_id` is nullable, which would silently drop feedback entries from failed/interrupted runs during tenant scoping. Separating the two concerns (tenant via `ThreadMetaRow`, agent via `AgentUsageRow`) is both more correct and more resilient. The SQL path also has `run_id` for agent correlation; the JSON path lacks `run_id` and `user_id` entirely. The `migrate-current-system-to-postgresql` change will later move all stores to PostgreSQL; the analytics layer just needs to swap its read adapter.

**Alternatives considered**:
- Read from both SQL and JSON paths — JSON path cannot correlate with agents, adds complexity for minimal value
- Event-sourcing with a new event bus — too heavy for current scale, adds infrastructure
- Materialized views in PostgreSQL — blocked until migration is complete

### D2: Batch aggregation via background job, agent-level only (no skill dimension in MVP)

**Decision**: A `FeedbackAggregator` runs on a configurable schedule (default: every 6 hours) and computes:
- Per-agent feedback distribution (positive/negative ratio, trend over 7d/30d) via `FeedbackRow` JOIN `AgentUsageRow` on `run_id`
- Comment text pattern analysis (keyword extraction from `FeedbackRow.comment` field)
- Closure metrics (resolution time, SLA compliance, overdue rate, verification pass rate)

The **skill dimension is deferred** to a future phase. Current `RunRow` does not track which skills were used in a run; this metadata exists only in LangGraph checkpoint state and is not indexed for querying.

**Rationale**: Feedback volume is low-to-moderate (enterprise deployments, not consumer scale). Batch processing avoids latency in the write path and keeps the analytics logic testable in isolation. Agent-level correlation is achievable via existing `AgentUsageRow`; skill-level would require schema changes or checkpoint parsing.

**Alternatives considered**:
- Streaming with event hooks on every feedback write — unnecessary complexity, tight coupling
- On-demand computation per API call — too slow for dashboard with historical data
- Skill-level correlation via checkpoint inspection — too complex, brittle, and slow for MVP

### D3: Closure-to-KB pipeline extracts from audit event payloads, not ticket columns

**Decision**: When a closure ticket transitions to `closed` (via `verify_close`), the `ClosureKnowledgeExtractor` queries `ClosureTicketEventRow` for events with `action` in (`submit_verification`, `verify_close`), extracts `verification_summary` and evidence pointers from the event `payload` JSON, and combines them with ticket metadata (`title`, `description`, `device_id`, `fault_category` from `extra_metadata`). The candidate is stored as a "pending review" item. An admin explicitly promotes it via `POST /api/insights/closure-knowledge/{ticket_id}/promote`. Only then does it enter the KB indexing pipeline.

**Rationale**: `ClosureTicketRow` has no dedicated `resolution_summary` or `verification_evidence` columns. Resolution data is captured in the audit trail's `payload` field during state transitions. Querying the event log and parsing payloads is the only way to access this data. The review gate prevents pollution of the knowledge base from potentially incomplete or hallucinated AI-generated summaries. This aligns with the existing `human_review_required` flag in interpretive reports (§13.2).

**Alternatives considered**:
- Add `resolution_summary` column to `ClosureTicketRow` — requires schema migration, breaks backward compatibility
- Fully automatic indexing — too risky without provenance guarantees
- No review gate, but flag as `source: "auto_closure"` — still allows hallucinated content into retrieval

### D4: Improvement suggestions as structured recommendations

**Decision**: The `ImprovementEngine` produces ranked `ImprovementSuggestion` objects with:
- `target`: what to improve (agent prompt, KB, tool config — not skills in MVP)
- `evidence`: the feedback/closure data that triggered it
- `suggestion`: concrete action (e.g., "Add error handling for X in agent Y")
- `confidence`: 0-1 score based on evidence volume and consistency
- `status`: pending / accepted / applied / dismissed

Suggestions are generated by an LLM call (using the lead agent's model) over aggregated evidence. Admin reviews and applies via API.

**Rationale**: Structured suggestions with evidence let admins make informed decisions. LLM-generated suggestions are cheap (one call per aggregation cycle) and can be dismissed without side effects. The `applied` status tracks which suggestions were actually implemented.

**Alternatives considered**:
- Rule-based suggestions only — too rigid, cannot handle novel patterns
- Fully automated application — too risky, no human review

### D5: Memory integration via `create_memory_fact()` with custom source parameter

**Decision**: When an admin applies an improvement suggestion, the `FeedbackMemoryIntegration` calls an extended version of `create_memory_fact()` that accepts a `source` parameter (default `"manual"` for backward compatibility, but allows `"feedback_loop"`). The fact is created with `source: "feedback_loop"`, `category: "improvement"`, and `confidence: 0.9`. This fact enters the standard memory injection pipeline and appears in the agent's system prompt.

**Rationale**: Reuses the existing memory system with minimal API extension. The agent naturally adapts behavior when improvement facts are injected. Facts have the same lifecycle as other memory facts (dedup, confidence decay, max_facts limit). The `source` field enables filtering and provenance tracking.

**Alternatives considered**:
- Create a separate `create_insight_fact()` function — duplicates logic, harder to maintain
- Direct prompt modification — brittle, hard to track provenance
- Separate "improvement store" — fragments the context injection, harder to manage

## Risks / Trade-offs

**[Risk] SQL JOIN complexity in SQLite vs PostgreSQL** → Mitigation: The JOIN query (`FeedbackRow` + `AgentUsageRow`) uses standard SQL that works in both engines. For MVP data volumes (< 10k feedback entries), SQLite performance is acceptable. Once `migrate-current-system-to-postgresql` lands, the cache moves to materialized views for better performance.

**[Risk] LLM-generated improvement suggestions may be low quality** → Mitigation: suggestions include evidence citations so admins can verify. Low-confidence suggestions (< 0.3) are suppressed by default.

**[Risk] Closure resolution data may be incomplete or hallucinated** → Mitigation: KB promotion requires explicit admin action. The review gate surfaces the full event payload content before indexing. Tenant isolation is enforced at every layer.

**[Risk] Batch aggregation may miss time-sensitive patterns** → Mitigation: the 6-hour default is configurable. Critical signals (e.g., 5+ negative feedbacks on one agent in 1 hour) trigger an immediate aggregation via a lightweight threshold check on each feedback write.

**[Trade-off] Exclude JSON-file feedback from analytics** → We accept that legacy 1-5 star ratings (which have categories but no `run_id`) are not analyzed in MVP. This simplifies the data model and focuses on the SQL path which has richer correlation potential. If category analysis is critical, it can be added as a separate JSON-only path in a future phase.

**[Trade-off] No skill-level feedback correlation in MVP** → Current `RunRow` does not track skill usage. Adding this would require schema changes or checkpoint parsing, which is out of scope. Agent-level correlation is sufficient for MVP; skill-level can be added when skill usage tracking is implemented.

**[Trade-off] JSON-file analytics cache vs PostgreSQL** → We accept file-based storage for MVP to avoid blocking on the PostgreSQL migration. The `InsightsCache` interface is designed to swap implementations. Once `migrate-current-system-to-postgresql` lands, the cache moves to materialized views.

**[Trade-off] Tenant-scoped analytics only** → Cross-tenant analytics (e.g., platform-wide quality benchmarks) is deferred. This keeps the data model simpler and avoids privacy concerns in multi-tenant deployments.
