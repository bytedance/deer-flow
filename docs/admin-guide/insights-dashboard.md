# Insights Dashboard

The insights system closes the feedback loop: collecting user feedback and closure ticket data, generating improvement suggestions, and feeding verified improvements into agent memory.

## Overview

The insights pipeline has four stages:

1. **Feedback Aggregation** — Batch aggregation of feedback ratings per agent, with complaint keyword extraction and negative cluster detection
2. **Closure-to-Knowledge** — Extract KB candidates from verified closure ticket resolutions
3. **Improvement Generation** — Produce ranked improvement suggestions from analytics data
4. **Memory Integration** — Feed applied improvements into agent memory as facts with `source="feedback_loop"`

## Configuration

Add to `config.yaml`:

```yaml
insights:
  enabled: true
  aggregation_interval_hours: 6  # Batch aggregation interval
  cluster_threshold: 5           # Negatives per hour to trigger alert
  low_confidence_threshold: 0.3  # Suppress suggestions below this confidence
```

## Dashboard Endpoints

All endpoints require `insights:read` (GET) or `insights:write` (POST) permissions.

### Viewing Feedback Trends

```
GET /api/insights/feedback-trends?days=30&agent_name=researcher
```

Returns per-agent metrics: positive/negative counts, positive ratio, trend direction (improving/stable/declining), and top complaint keywords.

### Viewing Improvement Suggestions

```
GET /api/insights/improvements?status=pending
```

Returns ranked suggestions sorted by confidence descending. Each suggestion includes:
- **target**: `agent:<name>`, `kb`, or `tool:<name>`
- **confidence**: 0.0–1.0 based on evidence volume, consistency, and severity
- **evidence**: Supporting feedback IDs, closure ticket IDs, and metrics

### Applying a Suggestion

```
POST /api/insights/improvements/{id}/apply
Body: { "note": "Applied in sprint 5" }
```

Changes status to "applied" and creates a memory fact with `source="feedback_loop"`. The lead agent will see this fact in future sessions and can adapt behavior accordingly.

### Dismissing a Suggestion

```
POST /api/insights/improvements/{id}/dismiss
Body: { "reason": "Not relevant — configuration already updated" }
```

### Managing KB Candidates

```
GET /api/insights/closure-knowledge?status=pending_review
POST /api/insights/closure-knowledge/{ticket_id}/promote
Body: { "target_kb_id": "equipment-faq" }
POST /api/insights/closure-knowledge/{ticket_id}/dismiss
Body: { "reason": "Duplicate of existing KB article" }
```

KB candidates are generated from `submit_verification` and `verify_close` events on closure tickets. Pending candidates are excluded from KB retrieval until approved via the promote endpoint.

## Tenant Isolation

All insights data is scoped by tenant. Tenant isolation uses `ThreadMetaRow.tenant_id` for feedback queries and the tenant context variable for cache/storage paths. Cross-tenant access is not possible at any layer.

## Merge Coordination

If the `frontend-memory-layers` change is also in progress, coordinate merge order: both changes modify `create_memory_fact()` in `updater.py`. Recommended: merge `frontend-memory-layers` first, then rebase this change's `source` parameter on top.

## Database Prerequisites

The insights system works with both SQLite and PostgreSQL backends. SQLite is suitable for MVP and single-tenant deployments. PostgreSQL (via the `migrate-current-system-to-postgresql` change) provides better performance for multi-tenant deployments with high feedback volume, thanks to indexed queries on `ThreadMetaRow.tenant_id` and `AgentUsageRow.run_id`.

## Deployment Checklist

Before deploying the insights system, verify:

- [ ] Database schema includes `agent_usage` and `closure_ticket_events` tables
- [ ] `config.yaml` has an `insights` section (see Configuration above)
- [ ] `insights.enabled` is set to `true`
- [ ] Auth roles include `insights:read` and `insights:write` permissions for admin users
- [ ] Gateway lifespan starts the insights scheduler on app startup
- [ ] `{DEER_FLOW_HOME}/insights/` directory is writable by the application process
