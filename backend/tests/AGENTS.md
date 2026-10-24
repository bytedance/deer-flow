# Backend Tests

Backend tests must preserve the runtime invariants they exercise without changing production execution topology.

Upload case-collision coverage uses separate HTTP requests and preserves both
reported payloads. Observe real filename-claim inputs to pin the disk seed;
case-insensitive hosts can otherwise mask a missing seed through link retries.

Channel reload cancellation regressions must assert the worker returned the
stale snapshot before checking that newer runtime config survived. Completion
alone cannot prove the race: loader exceptions are caught and return `None`.

Browser egress session-close tests retain the real listener and its sockets,
verify a SOCKS handshake, then check listener shutdown, closed socket descriptors
and EOF on the established client. A new connection to the old port is not a
reliable ownership assertion on hosts with loopback forwarding or port reuse.
Keep ownership assertions inside the teardown-protected block; always drain
the client writer and close the saved proxy during teardown.

Read-before-write hash fixtures pin `newline=""` when writing LF/CRLF test
content, so native Windows cannot translate the bytes before the real read.

Browser-asset confinement tests use `support.symlinks.symlink_or_skip` for real
file and directory symlinks. Keep missing-file, duplicate-key, and size-limit
checks separate so they still run when the host cannot create symlinks.

`blocking_io/test_web_tool_url_validation.py` resolves a synthetic `.invalid`
hostname to loopback by patching `_socket.getaddrinfo`, below the real
`socket.getaddrinfo` wrapper. Do not replace that wrapper or the production URL
guard: the strict gate must still reject on-loop resolution. Assert each tool
path reaches the native fixture so an unresolved-host rejection cannot mask it.
The IPv4 fixture accepts only `AF_UNSPEC` and `AF_INET`; unsupported families
must fail rather than receive a fabricated IPv4 answer.

The local sandbox's UTF-8 subprocess guard inspects each text-mode call with
`ast`, checking both `encoding` and `errors`; module-wide literal counts can
hide unpinned calls behind unrelated settings.

## PostgreSQL batch fixtures

Batch fixtures use `support.postgres.asyncpg_test_url` to map libpq `sslmode`
to asyncpg `ssl` and remove unsupported `channel_binding` before constructing
database config. Preserve TLS modes, credentials and other query options;
reject conflicting `ssl`/`sslmode` values. CI uses `?sslmode=disable`; validate
that URI shape against a real test database, not only a parameter-free local
URI. Reuse the normalized config for reopening and teardown, and drop only the
fixture's UUID schema. This is test-only handling; production connection and
TLS policy are unchanged.

The 0033 batch-evidence migration fixture uses the same adapter. Its connection
contract probes execute the actual migration test setup through SQLAlchemy's
dialect argument conversion, stopping before database acquisition; the real
SQLite/PostgreSQL cases still exercise upgrade, downgrade and re-upgrade.

## Real Compose tests

`support/compose.py` probes `docker compose version --short` and requires Compose
2.24+ for optional `env_file` syntax. Skip missing, old or unreadable clients with
an actionable reason; cover version detection offline in `test_support_compose.py`.
Real rendering and production entry-point tests use only read-only Compose calls.
Never start or stop a stack from these tests.

## Claude provider tests

`test_claude_provider_prompt_caching.py` exercises real Anthropic SDK serialization
through offline HTTP transports. Keep its directly imported `anthropic` SDK in
the backend `dev` dependency group rather than relying on `langchain-anthropic`
to supply it transitively.

## User repository ordering

`test_auth.py` pins `list_user_ids()` ordering with fixed UTC timestamps and UUIDs.
Cover both creation-time precedence and the lexical stored-ID tie-break for
equal timestamps through the real SQLite repository; do not assume wall-clock
calls are distinct or weaken the result to an unordered comparison.

## Router auth fixtures

For owner-scoped route assertions, pass a stable `user_factory` and
`bind_current_user=True` to `make_authed_test_app`. The default stub stamps
request state but leaves the ambient user context unchanged; the opt-in binding
uses the stub user during the request and restores the previous context after it.

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

## Project document cache

`test_project_document_char_cache.py` pauses real file-IO workers between cache
lookup and promotion to exercise concurrent eviction. Keep cache metadata
operations atomic, and verify that a full scan does not hold the cache lock.

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

## Deploy home permission tests

`test_deploy_home_writability.py` covers the production deploy permission
preflight. It runs the complete script with a recording Docker stub and
isolated runtime paths. Permission cases remove directory write bits or secret
file read bits and restore them during teardown; they skip on Windows, as root,
or when the filesystem does not enforce those bits. Cover both persisted
secrets, shell/Compose dotenv overrides, readable read-only secrets, and teardown
without secret exports. `down` must not probe, read, or generate secrets.
Writable-directory cases remain portable.

