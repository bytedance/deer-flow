# Script workflow extension

Keep workflow business logic in this packaged extension. Import only public
`deerflow_extension_api` contracts, standard library and declared QuickJS dependency;
never import private `app.*` or `deerflow.*` runtime modules.

Generated script runs only in worker.py's isolated, capability-free JS context.
Never pass host callables, capability handles, credentials or ambient environment
into it. Keep every IPC and stored/public payload bounded. Parent lifecycle must
kill and reap the worker and explicitly observe child cancellation.
Agent tasks allow 16,000 serialized JSON bytes and outputs 12,000; preserve enough
input room for a retained output plus task wrapping. Test sequential handoff with
both ASCII and escaped Unicode, and reject oversized inputs before admission.
The worker turn cap counts worker frames only; while the worker is idle (its job
queue drained) and Agent calls are pending, wait locally with bounded cancellation,
fault and worker-exit polls instead of round-tripping empty frames, so wall time stays the only clock bound.

Persist stable child thread, input message, attempt and idempotency identity before
admission. Workflow cancel is a supervisor signal; do not cancel an admission task
and lose an already-created child. Timeout/unknown outcomes require reconciliation,
never automatic retries. Distinguish admission uncertainty from post-admission
observation timeout: interrupt/observe known runs and escalate only uncertain cleanup.
Keep the workflow deadline handler outside asyncio.timeout and test external cancellation
separately. Hash the Agent allowlist in canonical sorted order. Owner scope applies
to every public read and mutation.
Own persistence through supervisor publication even if the launching caller cancels.
Serialize launch admission and shutdown. After artifact IO, validate call limits
and step uniqueness together with await-free reservation. In SQLite mode hold the process lock across service life;
do not recover live records while another Gateway owns the file.

Anchor results on the visible human input, including canonical __user rewrites;
never use hidden system/memory IDs. Retain UI launch identity across refresh failures.
Thread latest state is not immutable run output. Check message/run attribution,
interrupts and pending human input before copying output. Agent success is never
human approval. Live checkpoints retain the worker. On restart, versioned bridge-journal replay
requires an authenticated recovery action; reuse committed outputs and decisions.
Legacy records are inspection-only. Never resubmit uncertain admissions. Bind human decisions to source output hash, step/attempt and authenticated
session ActionContext, never ToolContext. Persist before waking; fence duplicate
resume by checkpoint ID. Config revision is a declarative preflight guard. Store actual host assembly
evidence per child run; never expose raw credentials. File checkpoints bind
append-only captured bytes and SHA-256; preview and approved consumption read
that exact version. Never claim hard currency limits or freeze external state. Do not serialize capability handles.

Tests live in backend/tests/test_workflow_plugin.py. Run the backend offline and
blocking-I/O targets plus verify_browser.mjs. The browser fixture is loopback-only
and synthetic; it must never become a deployed authentication bypass.

Phase 3: recovery.py owns session reattachment, exact bridge replay and admission
reconciliation classification. Store.put uses conditional revisions; drain SQLite
writes through repeated cancellation before releasing the write lock. Service-own
recovered-run cancellation through child cleanup and the terminal write, and drain
it during shutdown even if its caller disconnects. Log failed service-owned actions
at error level even after caller disconnection; omit raw exception payloads as for
supervisor failures. Persist bridge intent
before host effects and responses before worker delivery. Include worker/supervisor
source and engine version in compatibility checks; Date/random are unavailable.
Preserve original wait expiry and remaining execution budget. Read captured files
by stored step/version after crashes, never overwrite them from mutable sources.
PostgreSQL mode uses postgres.py/cluster.py: the host and extension must share
one database/schema. Database-clock leases use monotonically increasing epochs.
Every supervisor write, file capture, child admission and child cancellation is
fenced. Host admission/cancel lock the lease row in their transaction; never replace
this with a preflight check. Durable controls are immutable and consumed by the
owner. Lease loss kills only the local JS worker; never clean up successor children.
Unknown child reservations retain cluster capacity. Takeover requires a fresh
session and matching runtime/config; there is no unattended authority reattachment.
Keep the SQLite flock default. Cluster tests use DEERFLOW_TEST_WORKFLOW_POSTGRES
and disposable schemas, including real process kill and a host row-lock race.
Recovery tests: backend/tests/test_workflow_recovery.py, including real process kill.

AgentRuns.configuration_revision(durable=True) uses a purpose-separated HMAC
under the persisted host signing secret for restart comparison. Default revisions
remain process-local. Rotation invalidates comparisons; no raw config or secret is
returned. Recovery callers must bind a fresh authenticated session capability;
never serialize handles or reconstruct authority from a stored user ID alone.

Deployed acceptance: `backend/tests/test_workflow_gateway_acceptance.py` opts in
with DEERFLOW_WORKFLOW_ACCEPTANCE=1 and disposable Docker PostgreSQL/Redis/nginx.
The support/workflow_gateway.py entrypoint is test-only: deterministic model and
barriers around real operations, never a deployed auth/admission bypass. Use real
SIGKILL/SIGSTOP, login/CSRF, host runs and persisted assertions. Preserve uncertain
reservations; there is no supported reconciliation attestation/release API yet.

Keep the plugin registration and execution-lease namespace in constants.py as a
single declaration. Include that module in the recovery runtime signature.

Project expired cancelling as recoverable for cancel cleanup; never permit replay
of stored cancelling. Cancel claims persist cancelling and bypass admission caps.
Inspection/list reads use read-only, lock-free transactions and a single joined
record/lease snapshot. Keep write serialization and fencing intact; pooling remains
future work. Cover killed cancellation takeover and saturated cancellation cleanup.

Keep the supervisor outcome private until child tasks and fenced cleanup finish.
Child saves share the workflow record; publishing terminal status early retires
the PostgreSQL lease before reservation release. Pin cancellation ordering with
a barrier-based cluster regression.

Proven pre-admission rejection releases child capacity before retiring the lease;
unknown admission errors retain it. Share the slot-release predicate across cleanup paths.
Acceptance routing counts final Gateway ports, not nginx retry-history strings.
