# Implementation Tasks

## 1. Foundation — Insights Package Structure

- [x] 1.1 Create `backend/packages/harness/deerflow/insights/` package with `__init__.py`, module layout: `analytics.py`, `cache.py`, `improvement.py`, `knowledge_extractor.py`, `memory_integration.py`
- [x] 1.2 Define shared data models in `insights/models.py`: `FeedbackTrend`, `ClosureMetrics`, `ImprovementSuggestion`, `KBCandidate`, `InsightAlert` (all Pydantic, frozen)
- [x] 1.3 Create `InsightsCache` interface in `insights/cache.py` with `get/set/delete` methods and JSON-file implementation (`JsonFileInsightsCache`) respecting tenant isolation paths
- [x] 1.4 Register `insights:read` and `insights:write` permissions in the auth permission system, grant to superadmin and tenant_admin roles by default

## 2. Feedback Analytics Engine

- [x] 2.1 Implement `FeedbackAggregator` in `insights/analytics.py` that reads from SQL `FeedbackRepository` via `persistence.feedback.sql.FeedbackRepository`, scoped by `tenant_id`
- [x] 2.2 Implement per-agent aggregation with dual JOIN paths: JOIN `FeedbackRow.thread_id` with `ThreadMetaRow.thread_id` for tenant isolation (always present, indexed), and JOIN `FeedbackRow.run_id` with `AgentUsageRow.run_id` for agent correlation (nullable). Compute positive_count, negative_count, positive_ratio, trend_direction (improving/stable/declining) for 7d and 30d windows
- [x] 2.3 Handle feedback entries with no matching `AgentUsageRow`: count in overall totals but record under agent_name="unknown" in per-agent breakdown
- [x] 2.4 Implement comment text pattern analysis: tokenize `FeedbackRow.comment` fields, remove common stop words, count keyword frequencies per agent and overall
- [x] 2.5 Implement negative cluster detection: threshold-based check (>=5 negatives for same agent within 1 hour via `AgentUsageRow` JOIN) that emits an immediate `InsightAlert` signal
- [x] 2.6 Add cluster detection hook to feedback write path: after `FeedbackRepository.create()` or `upsert()`, call a lightweight `_check_cluster_threshold()` that schedules an early aggregation if triggered
- [x] 2.7 Implement background scheduler for batch aggregation (default 6-hour interval, configurable via `config.yaml` `insights.aggregation_interval_hours`)
- [x] 2.8 Add `skill_correlation_available: false` flag to aggregation output to indicate skill dimension is deferred
- [x] 2.9 Write unit tests for all analytics functions: agent aggregation via JOIN, comment keyword extraction, cluster detection, tenant isolation, handling of missing AgentUsageRow

## 3. Closure-to-Knowledge Pipeline

- [x] 3.1 Implement `ClosureKnowledgeExtractor` in `insights/knowledge_extractor.py`: on `verify_close` transition, query `ClosureTicketEventRow` for events with `action` in (`submit_verification`, `verify_close`)
- [x] 3.2 Extract `verification_summary` and `evidence` pointers from event `payload` JSON fields, combine with ticket metadata (`title`, `description`, `device_id`, `device_name`, `extra_metadata` including fault_category)
- [x] 3.3 Add hook in `closed_loop/service.py` `transition()` path: when action is `VERIFY_CLOSE` and transition succeeds, call `ClosureKnowledgeExtractor.extract()` to generate candidate
- [x] 3.4 Implement KB candidate storage: persist candidates in `{DEER_FLOW_HOME}/insights/{tenant_id}/kb_candidates/` as JSON files with status field (pending_review / approved / dismissed)
- [x] 3.5 Implement `promote()` method: change candidate status to "approved", construct a KB document with proper metadata tags (device_id, fault_category, source_ticket_id, verifier_id from event actor_id), submit to KB indexing pipeline via `IndexingDispatcher.submit(IndexJobRequest(document=..., knowledge_base=...))`
- [x] 3.6 Implement `dismiss()` method: change candidate status to "dismissed" with reason recorded
- [x] 3.7 Ensure pending_review candidates are excluded from KB retrieval by only indexing approved candidates
- [x] 3.8 Handle edge case: ticket with no `submit_verification` event (verifier closed directly) — generate candidate using only ticket metadata and `verify_close` event payload
- [x] 3.9 Write unit tests: extraction from event payloads, promote flow, dismiss flow, tenant isolation on promotion, pending candidates excluded from retrieval, missing submit_verification event

