## 1. Frontend Connection Lifecycle (sse-connection-lifecycle)

- [x] 1.1 Create `useDocumentVisible` hook in `frontend/src/hooks/use-document-visible.ts` using `document.visibilityState` and `visibilitychange` event
- [x] 1.2 Create `useHasActiveRun` hook in `frontend/src/core/threads/` that tracks whether a thread has an in-progress run
- [x] 1.3 Create `useStreamTier` hook in `frontend/src/core/threads/` that returns the appropriate stream mode tier (`standard`/`full`) based on current UI context (report page → `full`, else → `standard`)
- [x] 1.4 Define stream mode tier constants in `frontend/src/core/api/stream-mode.ts`: `standard` = `["messages-tuple", "updates", "custom"]` (includes `updates` to preserve SummarizationMiddleware and title sync), `full` = `["values", "messages-tuple", "updates", "custom"]`
- [x] 1.5 Modify `frontend/src/core/threads/hooks.ts` `useStream` call (line ~241): change `reconnectOnMount: true` to `reconnectOnMount: isVisible && hasActiveRun`, change `throttle: 100` to adaptive throttle — single active stream → `100ms`, multiple concurrent streams → `300ms` (detect via counting threads with `isLoading === true`)
- [x] 1.6 Add `streamMode` parameter to `useStream` call driven by `useStreamTier` hook result
- [x] 1.7 Change `streamSubgraphs` in `sendMessage` (line ~582) from hardcoded `true` to conditional: `context.mode === "ultra"` (per-run config, not per-subscription). Document that `streamSubgraphs` cannot be toggled mid-run. When mode is not `ultra`, hide the subagent detail panel entry in the UI (instead of showing a "not available" message).
- [x] 1.8 Verify whether backend actually skips `events` mode before removing `onLangChainEvent` (line ~258). **Verification steps**: (a) Start backend dev server, open browser DevTools → Network tab; (b) Send a message that triggers a tool call; (c) Filter SSE response for `event: events` lines — if no such lines appear in the SSE stream, backend skips events mode; (d) Alternatively, check `backend/packages/harness/deerflow/agents/` for where `stream_mode` is passed to `client.runs.stream()` and verify `events` is not in the list. If confirmed skipped, remove handler and add `tool_end` handling in `onCustomEvent`. If not skipped, preserve handler and add `tool_end` as redundant channel.
- [x] 1.9 Add `GenUISSEManager` visibility awareness in `frontend/src/core/genui/sse-recovery.ts`: suspend `recoverBlocks()` and `scheduleReconnect()` when `document.visibilityState === "hidden"`, resume on visible
- [x] 1.10 Add `onFinish` pause/resume fallback in `hooks.ts`: when `useDocumentVisible` transitions from `false` to `true`, check `thread.status`. If terminal (`completed`/`error`) but `onFinish` was not triggered, fetch `/threads/{id}/state` and execute `onFinish`-equivalent logic (appendMessages, invalidateQueries)
- [x] 1.11 Add unit tests for `useDocumentVisible`, `useHasActiveRun`, and `useStreamTier` hooks
- [x] 1.12 Add unit tests for stream mode tier selection logic in `stream-mode.test.ts`
- [x] 1.13 Add unit test for `onFinish` fallback: simulate background-paused run completion, verify state fetch and finalization on return

## 2. GenUI Incremental Extraction (genui-incremental-extract)

