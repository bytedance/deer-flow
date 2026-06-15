## ADDED Requirements

### Requirement: Incremental UI block extraction during streaming

During an active stream, the system SHALL only extract UI blocks from newly arrived messages since the last extraction, not from the entire message history. Extraction SHALL be debounced at 500ms to batch rapid message arrivals.

#### Scenario: New message arrives during streaming

- **WHEN** a new assistant message arrives during streaming AND it contains `<!--ui_block:...-->` markers
- **THEN** the system SHALL send only the new message(s) to `/ui-blocks/extract` for incremental parsing
- **AND** the request SHALL be debounced so that multiple messages arriving within 500ms are batched into a single request

#### Scenario: No new messages triggers no extraction

- **WHEN** a stream event arrives that updates an existing message but does not add new messages
- **THEN** the system SHALL NOT trigger a new `/ui-blocks/extract` request

#### Scenario: Debounce cancels pending request on rapid updates

- **WHEN** multiple new messages arrive in quick succession (< 500ms apart)
- **THEN** the system SHALL cancel the pending extraction request and batch all new messages into a single request after the 500ms debounce window

### Requirement: Full extraction after stream completion

After the stream completes (`isLoading` transitions from `true` to `false`), the system SHALL perform a full `/ui-blocks/extract` call on the entire message history as a consistency check.

#### Scenario: Stream completes triggers full extraction

- **WHEN** the thread's `isLoading` state transitions from `true` to `false`
- **THEN** the system SHALL call `/ui-blocks/extract` with the complete message array
- **AND** the result SHALL replace any incrementally extracted block data
- **AND** this full extraction SHALL NOT be debounced

#### Scenario: Full extraction result matches incremental accumulation

- **WHEN** the full extraction completes
- **THEN** the resulting block list SHALL be identical to what would have been produced by accumulating all incremental extractions
- **AND** any discrepancies SHALL be resolved in favor of the full extraction result

### Requirement: GenUISSEManager integration with incremental extraction

The `GenUISSEManager` (UI block recovery SSE at `sse-recovery.ts`) SHALL be integrated with the incremental extraction system. The incremental extraction SHALL become the single source of truth for block state. `GenUISSEManager` SHALL be reduced to connection health monitoring and visibility-aware reconnection, not an independent block synchronization path.

#### Scenario: GenUISSEManager defers to incremental extraction

- **WHEN** both `GenUISSEManager.recoverBlocks()` and incremental extraction could update block state
- **THEN** incremental extraction SHALL be the authoritative source
- **AND** `GenUISSEManager` SHALL only trigger a full extraction (not directly call `replaceAllBlocks` from `/ui-blocks` endpoint)

#### Scenario: GenUISSEManager visibility-aware reconnection

- **WHEN** the page becomes hidden
- **THEN** `GenUISSEManager` SHALL suspend all reconnect attempts
- **AND** clear any pending reconnect timer

#### Scenario: GenUISSEManager resumes on page visible

- **WHEN** the page becomes visible again AND the thread has an active or recently completed run
- **THEN** `GenUISSEManager` SHALL resume health monitoring and trigger a full incremental extraction if block state is stale

### Requirement: useBlockStore adaptation for incremental mode

The `useBlockStore` (Zustand store) operations SHALL be adapted for incremental extraction mode. `replaceAllBlocks` SHALL only be called on full extraction (stream completion or recovery). During streaming, `upsertBlock` SHALL be used for incremental updates to avoid replacing the entire block state on each new message.

#### Scenario: Incremental block upsert during streaming

- **WHEN** an incremental extraction returns new blocks during streaming
- **THEN** the system SHALL call `upsertBlock` for each new/updated block
- **AND** SHALL NOT call `replaceAllBlocks` (which would discard blocks from other messages)

#### Scenario: Full replacement on stream completion

- **WHEN** a full extraction completes after stream ends
- **THEN** the system SHALL call `replaceAllBlocks` with the authoritative block list
- **AND** this SHALL be the only `replaceAllBlocks` call during the thread's lifecycle (besides recovery)

### Requirement: Incremental message grouping

Message list grouping and block assignment SHALL use incremental computation, appending new messages to existing groups rather than recomputing groups from the full message array on every change.

#### Scenario: New message appended to existing group

- **WHEN** a new message arrives that belongs to the same logical group as the last message (same agent, same turn)
- **THEN** the system SHALL append the message to the existing group without recomputing earlier groups

#### Scenario: New message starts a new group

- **WHEN** a new message arrives that starts a new logical group (different agent or new turn)
- **THEN** the system SHALL create a new group entry without modifying existing groups

#### Scenario: Message list scroll position preserved during incremental update

- **WHEN** new messages are incrementally added to the message list
- **THEN** the scroll position SHALL be preserved for users who have scrolled up to read earlier messages
- **AND** auto-scroll to bottom SHALL only trigger if the user was already at the bottom before the update

### Requirement: Background recovery UX with loading indicator and divider

When the user returns to a thread that completed (or made progress) during the background-paused period, the system SHALL display a clear visual transition: a brief loading indicator while fetching the complete state, followed by a horizontal divider labeled "以下消息在后台生成" (messages below were generated in the background) separating the pre-background messages from the newly synced messages. This provides context for why messages appeared suddenly and maintains conversational continuity.

#### Scenario: Background completion shows loading + divider

- **WHEN** the `onFinish` fallback triggers (run completed during background)
- **THEN** the system SHALL show a loading spinner for the duration of the `/threads/{id}/state` fetch
- **AND** after state sync completes, insert a divider with text "以下消息在后台生成" between the last message seen before background and the first message generated during background
- **AND** the divider SHALL fade out after 10 seconds or on next user interaction

#### Scenario: Background in-progress run resumes without divider

- **WHEN** the user returns to a thread whose run is still in progress
- **THEN** the system SHALL resume SSE consumption normally
- **AND** no divider SHALL be inserted (messages continue to stream in naturally)

### Requirement: Block history consistency across extraction modes

The block history state maintained by incremental extraction SHALL be consistent with the state produced by full extraction, ensuring that UI rendering is identical regardless of which extraction path was used.

#### Scenario: Incremental and full extraction produce same block IDs

- **WHEN** both incremental and full extraction are run on the same message set
- **THEN** the resulting `blockIdsByMessageKey` mapping SHALL be identical

#### Scenario: Block fold operations are idempotent

- **WHEN** a full extraction is performed after incremental extractions have already processed the same messages
- **THEN** the fold operations (create/update/delete) SHALL produce the same final block state as if only full extraction had been run
