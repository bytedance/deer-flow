# Subagent Capacity and Durable Batch Execution

## Status

Implemented in the `feat/subagent-batch-capacity` worktree. The implementation keeps ordinary delegation bounded, makes its advertised and real concurrency consistent, and adds an explicit durable batch path for large collections of independent items.

This is an implementation document, not an RFC. It describes the behavior and operational contract delivered by the code.

## Problem

DeerFlow previously exposed three different concepts as if they were one limit:

- `max_concurrent_subagents` controlled how many `task` calls the lead agent could emit in one model response.
- `subagents.max_total_per_run` limited cumulative ordinary delegations in one lead-agent run (default `6`, hard range `1`–`50`).
- the executor had a fixed process-local capacity of three native subagents.

Changing only the model-visible limit did not change the executor, while raising only the executor capacity could let the model and middleware make different promises. Neither change makes a request containing thousands of independent records durable: ordinary `task` calls still depend on the lead run, keep their task state in process memory, and return their results to the lead context.

The implementation therefore delivers both the shared capacity foundation and a separate durable batch execution mode.

## Stage 1: one process-wide execution capacity

### Startup-only configuration

`subagent_runtime` is loaded once during Gateway startup:

```yaml
subagent_runtime:
  max_running: 3
  max_queued: 64
  admission_policy: queue # queue or reject
  queue_timeout_seconds: 300
```

The schema enforces bounded values. `max_running` accepts `1`–`64`; `max_queued` accepts `0`–`10000`. The default remains three, so existing deployments do not increase model, sandbox, or database load after upgrading.

Configuration edits require a Gateway restart. Hot reload must not change a live process's semaphore while work owns slots.

### One value across prompt, middleware, and executor

For an ordinary lead-agent run, the effective `max_concurrent_subagents` is:

```text
min(requested task-call concurrency, subagent_runtime.max_running, hard safety maximum)
```

The same resolved value is used by:

- the lead-agent prompt;
- `SubagentLimitMiddleware` tool-call truncation;
- Gateway and embedded client agent construction; and
- the real process-wide execution controller.

The hard schema maximum is now `64`, but that number is not an instruction to run 64 workers. A deployment must explicitly raise `subagent_runtime.max_running`, and every ordinary request remains capped by that real process capacity.

### Admission behavior

All native subagents, including ordinary `task` calls and durable batch items, acquire the same asynchronous FIFO execution slot.

- A slot holder is counted as running.
- A waiter owns no scheduler thread.
- `queue` admits waiters up to `max_queued` and applies `queue_timeout_seconds`.
- `reject` fails immediately while saturated.
- cancellation and timeout remove the waiter and cannot leak a slot.
- task status remains pending until a real slot has been acquired.

The previous scheduler thread pool was removed. Background execution submits a coroutine directly to the existing persistent isolated event loop; increasing the queue no longer creates the same number of long-lived blocked threads.

### Ordinary runaway protection remains

`subagents.max_total_per_run` still protects the iterative lead-agent loop. Its default remains `6` and its hard range remains `1`–`50`.

This limit is not batch capacity. It prevents an ordinary conversational run from repeatedly emitting legal-sized `task` groups at successive planning checkpoints. Removing it or setting it to thousands would make accidental recursive or unproductive delegation much more expensive without adding persistence, recovery, or result collection.

## Stage 2: explicit durable batch mode

### Mode selection is explicit

A job is a batch only when the lead agent or another authorized caller invokes `batch_task`. DeerFlow does not infer batch mode from prompt wording, item count, or frontend state.

The tool is exposed only when all of the following are true:

- native subagents are enabled for the lead agent;
- `subagent_batches.enabled` was true at Gateway startup; and
- SQL persistence is available.

Ordinary `task` retains its existing wait-for-result conversational semantics and per-run ledger. `batch_task` returns a durable batch receipt immediately and tells the lead agent not to re-submit those items as ordinary tasks. Compact progress is available through `batch_status`; results are read through the owner-scoped API or JSONL export instead of being appended wholesale to the model context.