- [x] 2.0 Add `upsertBlock(id, block)` method to `useBlockStore` in `frontend/src/core/genui/store.ts` (currently only has `replaceAllBlocks` and `updateBlockProps`). The new method SHALL insert a new block or update an existing one by ID without affecting other blocks. This is a prerequisite for task 2.5.
- [x] 2.1 Create `extractBlocksIncremental` function in `frontend/src/core/genui/history.ts` that sends only new messages to `/ui-blocks/extract`
- [x] 2.2 Create `useUIBlockExtractor` hook in `frontend/src/core/genui/` that manages incremental extraction during streaming (500ms debounce) and full extraction on stream completion
- [x] 2.3 Refactor existing full-extraction logic in `history.ts` to be called only on stream completion (`isLoading` transition `true` → `false`)
- [x] 2.4 Integrate `GenUISSEManager` with incremental extraction: `GenUISSEManager` SHALL defer to incremental extraction as the single source of truth for block state. Replace direct `replaceAllBlocks` from `/ui-blocks` endpoint with triggering a full incremental extraction.
- [x] 2.5 Adapt `useBlockStore` (Zustand) for incremental mode: use `upsertBlock` during streaming for incremental updates, reserve `replaceAllBlocks` for full extraction only (stream completion or recovery)
- [x] 2.6 Implement incremental message grouping in message list component: change `groupedMessages` `useMemo` (line ~376) from full recomputation to incremental append pattern using `useRef` for accumulated groups
- [x] 2.7 Ensure scroll position is preserved during incremental message updates; auto-scroll to bottom only if user was already at bottom
- [x] 2.8 Add snapshot tests verifying incremental extraction produces identical block IDs as full extraction
- [x] 2.9 Add tests for message grouping incremental update (append to existing group vs. create new group)
- [x] 2.10 Add tests for `useBlockStore` incremental mode: verify `upsertBlock` during streaming, `replaceAllBlocks` only on full extraction

## 3. Backend Stream Event Compaction (stream-event-compaction)

- [x] 3.1 Create `StatePatchEmitMiddleware` in `backend/packages/harness/deerflow/agents/middlewares/state_patch_emit_middleware.py`: in `after_model`/`aafter_model`, detect state diff fields (`title`, `todos`, `artifacts`) and emit `{"type": "state_patch", "patch": {...}}` via `get_stream_writer()`. Return empty dict (no state modification).
- [x] 3.2 Register `StatePatchEmitMiddleware` in the middleware chain (after `TitleMiddleware`, `TodoListMiddleware`, and artifact-producing middleware). Ensure it runs after state-modifying middleware so it can observe their diffs.
- [x] 3.3 Add `tool_end` custom event emission in the tool execution layer: after each tool completes, emit `{"type": "tool_end", "name": "<tool_name>", "data": {"status": "success|error", ...summary}}` via `get_stream_writer()`. Summary must be under 500 bytes. Implemented as `ToolEndEmitMiddleware` using `awrap_tool_call` hook, placed after `ToolErrorHandlingMiddleware` in the chain.
- [x] 3.4 Update frontend `onCustomEvent` handler in `hooks.ts` to process `state_patch` events: merge patch into TanStack Query cache for the current thread. Ensure idempotency with `onUpdateEvent` (last write wins for same field).
- [x] 3.5 Add frontend sequence number tracking: maintain `lastSequenceNumber` per run, detect gaps in `onCustomEvent`/`onUpdateEvent`/`onValueEvent`, trigger `/threads/{id}/state` fetch on gap detection. No periodic polling.
- [x] 3.6 Add backend tests for `StatePatchEmitMiddleware`: verify it emits `state_patch` for title/todos/artifacts changes and emits nothing for other state diffs
- [x] 3.7 Add backend tests for `tool_end` event emission: verify all tool execution paths emit the event
- [x] 3.8 Add frontend tests for `state_patch` idempotency: verify `onCustomEvent` and `onUpdateEvent` both updating title doesn't cause duplication

## 4. Stream Bridge Multi-Instance (stream-bridge-multi-instance)

- [x] 4.1 Raise `queue_maxsize` default from 256 to 1024 in `backend/packages/harness/deerflow/config/stream_bridge_config.py`
- [x] 4.2 Add sequence number field to stream bridge events: each event produced by a run gets a monotonically increasing sequence number
- [x] 4.3 Implement merge-drop backpressure policy in memory stream bridge: for `messages-tuple` token events of the same message, drop intermediate tokens (keep first + latest); for other event types, FIFO drop oldest. Worker is never blocked.
- [x] 4.4 Include sequence number in SSE event payload sent to frontend
- [x] 4.5 Add Nginx configuration for sticky session in `docker/nginx/nginx.conf` and `docker/nginx/nginx.local.conf`: consistent hash based on `thread_id` to route same-thread requests to same worker
- [x] 4.6 Verify Nginx `proxy_read_timeout` ≥ 300s for SSE endpoints
- [x] 4.7 Verify HTTP/2 is enabled between browser and Nginx
- [x] 4.8 Assess current deployment topology: confirm whether production runs single-worker or multi-worker. If multi-worker, escalate Redis bridge priority to short-term.
- [x] 4.9 Add backend tests for merge-drop backpressure behavior: queue-full with token events drops intermediates, sequence numbers remain monotonic
- [x] 4.10 Add frontend tests for sequence gap detection and state fetch recovery flow

