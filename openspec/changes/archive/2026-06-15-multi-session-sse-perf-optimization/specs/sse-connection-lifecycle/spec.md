## ADDED Requirements

### Requirement: Page Visibility-based reconnection

The system SHALL only maintain full SSE stream connections for threads that are both (a) on the currently visible page/tab and (b) have an active (in-progress) run. Background tabs and threads without active runs SHALL NOT maintain persistent SSE connections. Both `useStream` (LangGraph SDK SSE) and `GenUISSEManager` (UI block recovery SSE) SHALL be visibility-aware.

#### Scenario: Active visible thread maintains SSE

- **WHEN** a thread has an in-progress run AND its page is visible (`document.visibilityState === "visible"`)
- **THEN** the system SHALL maintain both the LangGraph SDK SSE connection and the `GenUISSEManager` recovery connection

#### Scenario: Background tab suspends all SSE consumption

- **WHEN** the user switches to a different browser tab
- **THEN** the system SHALL pause SSE event consumption for `useStream` AND suspend `GenUISSEManager.recoverBlocks()` / `scheduleReconnect()` for all threads on the now-hidden page within 1 second

#### Scenario: Return to background tab resumes with state sync

- **WHEN** the user returns to a previously backgrounded tab that has an in-progress run
- **THEN** the system SHALL resume SSE consumption and fetch the latest thread state via `fetchStateHistory` to fill any gaps incurred during the paused period

#### Scenario: Thread with no active run does not reconnect

- **WHEN** a thread's last run has completed or failed AND the user navigates to that thread's page
- **THEN** the system SHALL NOT establish an SSE connection

#### Scenario: GenUISSEManager pauses in background

- **WHEN** the page becomes hidden AND `GenUISSEManager` has a pending reconnect timer
- **THEN** the system SHALL clear the reconnect timer and suspend recovery attempts until the page becomes visible again

### Requirement: Stream mode tier selection with updates preserved

The system SHALL select stream mode subscription based on the current UI context, using two predefined tiers: `standard` and `full`. The `standard` tier SHALL include `updates` mode to preserve `onUpdateEvent` functionality (SummarizationMiddleware message migration and title sidebar sync).

#### Scenario: Standard chat uses stream modes without values

- **WHEN** the user is on a normal chat page (including subagent panel open)
- **THEN** the system SHALL subscribe to `["messages-tuple", "updates", "custom"]` stream modes
- **AND** SHALL NOT subscribe to `values` mode

#### Scenario: Report generation uses full stream modes

- **WHEN** the user is on a report generation page or template preview
- **THEN** the system SHALL subscribe to `["values", "messages-tuple", "updates", "custom"]` stream modes

#### Scenario: SummarizationMiddleware message migration continues working

- **WHEN** the system is on `standard` tier AND a SummarizationMiddleware event arrives via `updates` mode
- **THEN** the `onUpdateEvent` handler SHALL process the event and migrate messages as before

#### Scenario: Tier switches during active stream

- **WHEN** the user navigates from a chat page to a report page while a stream is active
- **THEN** the system SHALL update the stream mode on the next reconnection cycle without interrupting the current run

### Requirement: Adaptive throttle for multi-stream scenarios

The system SHALL use an adaptive throttle interval for `useStream` based on the number of concurrently active streams. When only one thread is actively streaming, the throttle interval SHALL be 100ms (matching current single-session responsiveness). When multiple threads are simultaneously streaming, the throttle interval SHALL increase to 300ms per stream, reducing main thread pressure during multi-session scenarios.

#### Scenario: Single active stream uses responsive throttle

- **WHEN** only one thread has `isLoading === true`
- **THEN** the throttle interval for that stream SHALL be 100ms

#### Scenario: Multiple concurrent streams use conservative throttle

- **WHEN** two or more threads have `isLoading === true` simultaneously
- **THEN** each active stream SHALL apply a 300ms throttle independently
- **AND** the system SHALL NOT trigger main thread Long Tasks from SSE event processing

### Requirement: onLangChainEvent verification before removal

The system SHALL verify whether the backend actually skips `events` mode before removing the `onLangChainEvent` handler. If the backend does emit events mode data, the handler SHALL be preserved. If not, tool end notifications SHALL be received via `onCustomEvent` with a `tool_end` event type instead.

#### Scenario: Backend confirmed to skip events mode

- **WHEN** verification confirms the backend does not push `events` mode data
- **THEN** the `onLangChainEvent` handler SHALL be removed
- **AND** tool end notifications SHALL be handled via `onCustomEvent` with `tool_end` events

#### Scenario: Backend confirmed to emit events mode

- **WHEN** verification confirms the backend does push `events` mode data
- **THEN** the `onLangChainEvent` handler SHALL be preserved
- **AND** `tool_end` custom events SHALL also be added as a redundant channel

### Requirement: streamSubgraphs per-run configuration

The system SHALL set `streamSubgraphs` as a per-run configuration at message submission time, based on the agent mode. It SHALL NOT attempt to dynamically switch `streamSubgraphs` based on UI panel state during an active run.

#### Scenario: Ultra mode enables streamSubgraphs at submission

- **WHEN** the user submits a message with agent mode set to `ultra` (subagents enabled)
- **THEN** `streamSubgraphs` SHALL be `true` in the `client.runs.stream()` call

#### Scenario: Non-ultra mode disables streamSubgraphs at submission

- **WHEN** the user submits a message with agent mode set to `pro`, `thinking`, or `flash`
- **THEN** `streamSubgraphs` SHALL be `false` in the `client.runs.stream()` call

#### Scenario: streamSubgraphs cannot be toggled mid-run

- **WHEN** a run is started with `streamSubgraphs: false` AND the user later opens the subagent detail panel
- **THEN** the system SHALL NOT attempt to enable `streamSubgraphs` for the in-progress run
- **AND** the system SHALL hide the subagent detail panel entry in the UI (rather than showing a "not available" message)

### Requirement: onFinish pause/resume fallback

The system SHALL detect when `onFinish` was not triggered during a background-paused period and execute equivalent finalization logic upon the user returning to the thread.

#### Scenario: Run completes while tab is backgrounded

- **WHEN** the user returns to a tab where the thread's run completed during the background period
- **AND** `onFinish` was not triggered (because SSE was paused)
- **THEN** the system SHALL detect `thread.status === "completed"` (or `"error"`) within 2 seconds of the page becoming visible
- **AND** fetch the complete thread state via `/threads/{id}/state`
- **AND** execute `onFinish`-equivalent logic: `appendMessages` from fetched state, `invalidateQueries` for sidebar refresh

#### Scenario: Run still in progress when tab returns

- **WHEN** the user returns to a tab where the thread's run is still in progress
- **THEN** the system SHALL resume SSE consumption normally
- **AND** `onFinish` SHALL fire naturally when the run completes