### Separate total, live, and running limits

```yaml
subagent_batches:
  enabled: false
  poll_interval_seconds: 1
  lease_seconds: 120
  max_items_per_batch: 5000
  default_max_live_items: 100
  max_live_items_per_batch: 1000
  default_max_running_items: 3
  max_running_items_per_batch: 64
  max_attempts: 3
  max_result_chars: 100000
  result_preview_max_chars: 2000
```

The three capacity dimensions are intentionally independent:

| Dimension | Meaning | Enforcement |
| --- | --- | --- |
| Total | All durable items belonging to the batch | Submission is rejected above `max_items_per_batch`. |
| Live | Items promoted from durable pending storage into queued, leased, or running work | The repository promotes only enough pending rows to fill `max_live_items`. |
| Running | Maximum execution admissions owned by one batch across workers | Database claiming counts leased and running rows conservatively; real execution also requires a process-wide slot. |

`max_running_items` is not clamped to one process's capacity. In a multi-worker Postgres deployment, several processes can contribute execution slots while the database enforces the batch-wide ceiling. Within every process, ordinary and batch work still share `subagent_runtime.max_running`.

### Durable state model

The migration creates `subagent_batches` and `subagent_batch_items`.

Batch states:

```text
queued -> running <-> paused -> completed
                    \-------> cancelled
```

Item states:

```text
pending -> queued -> leased -> running -> succeeded
              ^          |         |----> failed
              |          |         \----> cancelled
              \----------/  retry while attempts remain
```

- `pending` is durable backlog outside the live window.
- `queued` is admitted batch work not owned by a worker.
- `leased` means one worker owns recovery responsibility but the native executor has not necessarily acquired a process slot.
- `running` is written only after the executor reports real execution.
- terminal rows retain bounded result, preview, error, model, stop reason, and aggregate token usage.

### Recovery and delivery semantics

Workers claim rows using database locks and a lease owner. A worker renews the lease while an item is leased or running. If the process exits without finalizing:

1. the lease expires;
2. another scheduler pass returns the same item row to the queue;
3. the attempt counter advances; and
4. the item reaches terminal failure when `max_attempts` is exhausted.

Gateway shutdown cancels local native executions but intentionally does not falsely finalize their durable rows; the expired lease is the recovery handoff.

Submission is idempotent per `(user_id, submission_key)`, where model submissions use the stable `run_id:tool_call_id` identity. Item keys must be unique within a batch and survive retries.

Execution is **at least once**, not exactly once. An external side effect can complete immediately before a worker crashes and before DeerFlow commits the result. Batch items therefore must be read-only or use their stable item key as an idempotency key at the external system.

### Authorization snapshot

Batch submission validates the requested subagent against the caller's effective allowlist. The durable execution specification records the selected subagent definition, parent model, tool groups, skill intersection, role, channel identity, and authorization attributes needed to reconstruct the same delegated execution boundary after restart. Subagents cannot recursively enable subagent tools.

### Owner-scoped HTTP API

The Gateway exposes:

```text
GET  /api/threads/{thread_id}/subagent-batches
GET  /api/threads/{thread_id}/subagent-batches/{batch_id}
GET  /api/threads/{thread_id}/subagent-batches/{batch_id}/items
POST /api/threads/{thread_id}/subagent-batches/{batch_id}/pause
POST /api/threads/{thread_id}/subagent-batches/{batch_id}/resume
POST /api/threads/{thread_id}/subagent-batches/{batch_id}/cancel
POST /api/threads/{thread_id}/subagent-batches/{batch_id}/items/{item_id}/retry
GET  /api/threads/{thread_id}/subagent-batches/{batch_id}/results.jsonl
```

Every lookup uses both authenticated owner and thread scope. Read and export remain possible for historical batches; live cancellation requires the startup batch worker to be available.

### Frontend behavior

