## ADDED Requirements

### Requirement: Retrieval latency tracking
The system SHALL track and expose retrieval latency metrics per knowledge base.

#### Scenario: Retrieval stats endpoint reports latency
- **WHEN** an authorized user requests retrieval statistics for a knowledge base
- **THEN** the response SHALL include `avg_retrieval_latency_ms`, `p95_retrieval_latency_ms`, and `total_queries` for recent retrieval operations

### Requirement: Knowledge base retrieval health indicator
The system SHALL indicate whether retrieval from a knowledge base is operating within expected parameters.

#### Scenario: Healthy retrieval returns normal status
- **WHEN** a knowledge base has successful recent retrievals within expected latency
- **THEN** the health indicator SHALL show "healthy"

#### Scenario: Degraded retrieval returns warning status
- **WHEN** a knowledge base has elevated error rates or latency in recent retrievals
- **THEN** the health indicator SHALL show "degraded"

#### Scenario: Failed retrieval returns error status
- **WHEN** a knowledge base consistently fails retrieval operations
- **THEN** the health indicator SHALL show "error" with the failure reason

### Requirement: Observability metrics documentation
The system SHALL provide a documented reference for knowledge chain metrics including calculation methods and recommended alert thresholds.

#### Scenario: Metrics documentation is accessible
- **WHEN** an operator or technical owner needs to understand knowledge chain metrics
- **THEN** a metrics reference document SHALL define each metric's calculation method, data source, and suggested alert thresholds

#### Scenario: Metrics can be referenced in monthly reviews
- **WHEN** a monthly architecture or planning review occurs
- **THEN** the documented metrics SHALL be directly quotable for knowledge chain health assessment
