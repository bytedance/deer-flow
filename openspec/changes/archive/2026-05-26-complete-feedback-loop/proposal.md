## Why

The system collects user feedback (thumbs up/down, comments) via SQL-backed `FeedbackRepository` and manages closure tickets (issue lifecycle from creation to verification/close) via `ClosureRepository`, but neither data stream flows back into system improvement. The chain from "data collection" to "actionable insight" to "system enhancement" is broken — feedback is stored but never analyzed, closure resolutions are recorded in audit event payloads but never used to enrich the knowledge base or improve AI prompts. This creates a dead-end data pipeline that wastes operational signals and prevents the system from learning from its own usage.

## What Changes

- Add a **Feedback Analytics Engine** that aggregates feedback patterns by agent (via `FeedbackRow` JOIN `AgentUsageRow`), thread topic, and time window — surfacing negative-feedback clusters and recurring complaint patterns from comment text analysis
- Add a **Closure-to-Knowledge Pipeline** that extracts resolution data from closure ticket audit event payloads (`submit_verification` / `verify_close` events) and converts them into knowledge base entries (with human review gate)
- Add a **Signal-to-Improvement Bridge** that connects negative feedback signals to concrete improvement recommendations: prompt adjustments or agent configuration changes
- Add an **Admin Insight Dashboard API** that exposes feedback trends, closure resolution rates, SLA compliance, and improvement suggestions
- Add a **Feedback Memory Integration** that feeds verified improvement signals into the agent memory system so the lead agent can adapt behavior over time

## Capabilities

### New Capabilities
- `feedback-analytics`: Aggregate and analyze feedback data by agent (via SQL JOIN with agent_usage table), topic, and time window; detect negative clusters and trending complaint patterns from comment text
- `closure-knowledge-pipeline`: Extract resolution data from closure ticket audit event payloads, generate knowledge base candidates with human review gate; auto-tag and index approved solutions
- `signal-improvement-bridge`: Connect negative feedback signals and closure patterns to concrete improvement recommendations (prompts, agent config)
- `admin-insight-dashboard`: REST API exposing feedback trends, closure metrics, SLA compliance, and actionable improvement suggestions
- `feedback-memory-integration`: Feed verified improvement signals into agent memory system for adaptive behavior

### Modified Capabilities
(none — existing specs do not need requirement-level changes)

## Impact

**Code**:
- `backend/packages/harness/deerflow/insights/` — new package: analytics, cache, improvement engine, knowledge extractor, memory integration
- `backend/packages/harness/deerflow/agents/memory/updater.py` — extend `create_memory_fact()` to accept custom `source` parameter (or add `create_insight_fact()`)
- `backend/app/gateway/routers/insights.py` — new REST API for admin dashboard
- `backend/packages/harness/deerflow/closed_loop/service.py` — add hook in transition path for knowledge extraction

**Data Sources** (read-only, no schema changes):
- `FeedbackRow.thread_id` → JOIN `ThreadMetaRow.thread_id` → `ThreadMetaRow.tenant_id` — tenant isolation (always present, indexed, default=`"default"`)
- `FeedbackRow.run_id` → JOIN `AgentUsageRow.run_id` → `AgentUsageRow.agent_name` — optional agent correlation (`AgentUsageRow.run_id` is nullable; failed/interrupted runs may lack usage records)
- `ClosureTicketEventRow.payload` (audit events) → resolution data for KB candidate generation

**Soft Prerequisite**:
- `migrate-current-system-to-postgresql` — SQLite mode works for MVP but analytical JOIN queries perform better on PostgreSQL; full feature set assumes PostgreSQL backend

**Dependencies**:
- Existing `FeedbackRepository` (SQL) and `ClosureRepository` (no new external deps)
- Optional: `numpy` for statistical trend detection (already available via data-analyst skill)
- No new infrastructure dependencies

**Parallel Changes** (merge coordination required):

- `frontend-memory-layers` — also modifies `create_memory_fact()` in `updater.py` (adds new fields). Both changes touch the same function signature. Merge order matters: whichever lands first becomes the base the other must rebase onto. Recommended: merge `frontend-memory-layers` first (larger scope, 59 tasks), then rebase this change's `source` parameter addition on top. Alternatively, if this change merges first, `frontend-memory-layers` must add `source` alongside its new fields in a single commit to avoid signature drift

**APIs**:
- `GET /api/insights/feedback-trends` — feedback aggregation by dimension
- `GET /api/insights/closure-metrics` — SLA compliance, resolution rates, overdue counts
- `GET /api/insights/improvements` — ranked improvement suggestions
- `POST /api/insights/improvements/{id}/apply` — apply a suggested improvement (admin only)
- `POST /api/insights/closure-knowledge/{ticket_id}/promote` — promote closure to KB entry (admin review)
