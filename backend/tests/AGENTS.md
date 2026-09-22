# Backend Tests

Backend tests must preserve the runtime invariants they exercise without changing production execution topology.

## Shared sandbox search contracts

`test_sandbox_search_contract.py` runs shared `ls`/`glob`/`grep` scenarios through
Local, AIO, E2B, BoxLite, Tenki and OpenSandbox adapters. POSIX shell transports
execute production commands against temporary files; AIO file RPCs use an
independent filesystem-backed double. Do not substitute precomputed final search
results or import another test module's private fixtures. Provisioning, live SDK
compatibility, permissions enforced above Sandbox, and session lifecycle remain
in their existing suites. Windows skips this POSIX execution tier explicitly.

Compare result names/content, errors and completeness, allowing documented root
entries and directory suffixes to differ. First-stage cases use ordinary roots,
positive caps and a plain literal pattern: ignored-root fixes (#5667), E2B literal
metacharacters (#5627), and exactly-full local caps (#5491) have separate owners.
Add those shared scenarios after their fixes land; do not encode known bugs as
expected successful behavior or hide them with permanent xfails.

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
