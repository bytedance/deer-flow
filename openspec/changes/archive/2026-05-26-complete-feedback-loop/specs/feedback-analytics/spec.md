## ADDED Requirements

### Requirement: Feedback aggregation by agent via SQL JOIN
The system SHALL aggregate feedback entries from the SQL `FeedbackRepository` by joining `FeedbackRow` with `AgentUsageRow` on `run_id` to resolve `agent_name`. The system SHALL compute positive/negative ratios and counts over configurable time windows (7d, 30d, custom range). Aggregation SHALL run as a background job on a configurable schedule (default: 6 hours).

#### Scenario: Scheduled aggregation produces agent-level metrics
- **WHEN** the aggregation job runs on schedule
- **THEN** the system executes a SQL query joining `FeedbackRow` with `AgentUsageRow` on `run_id`, computes per-agent positive count, negative count, ratio, and trend direction (improving/stable/declining) for the configured time windows, and persists results to the insights cache

#### Scenario: Agent with mixed feedback
- **WHEN** an agent has 12 positive and 3 negative feedback entries in the past 7 days (resolved via `AgentUsageRow.agent_name`)
- **THEN** the aggregation reports positive_ratio=0.8, total=15, trend="stable" for that agent

#### Scenario: Feedback with no matching AgentUsageRow
- **WHEN** a `FeedbackRow` has a `run_id` that does not exist in `AgentUsageRow` (e.g., run failed before usage was recorded)
- **THEN** the feedback entry is counted in overall totals but excluded from per-agent breakdown, and recorded under agent_name="unknown"

### Requirement: Comment text pattern analysis
The system SHALL analyze `FeedbackRow.comment` text fields to extract recurring complaint patterns via keyword frequency analysis. Comments SHALL be tokenized and common stop words removed before counting.

#### Scenario: Recurring complaint pattern in comments
- **WHEN** 15 feedback comments in the past 30 days contain the phrase "数据不准确" or "inaccurate data"
- **THEN** the analysis reports "inaccurate" as a top complaint keyword with count=15 and associated agent names

#### Scenario: Empty comments excluded
- **WHEN** feedback entries have null or empty `comment` fields
- **THEN** those entries are excluded from comment pattern analysis but still counted in positive/negative ratio aggregation

### Requirement: Negative feedback cluster detection
The system SHALL detect clusters of negative feedback — defined as N or more negative entries for the same agent (resolved via `AgentUsageRow`) within a short time window — and emit an alert signal.

#### Scenario: Spike in negative feedback for one agent
- **WHEN** 5 or more negative feedback entries are submitted for the same agent within 1 hour
- **THEN** the system emits an immediate alert signal (bypassing the batch schedule) and records the cluster with its timestamp, agent, and contributing feedback IDs

#### Scenario: Cluster threshold is configurable
- **WHEN** the cluster threshold is configured to 10 in `config.yaml` under `insights.cluster_threshold`
- **THEN** the system only emits a cluster alert when 10 or more negative entries occur within the time window

### Requirement: Tenant-scoped isolation
All feedback analytics SHALL be scoped to `tenant_id` via `FeedbackRow.thread_id` JOIN `ThreadMetaRow.thread_id` → `ThreadMetaRow.tenant_id`. The `ThreadMetaRow` path SHALL be used for tenant isolation (not `AgentUsageRow.tenant_id`) because `ThreadMetaRow.tenant_id` is always present (default=`"default"`, indexed) while `AgentUsageRow.run_id` is nullable. Aggregation results from one tenant SHALL NOT be visible to or influence another tenant's analytics.

#### Scenario: Tenant A cannot see Tenant B analytics
- **WHEN** Tenant A requests feedback trends via the API
- **THEN** the SQL query includes `JOIN ThreadMetaRow ON FeedbackRow.thread_id = ThreadMetaRow.thread_id WHERE ThreadMetaRow.tenant_id = :tenant_id` and the response contains only feedback entries and aggregations belonging to Tenant A

#### Scenario: Feedback with no AgentUsageRow still tenant-scoped
- **WHEN** a `FeedbackRow` has a `run_id` that does not exist in `AgentUsageRow` (e.g., run failed before usage was recorded)
- **THEN** the feedback entry is still included in tenant-scoped aggregation (via `ThreadMetaRow` JOIN), counted in overall totals, but excluded from per-agent breakdown and recorded under `agent_name="unknown"`

### Requirement: Skill dimension deferred
The system SHALL NOT attempt skill-level feedback correlation in MVP. The analytics output SHALL include a `skill_correlation_available: false` flag to indicate this dimension is not yet supported.

#### Scenario: API response indicates skill dimension unavailable
- **WHEN** an admin queries feedback trends
- **THEN** the response includes `skill_correlation_available: false` in the metadata, signaling that skill-level breakdown will be available in a future release
