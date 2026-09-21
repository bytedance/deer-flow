# Backend Tests

Backend tests must preserve the runtime invariants they exercise without changing production execution topology.

## External system-role admission

`poc_external_system_message_injection.py --help` is the opt-in live reproduction
and post-fix verifier; never run it automatically against an existing user's chat.
`test_poc_external_system_message_injection.py` tests that CLI offline.
`test_external_system_message_boundary.py` records model inputs with a fake model:
the same regression must fail on unfixed admission and pass after rejection,
without production-provider logging or interpreting model obedience as proof.

## Scope-isolation benchmark

`test_bench_deermem_scope_isolation.py` exercises production admission and storage.
Check persisted facts and user/history summaries for semantic safety, but only
agent-local facts for routing. Failed updates must not become sealed observations;
report and resume must reject failed or old-schema rows. Stub live models so these
tests never need credentials or network access.

## MCP claim fencing

`test_mcp_task_repository.py` covers same-worker reclaim during an in-flight
release, poll/cancel snapshot, or notification completion. Use explicit events
to pause the old operation at the persistence boundary, reclaim via the real
repository, then verify the entire new row remains unchanged. Reclaiming before
the old operation starts does not catch SQLite SELECT/ORM-flush races. Keep the
old completion timestamp within its original lease so expiry cannot mask a
missing token fence; always drain paused tasks and restore session patches.

## Executor starvation tests

`test_executor_starvation.py` covers the deterministic starvation semantics from RFC #4560:

- default-executor saturation and queueing;
- cancellation of an awaiter while an already-started synchronous worker continues;
- isolation between the asyncio default executor and DeerFlow's dedicated file-I/O executor.

Use explicit synchronization such as `threading.Event` rather than sleep-based timing thresholds for worker lifecycle assertions. Every test must release blocked workers and restore any process-global monkeypatches so teardown cannot leak threads or state into later tests.

Stress/soak testing, AnyIO worker instrumentation, Uvicorn multi-process behavior, and broad production executor redesign are separate concerns and should not be folded into these deterministic regressions.
