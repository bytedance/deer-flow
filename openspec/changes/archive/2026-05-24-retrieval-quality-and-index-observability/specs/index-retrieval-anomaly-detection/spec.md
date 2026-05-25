## ADDED Requirements

### Requirement: Anomalies can be located by knowledge base or task
The system SHALL support locating indexing failures and retrieval anomalies at the granularity of knowledge base or task.

#### Scenario: Operator locates a failing knowledge base
- **WHEN** an operator observes elevated failure rates
- **THEN** they SHALL be able to drill down to the specific knowledge base or task causing the failures

#### Scenario: Anomaly detection provides context
- **WHEN** a retrieval anomaly is detected
- **THEN** the system SHALL surface the affected knowledge base, time window, and failure count to aid diagnosis
