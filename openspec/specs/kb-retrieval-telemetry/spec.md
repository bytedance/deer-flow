## ADDED Requirements

### Requirement: Multi-KB retrieval records telemetry
The system SHALL record retrieval latency and result events via `KbTelemetryCollector` for every `multi_kb_retrieve` call.

#### Scenario: Successful retrieval records latency per KB
- **WHEN** `multi_kb_retrieve` successfully retrieves results from one or more knowledge bases
- **THEN** the system SHALL record per-KB retrieval latency in milliseconds via `record_latency(kb_id, latency_ms)` for each KB queried

#### Scenario: Successful retrieval records result event
- **WHEN** `multi_kb_retrieve` completes successfully
- **THEN** the system SHALL record a `retrieval.completed` event with total result count, queried KB count, and per-KB hit breakdown

#### Scenario: Retrieval timeout records error event
- **WHEN** a per-KB retrieval times out
- **THEN** the system SHALL record a `retrieval.timeout` event with the KB ID and timeout duration

#### Scenario: Retrieval failure records error event
- **WHEN** a per-KB retrieval raises an exception
- **THEN** the system SHALL record a `retrieval.failed` event with the KB ID and error type

#### Scenario: Telemetry failure does not affect retrieval
- **WHEN** telemetry recording itself fails (e.g., lock contention)
- **THEN** the retrieval operation SHALL complete normally and return results without interruption

### Requirement: Search knowledge base tool records telemetry
The system SHALL record retrieval outcome events when `search_knowledge_base` is invoked as a tool.

#### Scenario: Tool-based search records telemetry
- **WHEN** `search_knowledge_base` completes a retrieval (via `_search_selected_kbs` or `_search_single_collection`)
- **THEN** the system SHALL record a `retrieval.completed` event with the query source marked as `"tool"`

#### Scenario: Blocked search records telemetry
- **WHEN** `search_knowledge_base` blocks a search due to missing auth or disabled RAG
- **THEN** the system SHALL record a `retrieval.blocked` event with the block reason

#### Scenario: Failed search records telemetry
- **WHEN** `search_knowledge_base` catches an exception during retrieval
- **THEN** the system SHALL record a `retrieval.failed` event with the error category

### Requirement: Retrieval telemetry is queryable via per-KB stats
The system SHALL include retrieval latency statistics from the telemetry collector in the existing per-KB index-stats endpoint.

#### Scenario: Index stats includes retrieval latency
- **WHEN** a user requests `GET /{kb_id}/index-stats` after retrieval queries have been recorded
- **THEN** the response SHALL include non-zero `avg_retrieval_latency_ms`, `p95_retrieval_latency_ms`, and `total_queries` fields reflecting the telemetry data

#### Scenario: Index stats handles zero retrieval data
- **WHEN** a user requests `GET /{kb_id}/index-stats` but no retrieval queries have been recorded for that KB
- **THEN** the response SHALL report `avg_retrieval_latency_ms: 0.0` and `total_queries: 0`