## 4. Signal-to-Improvement Bridge

- [x] 4.1 Implement `ImprovementEngine` in `insights/improvement.py`: takes aggregated analytics results (per-agent metrics from JOIN) + closure pattern data as input, produces ranked `ImprovementSuggestion` objects
- [x] 4.2 Implement evidence collection: for each potential improvement target, gather supporting feedback IDs, closure ticket IDs, and aggregation metrics
- [x] 4.3 Implement confidence scoring: weight by evidence volume, consistency across time windows, and source quality (verified closures with complete event payloads > unverified feedback)
- [x] 4.4 Implement LLM-based suggestion generation: call the lead agent's model with evidence summary to produce natural-language suggestion text (one call per aggregation cycle, low token budget)
- [x] 4.5 Implement suggestion deduplication: before creating a new suggestion, check if a pending suggestion with the same (target, issue_pattern) exists; if so, extend its evidence list and update confidence
- [x] 4.6 Implement low-confidence suppression: filter out suggestions with confidence < configurable threshold (default 0.3) before surfacing via API
- [x] 4.7 Implement suggestion lifecycle: `accept()`, `apply()`, `dismiss()` state transitions with persistence to insights cache
- [x] 4.8 Exclude `skill` target type from suggestion generation in MVP (skill usage tracking not available in RunRow)
- [x] 4.9 Write unit tests: confidence scoring, deduplication, suppression, lifecycle transitions, evidence collection

## 5. Admin Insight Dashboard API

- [x] 5.1 Create `backend/app/gateway/routers/insights.py` with `APIRouter(prefix="/api/insights", tags=["insights"])`
- [x] 5.2 Implement `GET /api/insights/feedback-trends`: query parameters for agent_name, days, keyword; returns aggregated metrics from InsightsCache with `skill_correlation_available: false` in metadata
- [x] 5.3 Implement `GET /api/insights/closure-metrics`: query parameters for priority, status, date range; returns open_count, closed_count, overdue_count, avg_resolution_hours, sla_compliance_rate, verification_pass_rate
- [x] 5.4 Implement `GET /api/insights/improvements`: query parameters for status (pending/accepted/applied/dismissed), target filter; returns ranked list sorted by confidence descending
- [x] 5.5 Implement `POST /api/insights/improvements/{id}/apply`: accepts optional note body, changes suggestion status to "applied", triggers feedback-memory-integration
- [x] 5.6 Implement `POST /api/insights/improvements/{id}/dismiss`: accepts required reason body, changes suggestion status to "dismissed"
- [x] 5.7 Implement `GET /api/insights/closure-knowledge`: query parameters for status (pending_review/approved/dismissed); returns KB candidates list
- [x] 5.8 Implement `POST /api/insights/closure-knowledge/{ticket_id}/promote`: accepts target_kb_id body, calls knowledge_extractor.promote()
- [x] 5.9 Implement `POST /api/insights/closure-knowledge/{ticket_id}/dismiss`: accepts reason body, calls knowledge_extractor.dismiss()
- [x] 5.10 Add `@require_permission("insights", "read")` to all GET endpoints and `@require_permission("insights", "write")` to all POST/state-changing endpoints
- [x] 5.11 Register the insights router in `app/gateway/app.py`
- [x] 5.12 Write integration tests for all dashboard endpoints: auth gating, tenant isolation, correct data shapes, error handling

