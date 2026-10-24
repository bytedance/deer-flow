# Backend Tests

`test_image_result_url_safety.py` drives GroundRoute through `ainvoke` and an
offline HTTPX transport. Patch only the provider's `httpx` reference; preserve
the shared client and exercise real configuration resolution and URL screening.

`test_client_upload_snapshot.py` keeps upload publication and conversion on the
same private capture. Cover source edits/removal, both conversion branches,
same-file rejection, metadata and cleanup; retain sandbox symlink defenses.
Exercise both replacement and first-time publication; mutation hooks must actually
run on both paths. Force collision retries while editing/removing the source and
assert one source open, original metadata, preserved competing uploads, companion
ownership and capture cleanup. Retain the real XLSX conversion coverage.

Backend tests must preserve the runtime invariants they exercise without changing production execution topology.

`test_goal_loop_stop_probe.py` runs the standalone Goal-loop reproduction through the native graph, loop middleware, worker and checkpoints. Only model responses are scripted; do not replace the Goal decision or simulate the stop-reason write.

InfoQuest fetch log assertions install the real `UrlRedactionFilter` on the
capture handler with fixture-scoped cleanup. Expect scheme/host context with
redacted paths, so isolated runs and full-suite logging configuration agree;
keep payload omission and tool-result assertions intact.

`.github/workflows/backend-windows-live-policy.yml` runs the child-env contract and all
four live-test collection policy cases on Windows/Python 3.12, weekly, manually,
and for relevant PR changes. These children only collect live tests. Keep the
make-dependent checks in the default suite. The workflow-selection regression
in `test_client_live_policy.py` collects the configured pytest nodes and pins
all five policy checks, so a partial name filter cannot silently omit cases.

Runtime-callback cleanup tests keep DEBUG capture enabled and implement graph
checkpoint reads. Fixture-only exception tracebacks can retain the journal;
preserve the strict weak-reference assertion rather than clearing captured logs.

Config-upgrade checkout fixtures clear inherited `DEER_FLOW_CONFIG_PATH`,
`DEER_FLOW_PROJECT_ROOT` and `DEER_FLOW_ENV_FILE` before applying explicit test
overrides. Exercise selector leaks through the real script with temporary
configs; assert that the simulated developer config and its backup stay untouched.

Image-context budget regressions use real PNG files through `view_image`, the
state reducer, and both model-call wrappers. Check decoded payloads, cumulative
base64 size and skipped file reads; keep count and byte limits independent.
Re-view coverage must first observe omission, then restoration in model input.

Local nginx path fixtures convert MSYS output through the selected Git Bash's
PATH and decode both renderer and converter output as UTF-8. POSIX Git-layout
stubs exercise Windows-style locale decoding and missing/failed/empty converters;
native Windows keeps the real Git Bash renderer checks, including Unicode paths.

`test_skills_custom_multiprocess.py` starts independent spawn workers sharing a
temporary custom-skill root. Park edit/rollback before the write and before the
history append, observe the peer reaching the mutation lock, then check both
exclusion and the persisted predecessor chain. Always release and reap workers
on assertion failures; do not replace this with two threads sharing a mutex.

Search coercion ownership tests audit executable helper bodies/call sites and
inline integer assignments. Include Exa and SearXNG in the deferred census;
pin new-provider copies and docstring false positives with source fixtures.
This pattern gate does not establish arbitrary provider semantics or change
deferred providers' validation policy.
Include You.com in the shared-owner provider checks; it applies its 100-result
cap after shared normalization. Pin invalid-value defaults and positive count
bounds through the outbound request in `test_youcom_tools.py`.

Mixed-version resume admission in `test_thread_run_idempotency.py` uses a real
shared SQL repository and an old-column projection. The frozen pre-6499 helper
models only null-input resume retry matching from `02ce9ab2`; do not update it
to the new identity-aware policy or claim it runs a complete old Gateway.
Assert both writer formats: old workers reuse conflicting decisions, upgraded
workers reject conflicts, and identity-less legacy rows fail closed even for
identical retries. This pins why rollout requires routing to upgraded workers.