## Workspace text cache

`test_scanner_text_cache_atomic.py` verifies complete publication and preservation
of an existing entry on failure. A cleanup failure must preserve the original
publish exception, including interruption. Import the scanner during fixture
setup, after the autouse fixtures initialize runtime, to avoid the package cycle.

Workspace deletion coverage in test_workspace_http uses actual scoped SQL and
authenticated multipart/delete/create calls: an old request must neither publish
into nor clean files from a reused thread generation. Tombstone probes execute
after real native checkpoint deletion, and uncertain cleanup checks no replay.
The native cancellation unit targets _delete_thread_data_authorized.__wrapped__
to retain its original authorization-bypassed lifecycle focus after the route
adapter split; HTTP authorization remains exercised separately.

The workspace HTTP main temporarily uses actual DbRunEventStore and
FeedbackRepository on its isolated session factory for Run/message/event reads,
then restores its native memory event fixture for the existing lifecycle main.
Do not replace scoped event results with canned payloads or remove feedback
enrichment. #71 verifies both dialects and entry-incarnation response fencing.

The workspace HTTP SSE main uses real JWT, both SQL dialects, native resident
Run records and native MemoryStreamBridge. The fixture publishes deterministic
frames (no Agent execution), commits withdrawal between frames, and checks
actual subscriber drain and unchanged running status/abort state. Token-version
withdrawal also requires native reconnect 401 before the fixture mints its next
valid token. A blocked-close native test pins cancellation intent before drain;
do not replace these edges with sleeps or pre-authorized canned responses.

Global Run reads in test_workspace_http use actual SQL messages and feedback
with real JWTs; after materialization they rotate the persisted parent nonce
and assert the prepared JSON is refused. Restore method patches before later
SSE/lifecycle checks. Native global API tests preserve unbound paging and
optional-storage behavior; these do not prove feedback write authorization.

The workspace HTTP usage/change stage seeds distinct persisted token totals and
one workspace_changes event per space, tests native include flags and SQL nonce
replacement after reads. Later deletion must retain exactly two personal SQL
events (message plus file change), one row in each other seeded child table, and
zero rows for the deleted space. Do not loosen retention to a nonzero count.

Workspace feedback tests use both actual metadata dialects. Invalid-parent and
peer rows precede valid feedback so a limit-one read proves SQL filtering.
HTTP tests commit policy/nonce changes immediately before the actual repository
method and inspect persisted rating/row count after refusal; do not mock a
successful mutation or test only the 404 status. Native feedback tests retain
unbound owner/statistics/deletion compatibility. Full fault matrices remain M11.

Workspace archive main uses actual SQL delivery events and current file bytes,
including an unpresented file that must never enter the ZIP. Observe native
builder file handles and assert close after normal send, post-materialization
policy refusal, and delayed ASGI refusal. Cancellation test separately checks
owned close/context restore. Personal SQL retention now has three events
(message/change/delivery), exactly one in other seeded child tables, zero for
the deleted space. Never relax this to an arbitrary positive count.

Artifact entry replacement in the workspace HTTP main commits an actual new
nonce inside native check_access. The old request must return 404, then a new
request must still read correct bytes. #85 failed with 200; #86 passes. This is
separate from existing prepared-response policy withdrawal and archive close
checks; do not replace it with a pre-denied canned owner response.

Workspace editor main configures artifacts and uploads with actual local provider
instances (no production config/credentials). After real private PUT, inspect
bytes/digest/size; inject actual policy/nonce/revision changes just before the
repository publication and assert old/new external bytes remain. Replace an
actual parent directory with a symlink and inspect both original/outside files
and outside temp inventory. Restore the directory in finally. No sandbox/model
execution or production physical isolation is implied. Native remote tests remain
unbound compatibility; scoped remote integration is still M4/M5.


Workspace Run identity checks use real SQLite/PostgreSQL admission and native
RunManager, then change the ambient selection and persisted policy independently.
Keep assertions on actual stored identity/nonce and refusal without mutation,
including unbound legacy upsert and resident idempotency reuse. The migration
case reconstructs parent 0038 only inside its disposable fixture database,
checks exact historical rows and NULL authority through repeat upgrades, then
checks refused downgrade preserves head and leaves no migration-owned Postgres
session. Never force DROP DATABASE or terminate connections to hide a leak.
These are short-operation/recovery foundations, not normal Agent Run execution.


