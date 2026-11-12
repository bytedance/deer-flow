# Gateway API (`app/gateway/`)

The FastAPI application on port 8001. It serves the REST API, embeds the
LangGraph-compatible agent runtime, and owns auth, CSRF, run admission and thread
lifecycle. Route-level rules are in [routers/AGENTS.md](routers/AGENTS.md). The
endpoint list is the OpenAPI schema at `/docs`; [API.md](../../docs/API.md)
describes it for humans.

## Verify

```bash
cd backend
python -m pytest tests -q -k "gateway or router or auth or run_manager"
make test-blocking-io     # request handlers share one event loop
```

Read these contracts before you change the matching area:
[thread lifecycle](../../docs/THREAD_LIFECYCLE.md) (branch, regenerate, edit
replay, archive), [run event stream](../../docs/RUN_EVENT_STREAM.md),
[run interaction policy](../../docs/RUN_INTERACTION_POLICY.md),
[auth design](../../docs/AUTH_DESIGN.md), [knowledge](../../docs/KNOWLEDGE.md).

## Trust boundary

- **Server-owned run context.** A client can send run context in `body.context`
  and in `body.config`. Admit server-owned keys only from internally authenticated
  callers and strip them from both places for everyone else. When you add a
  server-owned key, add it to that strip list in the same change.
- **Server-owned state.** Reject thread state fields that only the server may write
  (sandbox, thread data, viewed images, goal outcome) and reserved metadata keys
  when they come from a client. External run input cannot carry system or developer
  messages.
- **Owner scoping.** Run-history helpers default to the request user and fail
  closed when there is no user context. Pass `user_id=None` only in migration or
  admin code that needs an unscoped read, and say why at the call site.
- **Thread IDs become paths.** Validate every caller-provided thread ID with
  `deerflow.utils.thread_id` before it reaches persistence or the filesystem.
  Legacy IDs stay readable and deletable, but they are never interpolated into a
  host path.
- **Shared decisions.** Route permissions, model use and skill visibility are each
  decided in one helper in `authz.py`. HTTP routes, decorator-only auth and the
  Live Browser WebSocket all call it. A new entry point calls the same helper so
  that it cannot drift from the others.
- **Tokens and cookies.** A request with an invalid Bearer token gets 401 and never
  falls back to the session cookie; the CSRF middleware skips Bearer requests and
  relies on this. Personal access tokens work only on allowlisted routes.
- **Proxy headers.** "Is this localhost" decisions use the direct `Host` header.
  Forwarded headers are client-controlled unless the outer proxy replaces them.
- **Untrusted remote text.** MCP notifications and other remote events reach the
  model framed as untrusted data, outside the trusted instruction.

## Runs and threads

- **One writer per thread.** A run, a checkpoint write, an artifact write, a branch
  and a delete are all thread operations that share one durable uniqueness
  constraint. Reserve through `RunManager.reserve_thread_operation()` or
  `services.reserve_checkpoint_write()`. A separate lock would let two workers
  write the same thread.
- **Several workers.** In-memory run records exist only on the worker that owns the
  run. Cancel, takeover and orphan recovery are compare-and-set operations on the
  run store; use the store's claim and cancel primitives so that a lease renewal
  between your read and your write is not overwritten. Multi-worker deployments
  need `run_events.backend: db`.
- **Idempotency keys.** Scope an external `Idempotency-Key` to its owner and thread
  before it reaches `RunManager`; the manager's index is process-wide.
- **`/wait` on a reused run** returns the durable run status and error. The latest
  thread checkpoint can belong to a different run.
- **Stream gaps.** Stream bridges keep a bounded buffer. A client that asks for
  events older than the buffer receives a `gap` event and the run continues.
- **`Content-Location` must stay CORS-exposed.** Run-creating routes return the run
  ID in that header and the LangGraph SDK reads it from there only.
- **Run event contract.** Producer code, `deerflow/constants.py`, the event
  catalog, `contracts/run_event_stream_contract.json` and
  `docs/RUN_EVENT_STREAM.md` change together.
- **Thread membership in a project** is written by thread creation, branching and
  the explicit move route. Run admission reads it and never changes it.

## Lifecycle

- **Probe file-backed managed subagent storage once during startup, off the
  event loop.** Probe failures warn operators before their first create request;
  atomic create stays fail-closed rather than falling back to an overwrite.
- **Shutdown order matters.** `lifespan` drains runs and extensions first, then
  closes MCP, then shuts the sandbox provider down off the event loop. Cleanup code
  keeps running after cancellation, allocates nothing new, and logs failures
  instead of raising.
- **Persistent writes in routers** go through
  `app.gateway.persistent_writes.run_drained_write` so that a client disconnect
  cannot leave a half-written file.
- **LangGraph Studio.** `langgraph_studio.py` is loaded by LangGraph's file loader
  before the runtime starts and without a `sys.modules` entry. Keep its
  annotations eager, and identify Studio callers by the upstream `StudioUser`
  type, because the identity string can be reused by any client.