Run-store capability tests in that file check keyed input separately from resume
identity and assert that rejected admissions create no durable or local run.
An explicit `idempotency_key` parameter must keep supporting keyed input even
without resume support. For kwargs-only stores, pin the opt-in on the class
that defines `create_thread_operation_atomic`: replacing an opted-in parent's
method requires a fresh declaration; a flag-only child or mixin cannot opt in
another class's implementation. Also cover unchanged inheritance and durable
retry reuse, so the rejection tests cannot pass by rejecting every custom store.

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

Browserless reservation cleanup tests require a warning with the leftover path
and unlink error while preserving the original publication exception, including
interruption. Successful cleanup stays quiet.

Extension snapshot rollback and the managed plugins-block rewrite preserve the
original publish error when temporary cleanup or its warning log fails.
`tests/test_extension_atomic_write_cleanup.py` covers both writers, including
interruptions, an `fdopen` failure whose descriptor close also fails, a plugins
rewrite that fails while writing, a successful plugins rewrite's bytes and
mode, and a delete-branch restore whose unlink failure still lets a later
snapshot restore.
Skill archive upload copies do the same in
`tests/test_skill_archive_upload_cleanup.py`: a size-limit or read error stays
visible, a successful copy returns the original bytes, and the upload route's
post-install discard cannot replace a successful install or an install error.
A form-close failure cannot replace that outcome or skip the discard.
Custom-skill file writes and per-user skill-state writes do the same in
`tests/test_skill_storage_atomic_write_cleanup.py`, including
`KeyboardInterrupt` during a skill-state replace.

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
Channel JSON state coverage likewise checks each writer and Discord reader call
within its owning class/method; unrelated encoding literals must not mask a regression.

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

## Jina client options

Retry/response-budget compatibility tests pin client count and caller-supplied
`proxy`/`trust_env` settings. Additional provider-owned HTTPX options must not
break those assertions.

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

## Lark skill-pack publication

`test_lark_skill_manifest_atomic.py` injects `os.replace` failures at the actual
guidance and manifest writes. Assert that existing file bytes survive and
temporary files disappear. Reinstallation tests use complete ZIP fixtures and
the real installer: the previous installed tree must stay byte-identical while
the write is still in staging and after it fails, with no staging or backup
tree left behind. Do not replace these behavioral checks with assertions about
source formatting or duplicate the runtime publication control in
`test_lark_cli_atomic_publish.py`. That runtime publisher must also keep the
original publish error when temporary cleanup or its warning log fails,
including interruptions. A successful publish still replaces the bytes, leaves
no temporary file, and keeps the temporary file's mode; callers chmod afterward.

## Channel staging cleanup

`test_channel_staging_cleanup.py` blocks the rename destination (a non-empty
directory, because an empty one would just swallow the staged file) and fails
`Path.unlink`, the descriptor `close()`, and the log handler in turn. Assert the
save error is what propagates, that the unlink is still attempted after a failed
close, and that a staged copy the cleanup could not remove is named in a warning.
Keep these as injected-failure behavior checks: an assertion that the handler
source merely contains `suppress` would pass while the close error still skipped
the unlink.

`test_channel_credential_staging.py` leaves copies through the real credential writers, then ages
one for restart cleanup. Preserve current credentials, recent peer staging, anonymous files,
symlinks, directories and nested attachments. Exercise SQL startup after the legacy file is gone,
plus failed unlink/listing and a real delayed FileHandler whose parent is missing. WeChat startup
cleanup must also pass the strict blocking-I/O gate. Buzz failure tests keep the original write
exception attributable through close/unlink/diagnostic errors, retain pending events for a later
flush, and propagate interruptions after cleanup.

## Lark CLI blocking-I/O fixtures