Workspace worker context checks use actual native RunManager/StreamBridge and
compiled LangGraph, without a model. The scoped main provisions real verified
SQL membership, creates the ordinary Run, hands off and adopts that same row,
then executes the graph with the persisted native principal. Observe actual
tool runtime and ambient identity inside the graph, private thread busy state,
persisted terminal row and unchanged caller selection. Pending refusal checks
change actual parent nonce/member version before handoff/adopt/start; retain an
exact row snapshot to prove no owner/lease mutation. Unbound legacy CAS must not
operate on a scoped row. These do not prove public JWT/cookie admission, remote
physical execution, recurring jobs, or in-flight tool/publication revocation.


Workspace MCP checks use actual scoped SQL Run/task/member/parent records and
native McpTaskService; only remote protocol IO is deterministic. The main ends
the source Run and changes the caller's selection before polling, then inspects
actual task scope/result and context reset. Source-policy/nonce/owner/cancel
withdrawal checks happen around real IO and insert; observe compensation calls
and absent durable rows without claiming physical remote Stop. Poll withdrawal
checks assert no terminal/result commit. Use two poll slots for the independent
before/during cases so a deliberately denied old row cannot consume the one
slot and prevent the second edge from executing. Mandatory-mode checks use an
actual contextless worker call and inspect an untouched unattributed task.
Migration coverage reconstructs parent 0039 only in its disposable DB, preserves
old content/remote handles/leases through repeat upgrade to 0040 and refuses
downgrade without leaking a Postgres session. Crypto producer checks separately
prove original-runtime v2 identity and legacy-receiver refusal, not B server auth.


`test_workspace_execution_control.py` opts in only under the owned Shanghai
physical CI flag, before fixture creation. First prove real native ToolNode/MCP,
SQLite/PostgreSQL and actual running Docker -> member version change -> pending
SQL outbox -> independent control request -> physical removal -> signed receipt
-> native cancellation. The finite companion scenario covers queued user cancel,
missing provider, duplicate intent, wrong-purpose/expired/unauthenticated control,
false STOP payload, abandoned lease and service restart. ASGI is explicit, as are
trusted internal admission and the lack of public JWT/TCP/NAS acceptance. False
transport proof is a rejection injection, never a successful STOP stub. Only
manifest-owned job/spec Docker objects are cleaned. Other revocation-domain
parents remain pending. Default SQL runs skip all physical/control cases.

A historical/ordinary terminal B state without `physical_stopped` remains pending.
The control request now persists `cleanup_pending` for the existing worker to
verify exact owned-container absence/removal. Terminal metadata alone cannot
produce a STOP receipt or settle native cancellation; a running or unobservable
object still retains uncertainty. The companion test uses actual Docker
observation after the old ordinary queued-cancel path.

`test_workspace_revocation.py` first proves the native graph/SQL/real heartbeat
main on both databases. The held on_run_completed hook creates a real window
where metadata is interrupted while native finalizers are still alive; peer
admission must remain blocked. The finite companions cover callback failure
(no fake success), pending/unattached NoStart, first rollback intent preservation
with interrupt-only revocation consumption, wrong owner/context/incarnation/time,
expired owner lease, refusal of ordinary orphan takeover and replacement-parent
preservation. Trusted internal user/admission fixtures are explicit; no model,
public JWT, actual C container or new checkpoint rollback is claimed. Lease fault
restore is only disposable fixture restoration, never runtime takeover authority.
The startup negative test derives which closed production guard rejects current
metadata (unreleased schema fence or compiled integration gate), while separately
asserting _WORKSPACE_RUNTIME_INTEGRATED is False. It patches neither production
fence and proves no tenant startup; M10 must still align the release candidate.

`test_workspace_run_lifetime.py` first proves three native graph mains (normal,
member revoke during terminal cleanup, peer user interrupt), each on SQLite and
PostgreSQL. A held real completion hook plus a separate native manager proves
terminal status does not release private-thread admission; wrong-space and
withdrawn cached-user requests cannot signal local abort. Successful native close
then permits a fresh Run. The only added corrective scenario seeds a real durable
SQLite checkpoint, cancels an unstarted owner rollback and executes a late native
consumer; checkpoint ID/content must remain intact. It does not mock permission,
SQL, native closure or graph execution into success. Scoped running rollback and
actual C/OS recovery still need separate integration.

The versioned Run CI renderer accepts only revocation/lifetime suite names. The
lifetime suite combines these eight cases with the prior six Run-stop cases;
CI retains fixed images, RO source, internal PG, no runtime Docker socket and
recorded exact fixture-volume removal. Keep previous red/main/regression archives
and do not overwrite their phase names. Source receipts identify exact code
rather than treating a later formatter/test change as already verified.
