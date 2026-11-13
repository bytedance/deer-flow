# Subagents (`deerflow/subagents/`)

Owns in-memory `task` execution, durable `batch_task`, registries, capacity,
reports and acceptance checks. For Gateway and standalone batch workers, see
[BATCH_CONTINUATION.md](../../../../docs/BATCH_CONTINUATION.md).

## Verify

```bash
cd backend
python -m pytest tests -q -k "subagent or batch or acceptance"
make test-blocking-io
```

Batch and result-reader tests use SQLite or, with `TEST_POSTGRES_URI`, an isolated
PostgreSQL schema. No paid model is needed.

## Terminal state

- **The first terminal write wins.** Reject later cancellations and
  result/evidence writes from cancelled or stale attempts.
- **Deliver hard timeouts before cleanup.** Consumers can return while teardown
  still fences capacity, sandbox leases and normal registry removal.
- **Drain cleanup under repeated cancellation.** Release capacity, remove queued
  waiters and shut down the runtime. Leaked slots persist until restart.
- **Return usable capped results as `completed`.** Record token, turn and loop
  caps in `stop_reason` for compatibility.
- **Detect handled model failures by their `additional_kwargs` marker.**
  Middleware turns provider exceptions into normal messages to end the graph.

## Ordinary task notifications

Publish revisions and detach waiters under the `SubagentResult` lock. Recheck
revisions to prevent lost wakeups. Wake consumer-loop futures and run awaits
and callbacks outside the lock. Publish local step suffixes, read isolated
snapshots and reject late steps. Only progress, state and terminal updates notify.

Set one monotonic deadline after dispatch and recheck registry and terminal state
at expiry. Progress never renews it. After stream cleanup, supervise the final
interrupted usage on the parent loop with the original holder. Deduplicate journal
entries by `source_run_id`.
See [delivery boundaries](../../../../../docs/guide/subagent-task-delivery.md).

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
- **Configure thinking per subagent.** Unset reasoning means off; use the
  subagent's definition independently of the parent.
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
- **Unverified is the safe result.** Missing criteria, checker errors, legacy
  rows, failed executions and inaccessible paths remain unverified.
- **Require a complete runner summary.** Report test success only when at least
  one test ran and no failures were counted. Preserve this rule when adding
  runner formats.
- **Pair results by message, not by call ID alone.** Providers reuse tool-call
  IDs. A call without an ID records no evidence.
- **Classify before truncating.** Compute and store test summaries from complete
  tool messages; display tails can omit the result.
- **Authorize before you read.** File criteria pass the same owner-scoped path
  checks and sandbox authorization as the file tools, and blocking reads are
  drained before the lease is released.
- **Knowledge sources survive compaction.** Sources from validated tool messages
  accumulate on the result and are published before the terminal state.