## 5. Empathetic Error Handling Adaptation

- [x] 5.1 Add background-paused state tracking in thread hooks: when a thread's SSE is suspended due to tab invisibility, mark it as `backgroundPaused`
- [x] 5.2 Modify error display logic: errors on `backgroundPaused` threads SHALL NOT trigger toast notifications; instead, record errors in thread error state
- [x] 5.3 Surface accumulated background errors inline when user returns to the thread: display in message list with empathetic message and retry option
- [x] 5.4 Integrate `onFinish` fallback (from task 1.10) with error handling: if run ended with error during background, display error inline (not toast) on return
- [x] 5.5 Add tests for background error suppression (no toast) and surfacing on return (inline display)
- [x] 5.6 Add tests for `onFinish` fallback with error scenario: verify error is displayed inline, not as toast

## 6. Redis Stream Bridge (Medium-term or Short-term per 4.8)

- [x] 6.1 Implement Redis stream bridge backend in `backend/packages/harness/deerflow/runtime/`: publish events to Redis Stream keyed by run ID
- [x] 6.2 Implement Redis Stream consumer for SSE endpoints: read events from Redis Stream, support resuming from specific sequence number
- [x] 6.3 Add `MAXLEN` trimming to Redis Streams (default: 1024, matching `queue_maxsize`)
- [x] 6.4 Add consumer lag detection and warning logging for Redis bridge
- [x] 6.5 Add integration tests for Redis bridge: cross-worker reconnection, event delivery, trimming

## 7. Per-Phase Automated Smoke Tests

- [x] 7.1 Create smoke test script that simulates 5 concurrent threads with active runs and measures: active SSE connection count (expect ≤ 2 for visible), `/ui-blocks/extract` call count during streaming (expect O(1) after phase 2), main thread Long Task count via Performance Observer
- [ ] 7.2 Run smoke test after phase 1 completion: verify SSE connections and throttle behavior
- [ ] 7.3 Run smoke test after phase 2 completion: verify `/ui-blocks/extract` reduction and message grouping
- [ ] 7.4 Run smoke test after phase 3 completion: verify SSE payload size < 2KB for standard tier, `state_patch` delivery
- [ ] 7.5 Run smoke test after phase 4 completion: verify backpressure behavior and sequence gap recovery

## 8. Final Verification

- [x] 8.1 Add frontend performance metrics collection: active SSE count (including `GenUISSEManager`), `/ui-blocks/extract` call frequency, main thread Long Task count via Performance Observer
- [x] 8.2 Add backend SSE event size metrics: average event payload size per stream mode tier
- [x] 8.3 Add stream bridge queue size gauge metric for monitoring backpressure
- [ ] 8.4 Run full manual verification: open 3-5 concurrent sessions, verify active SSE count ≤ visible sessions x 2 (LangGraph + GenUISSEManager), verify no persistent Long Tasks in background tabs
- [ ] 8.5 Verify `onFinish` fallback: background a tab with active run, wait for run to complete, return and verify state sync within 2s
- [ ] 8.6 Verify long-session SSE payload size stays under 2KB average for standard tier

## 9. User Communication & Rollout

- [x] 9.1 Prepare user-facing changelog entry describing: improved multi-tab performance, background tab optimization, reduced memory usage. No action required from users.
- [ ] 9.2 Add in-app tooltip or release note for report-generation users: report pages continue to use full stream modes (`values` included), no behavior change for report scenarios.
- [ ] 9.3 Coordinate with customer support: brief FAQ on potential user-reported observations (e.g., "messages appear after a short delay when switching back to a background tab — this is expected, data is being synced")
- [x] 9.4 Define rollback plan: each phase is independently deployable. If phase N causes issues, it can be disabled via feature flag without affecting phases 1 to N-1.
