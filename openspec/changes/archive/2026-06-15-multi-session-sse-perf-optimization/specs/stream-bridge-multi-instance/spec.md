## ADDED Requirements

### Requirement: Backpressure with merge-drop overflow policy

The stream bridge memory queue SHALL implement a backpressure policy that uses merge-dropping for `messages-tuple` token events and FIFO dropping for other event types when the queue reaches its maximum size. The `queue_maxsize` default SHALL be 1024 (raised from 256). Each event SHALL carry a monotonically increasing sequence number.

#### Scenario: Queue full drops oldest non-token event via FIFO

- **WHEN** the stream bridge queue reaches `queue_maxsize` (default 1024) AND a new non-`messages-tuple` event is produced
- **THEN** the system SHALL dequeue and discard the oldest event
- **AND** enqueue the new event
- **AND** the agent worker SHALL NOT be blocked

#### Scenario: Queue full merge-drops intermediate token events

- **WHEN** the stream bridge queue reaches `queue_maxsize` AND the new event is a `messages-tuple` token event for a message that already has events in the queue
- **THEN** the system SHALL discard intermediate token events for that message (keeping the first and the new token)
- **AND** the message's first token event and the latest token event SHALL be preserved

#### Scenario: Sequence number monotonically increases

- **WHEN** events are produced by the agent worker
- **THEN** each event SHALL be assigned a sequence number that is strictly greater than the previous event's sequence number for the same run
- **AND** the sequence number SHALL be included in the SSE event payload

#### Scenario: Frontend detects sequence gap

- **WHEN** the frontend receives an SSE event with a sequence number that is more than 1 greater than the last received sequence number for the same run
- **THEN** the frontend SHALL recognize that one or more events were dropped
- **AND** initiate a state recovery by calling `/threads/{id}/state`

#### Scenario: Frontend recovers from dropped events

- **WHEN** a sequence gap is detected
- **THEN** the frontend SHALL fetch the full thread state via `/threads/{id}/state`
- **AND** reconcile the local state with the fetched state
- **AND** resume normal SSE consumption from the next event

### Requirement: queue_maxsize default raised to 1024

The default `queue_maxsize` in `StreamBridgeConfig` SHALL be 1024, raised from the current 256. This reduces the frequency of backpressure triggering in normal chat scenarios where a typical run produces fewer than 500 events.

#### Scenario: Default configuration uses 1024

- **WHEN** `StreamBridgeConfig` is created without an explicit `queue_maxsize`
- **THEN** the default value SHALL be 1024

#### Scenario: Explicit configuration overrides default

- **WHEN** `StreamBridgeConfig` is created with an explicit `queue_maxsize` value
- **THEN** the configured value SHALL be used

### Requirement: Nginx sticky session for stream continuity

When deployed behind Nginx with multiple backend workers, Nginx SHALL route all requests for the same thread to the same backend worker, ensuring that SSE streams and reconnection requests hit the worker that holds the stream bridge queue.

#### Scenario: Same thread routes to same worker

- **WHEN** a client sends multiple requests (stream, reconnect, state fetch) for the same `thread_id`
- **THEN** Nginx SHALL route all requests to the same backend worker based on a consistent hash of the `thread_id`

#### Scenario: Worker failure triggers failover

- **WHEN** the backend worker holding a thread's stream queue becomes unavailable
- **THEN** Nginx SHALL route subsequent requests to a healthy worker
- **AND** the frontend's `reconnectOnMount` logic and `onFinish` fallback SHALL handle the transition

### Requirement: Redis stream bridge implementation

The system SHALL implement a Redis-based stream bridge backend that stores events in Redis Streams, enabling cross-worker event delivery for multi-instance deployments. The implementation SHALL use the existing `StreamBridgeConfig` fields (`type: "redis"`, `redis_url`).

#### Scenario: Redis bridge configuration activates Redis backend

- **WHEN** `stream_bridge_config.type` is set to `"redis"` with a valid `redis_url`
- **THEN** the system SHALL use Redis Streams as the event transport instead of in-process `asyncio.Queue`

#### Scenario: Events published to Redis Stream per run

- **WHEN** an agent worker produces an event for a run
- **THEN** the event SHALL be published to a Redis Stream keyed by the run ID (e.g., `stream:{run_id}`)
- **AND** the event SHALL include a sequence number

#### Scenario: SSE consumer reads from Redis Stream

- **WHEN** an SSE endpoint receives a request for a run's stream
- **THEN** the endpoint SHALL consume events from the Redis Stream for that run ID
- **AND** support resuming from a specific sequence number for reconnection

#### Scenario: Redis bridge supports cross-worker reconnection

- **WHEN** a client reconnects to a different worker than the one handling the original stream
- **THEN** the new worker SHALL be able to read events from the Redis Stream and deliver them to the client
- **AND** the client SHALL not notice any difference compared to single-worker reconnection

### Requirement: Backpressure configuration for Redis bridge

The Redis stream bridge SHALL support the same backpressure configuration as the memory bridge, with an additional trimming policy to prevent unbounded Redis memory growth.

#### Scenario: Redis Stream maxlen trimming

- **WHEN** events are published to a Redis Stream
- **THEN** the stream SHALL be trimmed to a configurable maximum length (default: same as `queue_maxsize`, 1024)
- **AND** events exceeding the limit SHALL be trimmed from the oldest end

#### Scenario: Consumer lag detection

- **WHEN** a consumer falls behind the stream head by more than a configurable threshold
- **THEN** the system SHALL log a warning with the consumer group, run ID, and lag count
- **AND** the consumer SHALL be flagged for potential state recovery

### Requirement: Deployment topology assessment before Redis bridge priority

Before implementing the Redis stream bridge, the team SHALL assess the current deployment topology. If the production environment already runs multiple workers or multiple instances, the Redis bridge SHALL be prioritized as a short-term deliverable (not medium-term).

#### Scenario: Multi-worker deployment detected

- **WHEN** the production deployment runs 2 or more backend workers/instances
- **THEN** the Redis stream bridge SHALL be implemented before the multi-session SSE optimization is considered complete

#### Scenario: Single-worker deployment confirmed

- **WHEN** the production deployment runs a single backend worker
- **THEN** the Redis stream bridge SHALL remain a medium-term deliverable
- **AND** the memory bridge with improved backpressure SHALL be sufficient for production
