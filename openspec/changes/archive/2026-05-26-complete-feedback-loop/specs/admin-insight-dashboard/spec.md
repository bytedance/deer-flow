## ADDED Requirements

### Requirement: Feedback trends API
The system SHALL expose `GET /api/insights/feedback-trends` returning aggregated feedback metrics filterable by time range, agent name, skill name, and dimension. Response SHALL include positive/negative counts, ratios, trends, and top complaint categories.

#### Scenario: Query feedback trends for an agent
- **WHEN** an admin calls `GET /api/insights/feedback-trends?agent_name=ai-report--daily&days=30`
- **THEN** the response contains positive_count, negative_count, positive_ratio, trend_direction, and top_categories for that agent over the past 30 days

#### Scenario: Query overall feedback trends
- **WHEN** an admin calls `GET /api/insights/feedback-trends?days=7`
- **THEN** the response contains aggregate metrics across all agents for the past 7 days

### Requirement: Closure metrics API
The system SHALL expose `GET /api/insights/closure-metrics` returning closure ticket metrics: total open, closed, overdue, average resolution time, SLA compliance rate, and verification pass rate.

#### Scenario: Query closure metrics
- **WHEN** an admin calls `GET /api/insights/closure-metrics`
- **THEN** the response contains open_count, closed_count, overdue_count, avg_resolution_hours, sla_compliance_rate, and verification_pass_rate for the tenant

#### Scenario: Closure metrics filtered by priority
- **WHEN** an admin calls `GET /api/insights/closure-metrics?priority=urgent`
- **THEN** the response contains metrics scoped to urgent-priority tickets only

### Requirement: Improvement suggestions API
The system SHALL expose `GET /api/insights/improvements` returning ranked improvement suggestions with status filter (pending/accepted/applied/dismissed). Results SHALL be sorted by confidence descending.

#### Scenario: List pending suggestions
- **WHEN** an admin calls `GET /api/insights/improvements?status=pending`
- **THEN** the response contains a list of suggestions with target, suggestion text, confidence, evidence summary, and created_at, sorted by confidence descending

#### Scenario: Apply a suggestion
- **WHEN** an admin calls `POST /api/insights/improvements/{id}/apply` with an optional note
- **THEN** the suggestion status changes to "applied" and the response confirms the change

### Requirement: Closure knowledge promotion API
The system SHALL expose endpoints for managing KB candidates generated from closure tickets: list pending candidates, promote to KB, and dismiss with reason.

#### Scenario: List pending KB candidates
- **WHEN** an admin calls `GET /api/insights/closure-knowledge?status=pending_review`
- **THEN** the response contains a list of KB candidates with title, source_ticket_id, device context, and created_at

#### Scenario: Promote candidate to KB
- **WHEN** an admin calls `POST /api/insights/closure-knowledge/{ticket_id}/promote` with target_kb_id
- **THEN** the candidate is approved and submitted to the KB indexing pipeline for the specified knowledge base

### Requirement: Admin-only access control
All insight dashboard endpoints SHALL require the `insights:read` permission for viewing and `insights:write` permission for state-changing operations (apply, promote, dismiss). These permissions SHALL be granted to superadmin and tenant_admin roles by default.

#### Scenario: Non-admin user denied access
- **WHEN** a user without `insights:read` permission calls `GET /api/insights/feedback-trends`
- **THEN** the system returns a 403 Forbidden response

#### Scenario: Admin user has access
- **WHEN** a tenant_admin calls `GET /api/insights/feedback-trends`
- **THEN** the system returns the requested data with tenant-scoped results
