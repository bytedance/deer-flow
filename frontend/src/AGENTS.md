# Frontend source (`frontend/src/`)

`app/` holds routes, `components/workspace/` the chat UI, and `core/` the
framework-free logic (threads, messages, API client, settings). Ownership of the
model picker, chat entry pages, branch tree and browser control is described in
[conversation-ui-ownership.md](../docs/conversation-ui-ownership.md).

## Verify

```bash
cd frontend
pnpm check                       # eslint + tsc
pnpm rstest run <pattern>        # unit and happy-dom tests under tests/unit
pnpm test:e2e                    # Playwright, for anything that depends on a real browser
```

## Threads and streaming

- **Two thread identities.** A new chat has a display ID before the SDK has a
  `threadId`. Key local-turn state on the displayed conversation so that it
  survives the moment the SDK ID appears.
- **Creating a run is not retried.** Only the first `POST /runs/stream` has retries
  off, because a retry after an ambiguous failure creates a second run. Stream
  reads keep the SDK retry budget.
- **A stream gap is not the end of a run.** When the server reports a replay gap,
  reload durable state and rejoin. Do not finish the turn and do not cancel the
  backend run.
- **Do not rejoin a completed run.** Recovery for a reopened chat lists active
  runs, and that read can be stale. Run IDs that the mounted hook has seen complete
  stay excluded.
- **Unsupported stream modes fail before the request.** Forwarding part of the
  list, or defaulting to `values`, hides a caller bug.
- **Stream updates use the SDK `throttle: true` mode.** A numeric delay changes
  the trailing-debounce behaviour on a continuous stream; validate that before you
  switch.
- **No timers during render.** Streamed tool updates re-render often. Schedule
  timers in an effect with cleanup.
- **Queue and Steer.** Release a rejected attempt only after an HTTP 409 with no
  recovered receipt. After an uncertain failure keep its run, request ID and
  draft, because the server may have accepted the input.

## Messages

- **Match by message ID.** History, checkpoint and live copies of a message are
  overlaid by message ID. Provider tool-call IDs repeat across runs.
- **One message, two renderers.** A tool-calling AI message can also carry visible
  text, and a streaming text message can gain tool calls later. It is drawn by the
  processing group first and by the settled bubble afterwards, so text and
  reasoning order must be the same in both.
- **Run-scoped displays have one anchor.** Duration and workspace-change badges
  belong to a run, and a run can end in several assistant bubbles. Choose the
  anchor in `core/messages` and render it once.
- **Tool failures come from structured status.** Use `core/messages/tool-error.ts`.
  Classifying result text marks normal output as an error.
- **Exports read every persisted page.** The loaded window and the compacted
  checkpoint both omit messages.

## State and storage

- **Server state is authoritative.** `ThreadState.artifacts` is the artifact list.
  Session storage keeps panel UI state only, and an empty first stream value must
  not overwrite restored state before history loads.
- Recover `present_shared_artifact` paths from history only when all matching
  receipts confirm the same successful handoff.
- **A truncated preview is never an editing baseline.** Its ETag can equal the
  full file's. Editing and saving need the complete content.
- **Account preferences are scoped to the account.** A late response for a
  previous account is dropped, and legacy unscoped settings are never uploaded.
  Automatic model or mode resolution writes nothing to the account. Only an
  explicit user choice does.
- **Composer drafts are per tab.** New-chat pages use a stable scope because their
  runtime thread ID changes on every reload.
- **Credentials stay out of browser storage.** The session and CSRF cookies belong
  to the Gateway.

## Untrusted input

- Links in tool steps and Markdown come from the model or a provider. Pass them
  through the shared `isSafeHref` allowlist and render rejected ones with
  `UnsafeLink`.
- Knowledge sources come only from native tool artifacts. Message text and
  metadata cannot create a source. Excerpts render as plain text.
- Plugin mention IDs, imported Agent packages and uploaded names are input for the
  Gateway to validate. They grant nothing in the UI.
- Maps keyed by external strings use own properties, so `constructor` and
  `__proto__` fall back like any unknown key.

## Rendering

- Server Components by default. `app/layout.tsx` reads no cookies and imports no
  chat-only styles, so the public `/` stays static.
- Build chat paths with `core/threads/utils.ts::pathOfThread()`. It encodes agent
  names and thread IDs.
- Streaming Markdown plugins come from the shared `core/streamdown` config. Keep
  wrapper behaviour in workspace components and leave the generated AI elements
  unedited.
- The three right-hand panels share one `ResizablePanelGroup` in `chat-box.tsx`.
  A separate branch per panel loses the drag handle.
- Composer permission checks run in `InputBox.handleSubmit` after the command is
  classified and before the thread is prepared or the draft cleared.
