## Purpose

Redis-based leader election for IM channels in multi-worker deployments. Ensures only one worker process actively consumes messages per channel (Feishu, WeChat, WeCom, DingTalk, Telegram, Slack, Discord), with webhook deduplication for webhook-based channels.

## Requirements

### Requirement: Redis-based leader election for IM channels

Each IM channel (Feishu, WeChat, WeCom, DingTalk, Telegram, Slack, Discord) SHALL use a Redis distributed lock to ensure that only one worker process actively consumes messages at any time. The lock key SHALL be `deerflow:im_lock:{channel_name}`.

#### Scenario: Single active consumer per channel

- **WHEN** three workers start and all attempt to consume Feishu messages
- **THEN** exactly one worker SHALL acquire the lock `deerflow:im_lock:feishu`
- **AND** the other two workers SHALL skip Feishu consumption until the lock is released

#### Scenario: Lock holder crashes

- **WHEN** the worker holding the Feishu lock crashes
- **THEN** the lock SHALL expire after its TTL (default: 30 seconds)
- **AND** another worker SHALL acquire the lock within the next poll cycle (default: 10 seconds)

### Requirement: Atomic lock operations via Lua scripts

All lock operations (acquire, renew, release) SHALL use Redis Lua scripts to ensure atomicity and prevent race conditions.

#### Scenario: Lock renewal verifies ownership

- **WHEN** a worker holds the Feishu lock with TTL=30s
- **AND** the lock expires due to GC pause
- **AND** another worker acquires the lock
- **AND** the original worker attempts to renew
- **THEN** the Lua script SHALL check that the current value matches the worker's ID
- **AND** SHALL NOT renew (the lock now belongs to another worker)
- **AND** SHALL return 0 indicating the lock was lost

#### Scenario: Lock release verifies ownership

- **WHEN** a worker calls release on a lock it no longer holds
- **THEN** the Lua script SHALL check the value matches
- **AND** SHALL NOT delete the lock (it belongs to another worker)

#### Scenario: Lock acquisition is atomic

- **WHEN** two workers attempt to acquire the same lock simultaneously
- **THEN** exactly one SHALL succeed via atomic `SET NX EX`
- **AND** the other SHALL get nil

### Requirement: Graceful shutdown releases lock

When a worker shuts down gracefully (SIGTERM), it SHALL release all IM channel locks it holds before exiting.

#### Scenario: Graceful shutdown

- **WHEN** a worker holding the Feishu lock receives SIGTERM
- **THEN** the worker SHALL execute the release Lua script for `deerflow:im_lock:feishu`
- **AND** another worker SHALL be able to acquire the lock immediately

### Requirement: Channel coordination configuration

IM channel coordination SHALL be controlled by `im.coordination_mode` (overridden by multi-worker mode):

- `redis` (multi-worker mode default): use Redis Lua script distributed lock
- `none` (single-worker default): each worker consumes independently (existing behavior)

#### Scenario: Redis coordination mode

- **WHEN** `im.coordination_mode` is `"redis"`
- **THEN** each IM channel SHALL participate in leader election via Redis Lua script lock

#### Scenario: No coordination in single-worker mode

- **WHEN** `im.coordination_mode` is `"none"`
- **THEN** each worker SHALL consume from all IM channels independently (existing behavior)

### Requirement: Webhook deduplication

For webhook-based channels (Feishu, DingTalk), the system SHALL deduplicate incoming webhooks using a Redis key `deerflow:webhook_dedup:{channel}:{message_id}` with configurable TTL (default: 300 seconds). Duplicate webhooks (same message_id within TTL) SHALL be acknowledged but not processed.

#### Scenario: Duplicate webhook ignored

- **WHEN** worker receives a Feishu webhook with message_id "msg-123"
- **AND** another worker already processed a webhook with the same message_id within the last 300 seconds
- **THEN** the system SHALL return HTTP 200 to the sender
- **AND** SHALL NOT process the message again

#### Scenario: Webhook after TTL expiry

- **WHEN** a webhook with message_id "msg-123" is received
- **AND** the last processing was more than 300 seconds ago
- **THEN** the system SHALL process the webhook normally (TTL expired, not a duplicate)
