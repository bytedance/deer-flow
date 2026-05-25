## ADDED Requirements

### Requirement: Core knowledge link metrics are collected
The system SHALL collect and expose core knowledge link metrics including index success rate, rebuild completion rate, retrieval latency, and failure reason categories.

#### Scenario: Metrics are available for review
- **WHEN** a monthly review is conducted
- **THEN** the knowledge link metrics SHALL be available and cover at minimum: index success rate, rebuild completion rate, and retrieval latency percentiles

#### Scenario: Failure reasons are categorized
- **WHEN** indexing or retrieval fails
- **THEN** the failure SHALL be categorized (e.g., document format, size exceeded, service timeout, permission denied) and tallied in metrics