The frontend does not decide whether a prompt is “Swarm-like.” It reads separate SQL-repository and worker-runtime capabilities from `/api/features`. A running worker exposes the batch panel immediately; when the worker is stopped or disabled, the panel remains available in read-only mode only for threads with durable history. This preserves item inspection and JSONL export without exposing an unused panel on deployments that have never enabled batches.

The panel provides:

- active-batch count and progress;
- total, live, running, failed, and terminal counts;
- pause, resume, and cancel controls;
- item status, result preview, error, and failed-item retry; and
- JSONL result export.

Worker-dependent mutations are disabled while the worker is unavailable. Progress rendering clamps malformed persisted totals to a bounded `0`–`100` percentage so an invalid or manually edited row cannot pass `NaN`/`Infinity` into the UI primitive.

Only the first bounded item page is rendered in the panel. Large result sets stay outside the React tree and model transcript and are consumed through pagination/export.

## Why this matches the useful part of OpenClaw's design

OpenClaw does not treat unrestricted ordinary delegation as its large fan-out solution. Its ordinary subagent path has a global concurrent lane and a per-agent active-child limit. Its explicit opt-in Swarm path separately configures:

- `maxConcurrent` (running collectors);
- `maxChildrenPerGroup` (live collectors); and
- `maxTotalPerGroup` (lifetime runaway backstop).

Accepted collectors above concurrency queue FIFO inside the global subagent lane. This is the same important separation used here: explicit mode selection plus total, live, batch-running, and process-running boundaries. DeerFlow additionally persists each item and lease because issue #4993 requires long-running bulk work to survive Gateway restart rather than only organizing a conversational fan-out.

Comparison was verified against OpenClaw commit `65bcdf2f`; future OpenClaw behavior may change.

## Operational limits

This implementation makes a 5,000-item batch representable and recoverable. It does not promise that 5,000 agents start simultaneously or finish within a fixed wall-clock target.

End-to-end throughput remains bounded by:

- model-provider RPM and TPM;
- DeerFlow's LLM limiter and provider retry behavior;
- sandbox CPU, memory, startup latency, and external tool quotas;
- SQL connection pool and write throughput;
- result size; and
- the number of Gateway processes and their `subagent_runtime.max_running` values.

Operators should raise capacity gradually, observe provider throttling and resource saturation, and keep batch items independent. A value such as `max_running: 500` is rejected by the schema; scaling to hundreds of real concurrent items requires multiple appropriately provisioned workers and a shared Postgres database.

## Related work

- [#4993](https://github.com/bytedance/deer-flow/issues/4993) — bulk subagent capacity request addressed by this implementation.
- [#3099](https://github.com/bytedance/deer-flow/issues/3099) and [PR #3415](https://github.com/bytedance/deer-flow/pull/3415) — model-visible and executor concurrency inconsistency.
- [#2670](https://github.com/bytedance/deer-flow/issues/2670), [#1319](https://github.com/bytedance/deer-flow/issues/1319), and [#1339](https://github.com/bytedance/deer-flow/issues/1339) — concurrency, queueing, and subagent execution pressure.
- [#3857](https://github.com/bytedance/deer-flow/issues/3857), [#4290](https://github.com/bytedance/deer-flow/issues/4290), and [#4560](https://github.com/bytedance/deer-flow/issues/4560) — runaway protection, token/cost bounds, and long-running execution safety.
- [#3948](https://github.com/bytedance/deer-flow/issues/3948) and [#1223](https://github.com/bytedance/deer-flow/issues/1223) — persistent background work and recoverable task state.

## Validation contract

The implementation is covered at four boundaries:

- capacity configuration, startup reload boundaries, queue/reject/timeout/cancel, and slot release;
- ordinary prompt/middleware/executor consistency and executor regression coverage;
- migration parity, durable repository idempotency, live-window claiming, lease recovery, retries, controls, ownership, service execution, and JSONL routes; and
- frontend type checking, linting, API/type unit tests, and feature-gated chat integration.
