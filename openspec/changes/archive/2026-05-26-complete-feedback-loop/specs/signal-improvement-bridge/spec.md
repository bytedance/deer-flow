## ADDED Requirements

### Requirement: Generate improvement suggestions from aggregated evidence
The system SHALL generate ranked `ImprovementSuggestion` objects by analyzing aggregated feedback patterns (per-agent metrics from `FeedbackRow` JOIN `AgentUsageRow`) and closure ticket data. Each suggestion SHALL include: target (agent/KB/tool), evidence (supporting data points), suggestion text, confidence score (0-1), and status (pending). The `skill` target type SHALL NOT be generated in MVP.

#### Scenario: Suggestion generated from negative feedback cluster
- **WHEN** the aggregation shows agent "ai-report--daily" has positive_ratio=0.2 over the past 30 days with 12 negative feedback entries whose comments frequently contain "inaccurate"
- **THEN** the system generates an ImprovementSuggestion with target="agent:ai-report--daily", suggestion="Review prompt and data sources for ai-report--daily agent; 12 negative feedback entries cite inaccurate output", confidence=0.75, evidence containing the feedback IDs and aggregation metrics

#### Scenario: Suggestion generated from recurring closure pattern
- **WHEN** 5 closure tickets in 30 days share the same fault_category and device_type in their `extra_metadata`
- **THEN** the system generates an ImprovementSuggestion with target="kb" suggesting creation of a preventive maintenance guide for that device_type/fault_category combination

### Requirement: Confidence scoring
Each improvement suggestion SHALL have a confidence score between 0 and 1 based on: evidence volume (more data points = higher confidence), consistency (similar patterns across time windows = higher), and source quality (verified closures with complete event payloads > unverified feedback).

#### Scenario: High confidence from strong evidence
- **WHEN** a suggestion is supported by 20+ feedback entries AND 3+ verified closure tickets with consistent patterns
- **THEN** the confidence score is >= 0.8

#### Scenario: Low confidence from weak evidence
- **WHEN** a suggestion is supported by only 2 feedback entries with no closure data
- **THEN** the confidence score is <= 0.3

### Requirement: Suppress low-confidence suggestions
Suggestions with confidence below a configurable threshold (default: 0.3) SHALL be suppressed and not surfaced in the API.

#### Scenario: Low-confidence suggestion not returned
- **WHEN** the improvement engine generates a suggestion with confidence=0.2
- **THEN** the suggestion is stored internally but not returned by `GET /api/insights/improvements`

### Requirement: Suggestion lifecycle management
An administrator SHALL be able to change a suggestion's status: accept (mark for implementation), apply (record that the change was made), or dismiss (with reason). Applied suggestions SHALL trigger the feedback-memory-integration to create a memory fact.

#### Scenario: Admin applies a suggestion
- **WHEN** an admin calls `POST /api/insights/improvements/{id}/apply` with an optional implementation note
- **THEN** the suggestion status changes to "applied", the implementation note is recorded, and the feedback-memory-integration module is notified to create a memory fact

#### Scenario: Admin dismisses a suggestion
- **WHEN** an admin calls `POST /api/insights/improvements/{id}/dismiss` with reason="already handled in last release"
- **THEN** the suggestion status changes to "dismissed" with the reason recorded

### Requirement: Suggestion deduplication
The system SHALL deduplicate suggestions that target the same (target, issue_pattern) combination across aggregation cycles. Existing pending suggestions SHALL NOT be re-created; instead, their evidence list is extended.

#### Scenario: Same issue detected in consecutive cycles
- **WHEN** the improvement engine runs in two consecutive cycles and both identify the same agent as problematic with overlapping evidence
- **THEN** the existing suggestion is updated with additional evidence and its confidence may increase, but no duplicate suggestion is created