## 6. Feedback-Memory Integration

- [x] 6.1 Extend `create_memory_fact()` in `deerflow.agents.memory.updater` to accept optional `source` parameter (default "manual" for backward compatibility). Also update `DeerFlowClient.create_memory_fact()` wrapper at `client.py:1072-1076` to accept and pass through the `source` parameter for API consistency
- [x] 6.2 Implement `FeedbackMemoryIntegration` in `insights/memory_integration.py`: on suggestion apply, construct a memory fact with source="feedback_loop", category="improvement", confidence=0.9
- [x] 6.3 Implement deduplication check: before creating a new fact, search existing facts for matching content (whitespace-normalized); if found, boost confidence by 0.1 (capped at 1.0) and refresh updatedAt
- [x] 6.4 Implement fact injection: call extended `create_memory_fact()` with custom source="feedback_loop"
- [x] 6.5 Implement provenance tracking: store suggestion_id in the fact's metadata (extend fact dict to include optional suggestion_id field)
- [x] 6.6 Wire integration into the improvement apply flow: when `POST /api/insights/improvements/{id}/apply` succeeds, call `FeedbackMemoryIntegration.on_suggestion_applied()`
- [x] 6.7 Write unit tests: fact creation with custom source, deduplication with existing facts, confidence boost, max_facts eviction, provenance tracking, backward compatibility (source defaults to "manual")
- [x] 6.8 Coordinate merge order with `frontend-memory-layers` change: both modify `create_memory_fact()` signature in `updater.py`. Recommended order: merge `frontend-memory-layers` first, then rebase this change's `source` parameter on top. If this change merges first, `frontend-memory-layers` must preserve the `source` parameter when adding its new fields

## 7. Configuration and Wiring

- [x] 7.1 Add `insights` section to `config.yaml` schema: `enabled` (bool), `aggregation_interval_hours` (int, default 6), `cluster_threshold` (int, default 5), `low_confidence_threshold` (float, default 0.3), `improvement_model_name` (optional string)
- [x] 7.2 Add `insights` to `config.example.yaml` with documented defaults
- [x] 7.3 Wire insights scheduler into gateway lifespan: start on app startup, graceful shutdown on app stop (similar to `IndexingDispatcher` pattern)
- [x] 7.4 Add `get_insights_cache()` and `get_improvement_engine()` dependency injection functions to `app/gateway/deps.py`
- [x] 7.5 Update CLAUDE.md with insights module documentation

## 8. Testing and Validation

- [x] 8.1 Write end-to-end test: submit feedback → run aggregation (with AgentUsageRow JOIN) → verify analytics output → generate improvement → apply suggestion → verify memory fact created with source="feedback_loop"
- [x] 8.2 Write end-to-end test: create closure ticket → submit_verification event with payload → verify_close event → verify KB candidate generated from event payloads → promote → verify KB document indexed
- [x] 8.3 Write tenant isolation test: verify Tenant A analytics cannot see Tenant B data at every layer (analytics, KB candidates, improvements, memory)
- [x] 8.4 Write API integration tests: all dashboard endpoints with valid/invalid auth, correct/incorrect tenant scoping, error cases
- [x] 8.5 Write backward compatibility test: verify existing `create_memory_fact()` calls without source parameter still create facts with source="manual"
- [x] 8.6 Run full test suite: `make test` to ensure no regressions in existing feedback or closure modules

## 9. Documentation and Deployment

- [x] 9.1 Add admin guide section for insights dashboard: how to view trends, apply improvements, manage KB candidates
- [x] 9.2 Document soft prerequisite: note that `migrate-current-system-to-postgresql` improves performance but SQLite mode works for MVP
- [x] 9.3 Create deployment checklist: verify database schema includes AgentUsageRow and ClosureTicketEventRow tables, verify insights config section present
