## ADDED Requirements

### Requirement: Global KB health summary endpoint exists
The system SHALL provide a global health summary endpoint that aggregates index success rates, retrieval latency, and failure distributions across all knowledge bases accessible to the current user.

#### Scenario: Health summary returns aggregated stats
- **WHEN** a user requests `GET /api/knowledge-bases/health-summary`
- **THEN** the response SHALL include total knowledge base count, aggregate document counts by status, overall index success rate, global average retrieval latency, and per-KB breakdowns

#### Scenario: Health summary respects access control
- **WHEN** a user requests the health summary
- **THEN** the response SHALL only aggregate data from knowledge bases the user has read access to

#### Scenario: Health summary handles empty state
- **WHEN** a user with no accessible knowledge bases requests the health summary
- **THEN** the response SHALL return zero counts and an empty per-KB breakdown list, not an error

### Requirement: Health summary includes failure classification
The system SHALL classify and aggregate index failures across all accessible knowledge bases in the global health summary.

#### Scenario: Failure breakdown is cross-KB
- **WHEN** the health summary is requested and multiple KBs have failed documents
- **THEN** the response SHALL include a combined failure-by-type breakdown aggregating all accessible KBs

#### Scenario: Recent failures are surfaced globally
- **WHEN** the health summary is requested
- **THEN** the response SHALL include the most recent failures across all accessible KBs, ordered by finish time descending, limited to 20 entries

### Requirement: Health summary includes retrieval latency overview
The system SHALL include retrieval latency statistics in the global health summary, derived from the telemetry collector's in-memory samples.

#### Scenario: Retrieval latency is aggregated globally
- **WHEN** the health summary is requested and telemetry has retrieval latency samples
- **THEN** the response SHALL include global average and p95 retrieval latency in milliseconds, plus total query count across all KBs

#### Scenario: Zero retrieval data handled gracefully
- **WHEN** the health summary is requested but no retrieval queries have been recorded yet
- **THEN** the response SHALL report zero latency and zero query count without error
