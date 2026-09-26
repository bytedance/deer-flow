# Backend Tests

Backend tests must preserve the runtime invariants they exercise without changing production execution topology.

## Lark CLI blocking-I/O fixtures

`blocking_io/test_integrations_router.py` uses a real local CLI stub: a `.cmd`
script on Windows and an executable shell script on POSIX. Resolve it through
the production PATH lookup, including a directory containing spaces. Seed fake
app credentials so auth completion reaches the CLI instead of returning early,
and keep fixture filesystem work behind `asyncio.to_thread`.

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

## Managed DeepSeek compatibility

`test_managed_deepseek.py` exercises real SDK request serialization and SSE parsing
with an HTTP double; do not replace the provider classes with successful stubs.
`test_managed_deepseek_live.py` uses the same production probe/model configuration
against DeepSeek only with `DEER_FLOW_RUN_LIVE_TESTS=1` and
`DEEPSEEK_TEST_API_KEY`, never in CI. Keep credentials and provider payloads out of
committed evidence. A passing connectivity probe does not establish full agent
compatibility; distinguish protocol assertions from observed live behavior.

## Classification request packing

Pin the Jev example's outbound byte budget against captured HTTP request bodies.
Cover UTF-8 text and JSON embedded in chat messages, including escaping-heavy
inputs that fit the host's separate input limit. Use offline transports.
Check the host's JSON output bound with the maximum item count and keys that
expand when escaped; preserving raw UTF-8 limits alone does not cover it.

## Advisory fetched-content screening example

Load the example through `load_extensions()` and the host isolation wrapper, as a
`plugins:` entry is loaded; never instantiate the middleware directly.
`test_jev_result_screening_extension.py` checks install/config diagnostics, bounded
requests, the task-store handover between the tool wrapper and `before_model`, copy
semantics, fail-open provider errors and isolation diagnostics for local bugs. It
also pins per-message classification: a benign first message in a `Command` must
not take the flag of an injected later one, and a malformed, compressed or slow
answer for one message must not cancel or hide another's flag. The loopback test
uses a real local server behind an unreachable proxy variable.
`test_jev_screening_pipeline.py` runs real lead/subagent graphs to a recording model
with a task store bound under the runtime-context key the Gateway worker uses; cover
the redacted excerpt, error metadata/receipts, budget, one-time warnings including
valid empty-string message IDs, and runs without a task store. Only `None` awaits ID
assignment. Use offline transports. Detection is not behavioral defense; do not infer
the final model input from an isolated hook test. `test_jev_screening_policy.py` uses
the host descriptor builder to pin policy identity; hash endpoint/prompt text and
never project credential values.
