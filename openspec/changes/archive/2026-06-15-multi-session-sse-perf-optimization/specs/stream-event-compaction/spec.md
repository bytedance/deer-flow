## ADDED Requirements

### Requirement: Unified StatePatchEmitMiddleware with instance-level state comparison

A new `StatePatchEmitMiddleware` SHALL be created and inserted at the end of the middleware chain (after `TitleMiddleware`, `TodoListMiddleware`, and artifact-producing middleware). It SHALL use instance-level `_last_emitted` state comparison to detect changes: in `after_model`/`aafter_model`, it SHALL read the current absolute values of `title`, `todos`, and `artifacts` from the state, compare each against the `_last_emitted` cache, and emit `state_patch` custom events via `get_stream_writer()` for any changed fields. The middleware SHALL return an empty dict (no state modification). The `_last_emitted` cache SHALL be updated after each emission.

This approach is necessary because LangGraph middleware's `after_model` receives pre-merge state and cannot directly observe other middleware's diffs. By reading absolute field values at the end of the chain (after all state-modifying middleware have executed), the middleware can detect changes across invocations.

#### Scenario: Title update pushes patch via custom event

- **WHEN** `TitleMiddleware` has updated the title AND `StatePatchEmitMiddleware.after_model` reads a `title` value different from `_last_emitted["title"]`
- **THEN** `StatePatchEmitMiddleware` SHALL emit `{"type": "state_patch", "patch": {"title": "<new_title>"}}` via `get_stream_writer()`
- **AND** update `_last_emitted["title"]` to the new value
- **AND** the event payload SHALL be less than 1KB

#### Scenario: Todos update pushes patch via custom event

- **WHEN** `TodoListMiddleware` returns a state diff containing updated `todos`
- **THEN** `StatePatchEmitMiddleware` SHALL emit `{"type": "state_patch", "patch": {"todos": [...]}}` via `get_stream_writer()`

#### Scenario: Artifacts update pushes patch via custom event

- **WHEN** a tool produces new artifacts and the state diff contains updated `artifacts`
- **THEN** `StatePatchEmitMiddleware` SHALL emit `{"type": "state_patch", "patch": {"artifacts": [...]}}` via `get_stream_writer()`

#### Scenario: No relevant state change emits nothing

- **WHEN** a middleware returns a state diff that does not contain `title`, `todos`, or `artifacts`
- **THEN** `StatePatchEmitMiddleware` SHALL NOT emit any `state_patch` event

### Requirement: Frontend applies state_patch to local cache with idempotency

The frontend SHALL handle `state_patch` custom events in `onCustomEvent` by merging the patch into the local thread state cache. The handler SHALL be idempotent — if the same field is also updated via `onUpdateEvent` (updates mode) or `values` mode, the last write wins without duplication.

#### Scenario: state_patch updates thread title in sidebar

- **WHEN** the frontend receives a `state_patch` event with `{"patch": {"title": "New Title"}}`
- **THEN** the frontend SHALL update the thread's title in TanStack Query cache immediately
- **AND** the sidebar thread list SHALL reflect the new title without a page refetch

#### Scenario: state_patch and onUpdateEvent both carry title update

- **WHEN** both a `state_patch` custom event and an `updates` event carry a title change for the same thread
- **THEN** the frontend SHALL apply both updates idempotently
- **AND** the final title value SHALL be whichever arrived last (no duplication or conflict)

### Requirement: tool_end custom event for tool execution tracking

The backend SHALL emit `tool_end` custom events via `get_stream_writer()` after each tool completes execution, containing the tool name and a summary of the output (not the full output).

#### Scenario: Tool completion emits custom event

- **WHEN** any tool in the agent pipeline completes execution
- **THEN** the backend SHALL emit `{"type": "tool_end", "name": "<tool_name>", "data": <summary>}` via `get_stream_writer()`
- **AND** the summary SHALL include success/failure status and a brief description (under 500 bytes)

#### Scenario: Tool failure includes error category

- **WHEN** a tool execution fails
- **THEN** the `tool_end` event SHALL include `{"type": "tool_end", "name": "<tool_name>", "data": {"status": "error", "error_category": "<category>", "message": "<brief>"}}`

### Requirement: Stream mode values fallback preservation

The backend SHALL preserve the ability to push full `values` snapshots when the frontend subscribes to the `values` stream mode (full tier). This ensures backward compatibility during the transition period. The `StatePatchEmitMiddleware` operates independently — its custom events are emitted regardless of which stream modes the frontend subscribes to.

#### Scenario: Full tier still receives values events

- **WHEN** the frontend subscribes with `streamMode: ["values", "messages-tuple", "updates", "custom"]`
- **THEN** the backend SHALL continue to push full state values events as before
- **AND** `state_patch` custom events SHALL also be pushed alongside values events

#### Scenario: Standard tier does not receive values events

- **WHEN** the frontend subscribes with `streamMode: ["messages-tuple", "updates", "custom"]`
- **THEN** the backend SHALL NOT push `values` events
- **AND** the frontend SHALL rely on `state_patch` custom events (and `onUpdateEvent` for title) for UI state updates

### Requirement: Gap-triggered state consistency polling

The frontend SHALL poll `/threads/{id}/state` for consistency recovery ONLY when a sequence number gap is detected in the SSE event stream. There SHALL be no periodic time-based polling under normal operation.

#### Scenario: Sequence gap triggers state fetch

- **WHEN** the frontend receives an SSE event with a sequence number that is more than 1 greater than the last received sequence number for the same run
- **THEN** the frontend SHALL fetch the full thread state via `/threads/{id}/state`
- **AND** reconcile the local state with the fetched state
- **AND** resume normal SSE consumption from the next event

#### Scenario: No gap means no polling

- **WHEN** all SSE events arrive with contiguous sequence numbers
- **THEN** the frontend SHALL NOT poll `/threads/{id}/state` at all
