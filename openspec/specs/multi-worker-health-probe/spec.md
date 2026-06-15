## Purpose

Kubernetes-compatible health probe endpoints (`/health/live` and `/health/ready`) for multi-worker deployments. Liveness probe confirms process is alive; readiness probe checks all critical shared backend connectivity with caching and Prometheus metrics.

## Requirements

### Requirement: Readiness probe endpoint

The system SHALL provide a `GET /health/ready` endpoint that returns the health status of all critical shared backends. Results SHALL be cached for 10 seconds to avoid excessive probe load on backends.

#### Scenario: All backends healthy

- **WHEN** PostgreSQL, Redis, and vector store are all reachable
- **THEN** the endpoint SHALL return HTTP 200 with body:
  ```json
  {
    "status": "ready",
    "checks": {
      "postgres": {"status": "ok", "latency_ms": 3},
      "redis": {"status": "ok", "latency_ms": 1},
      "vector_store": {"status": "ok", "backend": "pgvector"}
    }
  }
  ```

#### Scenario: PostgreSQL unreachable

- **WHEN** PostgreSQL connection fails
- **THEN** the endpoint SHALL return HTTP 503
- **AND** the `postgres` check SHALL have `"status": "error"` with an error message

#### Scenario: Redis not configured

- **WHEN** `stream_bridge.type` is `"memory"` (Redis not required)
- **THEN** the Redis check SHALL have `"status": "skipped"` with a message indicating Redis is not configured
- **AND** SHALL NOT cause the overall status to be "not ready"

#### Scenario: Cached result returned

- **WHEN** a health check was performed within the last 10 seconds
- **THEN** the endpoint SHALL return the cached result without re-probing backends
- **AND** the response SHALL include `"cached": true` in the JSON body

#### Scenario: Cache expired triggers fresh probe

- **WHEN** the last health check was more than 10 seconds ago
- **THEN** the endpoint SHALL perform fresh probes of all backends
- **AND** SHALL update the cache with the new results

### Requirement: Liveness probe endpoint

The system SHALL provide a `GET /health/live` endpoint that returns HTTP 200 if the process is running and responsive, regardless of backend connectivity. This endpoint SHALL NOT check external dependencies and SHALL NOT cache results (K8s liveness probes need real-time status).

#### Scenario: Process alive

- **WHEN** the process is running and can handle HTTP requests
- **THEN** the endpoint SHALL return HTTP 200 with `{"status": "alive"}`

#### Scenario: Process overloaded

- **WHEN** the process is running but event loop is blocked
- **THEN** the endpoint SHALL NOT respond within the HTTP timeout
- **AND** the orchestrator SHALL consider the process unhealthy and restart it

### Requirement: Health check latency threshold

Backend health checks SHALL use a configurable timeout (default: 5 seconds). If a backend does not respond within the timeout, it SHALL be reported as `"status": "timeout"`.

#### Scenario: Slow PostgreSQL response

- **WHEN** PostgreSQL responds in 8 seconds (exceeding the 5-second threshold)
- **THEN** the `postgres` check SHALL report `"status": "timeout"`
- **AND** the overall status SHALL be "not ready"

### Requirement: Health check metrics

Each health check SHALL increment a Prometheus-style counter `health_check_total{backend, status}` for monitoring dashboards.

#### Scenario: Health check metrics emitted

- **WHEN** a health check is performed for PostgreSQL
- **THEN** the counter `health_check_total{backend="postgres", status="ok"}` SHALL be incremented
- **AND** the counter SHALL be accessible via the existing metrics endpoint