`blocking_io/test_integrations_router.py` uses a real local CLI stub: a `.cmd`
script on Windows and an executable shell script on POSIX. Resolve it through
the production PATH lookup, including a directory containing spaces. Seed fake
app credentials so auth completion reaches the CLI instead of returning early,
and keep fixture filesystem work behind `asyncio.to_thread`.

## Lark device-login single-flight

`test_lark_auth_singleflight.py` pins the `(user_id, generation)` single-flight
contract: request timeouts leave one shared CLI alive; supersession terminates
it, including its POSIX process group. Forked workers share a credential root;
every CLI gets the invocation-log environment so duplicate spawns are visible.
Publication grace starts at observed CLI exit, independent of login duration.
Cover publication between a foreign result read and its marker probe.
`test_lark_auth_lifecycle_failures.py` injects storage and startup failures:
terminal marker receipts prevent retrying uncertain single-use codes, cleanup
errors preserve published results, and failed starts reap children and wake
waiters. Treat unhandled worker-thread warnings as errors. Event-driven process
doubles must be released/killed and joined at teardown.
`test_lark_credential_tree_churn.py` removes real descendants at each walk step;
assert the injection fired and surviving secrets reached private modes. Missing
roots, permission errors and symlinks remain errors. Mutations must fail these
assertions; merely returning without an exception is insufficient.
Run mutations on a copied harness; never swap checkout sources during tests.

## Remote read fixtures

Remote ranged-read fixtures pass POSIX sandbox paths to adapters and map those
paths to native temporary files in fake transports. LocalSandbox keeps the native
host path; do not relax remote path validation to accommodate Windows fixtures.

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

Notification recovery tests advance to the persisted `next_notification_at` after
dispatch. It records completion time; a fixed scan-time offset can query before
the notification is due on a slower runner. Preserve delivery and counter assertions.

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

## Workspace snapshots and text cache

`test_workspace_changes.py` and `test_run_worker_delivery.py` remove real files
at the hash-read boundary. A vanished source must not discard other file records
or produced-output detection; permission and other hash I/O errors still propagate.

`test_scanner_text_cache_atomic.py` verifies complete publication and preservation
of an existing entry on failure. A cleanup failure must preserve the original
publish exception, including interruption. Import the scanner during fixture
setup, after the autouse fixtures initialize runtime, to avoid the package cycle.

### Web model provider presets

`test_managed_provider_presets.py` covers encrypted compatibility, auto IDs, key switching, snapshot isolation and native/compatible protocols. Its HTTP double is below actual LangChain/vendor SDK serialization; do not replace these adapters with successful stubs. `test_managed_presets_live.py` requires explicit opt-in and vendor credentials, and remains skipped in CI.

## Helm Redis credentials

`test_helm_redis_existing_secret.py` renders the chart and executes its startup
and both probe commands with argument-recording Redis stubs through
`support.shell.require_posix_sh`. Keep missing/empty password keys, stale
`redis.auth.password` values, Secret precedence, external mode and shell
metacharacters covered.
Render tests skip when Helm is unavailable; they need no Kubernetes cluster.
A falsy `existingSecret` (`false` is how people spell "not set") must fall
through to the chart-managed Secret, not name the Secret after the value.

## Helm postgres Secret precedence

`test_helm_database_secret_precedence.py` pins that the gateway's `DATABASE_URL`
and the postgres StatefulSet's `POSTGRES_PASSWORD` resolve the same Secret in
every branch of `deer-flow.databaseUserSecret`, and that only the chart-managed
branch renders a Secret. Teaching one consumer a new Secret source without the
other has to fail here. The falsy cases exist because `or` returns its last
operand even when falsy, which would name the Secret `false`.

## Multi-instance harness

Multi-instance harness tests use `support.shell.require_script_bash()` for shell
smoke checks. Keep config content and secret stability checks portable; isolate
POSIX owner-only permission assertions so Windows skips only those checks.
Nginx path expectations must include quoted-string escaping for native paths.
