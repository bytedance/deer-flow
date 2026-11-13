# Subagents (`deerflow/subagents/`)

Runs delegated work for the lead agent. `task` starts one in-memory subagent and
waits for it. `batch_task` writes durable rows that a lease-based batch service
executes, in the Gateway or in a separate worker. This directory also owns the
subagent registry, capacity limits, the report contract and the acceptance checks
that verify a subagent's claims. Batch behaviour and ownership:
[BATCH_CONTINUATION.md](../../../../docs/BATCH_CONTINUATION.md).

## Verify

```bash
cd backend
python -m pytest tests -q -k "subagent or batch or acceptance"
make test-blocking-io
```

Batch and result-reader tests run against SQLite and, when `TEST_POSTGRES_URI` is
set, against an isolated PostgreSQL schema. They need no paid model.

Run input delivery and parent context snapshots share `SUBAGENT_RESULT_MESSAGE_NAME`
from `deerflow.utils.messages`. Keep delayed Steer reports as sanitized history.

## Terminal state

- **The first terminal write wins.** Cancellation, timeout and completion race.
  A late cancellation must not replace a recorded timeout, and a cancelled or
  stale attempt must not publish a result or evidence.
- **Clean up before you notify.** Stream cleanup and the final usage snapshot come
  before the terminal notification, because callbacks can arrive before the last
  values chunk.
- **Drain cleanup under cancellation.** Releasing a capacity slot, removing a
  queued waiter and stopping the runtime all finish even when the caller is
  cancelled again while they run. A slot that is not released stays lost until
  restart.
- **Caps are not a new status.** A token, turn or loop cap is reported through the
  additive `stop_reason` field. A capped run with a usable answer stays
  `completed`, so existing consumers of the status enum keep working.
- **A handled model failure is still a failure.** The error-handling middleware
  turns a provider exception into a normal message so that the graph ends cleanly.
  Read its marker in `additional_kwargs` to decide the task status; do not read the
  message text.

## Durable batches

- **One execution lease per item.** The worker heartbeat covers tool assembly,
  execution and acceptance. Every write checks the lease owner and the active
  status in SQL, so a worker that lost its lease cannot write.
- **Persist data, never live capabilities.** A batch spec stores JSON that a
  different process restores after lease recovery: prompt overlays, knowledge
  scope, acceptance criteria. A malformed stored scope fails the item; it does not
  fall back to a wider scope.
- **Item positions are the submission order** and never change. Readers check the
  owner and the current thread before they return any field.
- **Take PostgreSQL locks parent first**, then item, to keep the lock order
  consistent between workers.

## Isolation from the parent

- **Apply name policies to middleware tools after assembly**, even without global
  authorization. Preserve shared middleware and allowed callables; require
  Sequence declarations and reject one-shot iterators unconsumed. Discovery
  helpers keep filtered catalogs; provider validation remains independent.
- **Audit immediately before `create_agent`.** Check explicit and middleware
  tools, failing on unexpected names rather than silently re-filtering. Exempt
  only actual generated discovery helpers in the explicit list, never name
  matches or middleware tools. Reuse callable name conversion within this build;
  recheck new or renamed tools. Errors identify `disallowed_tools` hits or missing
  `tools` allowlist entries; denylists win.
- **A subagent inherits scope, not state.** It gets the parent's identity, the
  user's skill storage, the knowledge execution scope and a deep copy of the
  uploaded-file list at dispatch. It does not share the parent's message history.
- **Thinking settings do not inherit.** A subagent's reasoning settings come from
  its own definition. Unset means off, not "same as the parent".
- **Registry overrides copy.** Resolution order is built-in, then
  `config.yaml custom_agents`, then enabled admin-managed definitions, then
  explicit per-agent overrides. An override must not mutate `BUILTIN_SUBAGENTS`.
- **Sandbox use is leased.** An admitted subagent carries a stable lease owner ID
  and command scope ID derived from its task, so the shared sandbox can stop only
  that subagent's processes.
- **All native subagents share one persistent event loop.** Keep loop and thread
  ownership until the worker has stopped. A bounded join does not prove that it
  stopped.
- **Delegation is not the default.** The routing policy permits `task` only when
  parallel latency, a specialist skill or context isolation clearly outweighs the
  startup cost and the duplicated discovery.

## Evidence and acceptance

- **Acceptance is decided in code.** The lead supplies acceptance criteria and
  `acceptance_checks.py` evaluates them against recorded tool results. The
  subagent's own report cannot mark a criterion as met.
- **Unverified is the safe result.** Missing criteria, a checker error, a legacy
  row or a failed execution is never treated as accepted. A path the caller may
  not read stays unverified.
- **A build banner is not a test result.** "Tests passed" needs a complete count
  summary from the test runner with at least one test that ran. Failure counters
  win over pass counters. Keep this rule when you add a runner format.
- **Pair results by message, not by call ID alone.** Providers reuse tool-call
  IDs. A call without an ID records no evidence.
- **Classify the full output before you shorten it.** The test summary is computed
  from the complete tool message and stored. The tail kept for display can cut the
  line that carries the result.
- **Authorize before you read.** File criteria pass the same owner-scoped path
  checks and sandbox authorization as the file tools, and blocking reads are
  drained before the lease is released.
- **Knowledge sources survive compaction.** Sources from validated tool messages
  accumulate on the result and are published before the terminal state.
