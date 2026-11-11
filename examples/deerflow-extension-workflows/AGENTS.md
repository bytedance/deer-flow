# Script workflow extension (`examples/deerflow-extension-workflows/`)

An installable extension that runs a generated script as a workflow over public
AgentRuns, with human approval, crash recovery and an optional PostgreSQL cluster
mode. The workflow logic stays in this package.

## Verify

```bash
cd backend
python -m pytest tests/test_workflow_plugin.py tests/test_workflow_recovery.py -q
make test-blocking-io
```

Then run `verify_browser.mjs`. The cluster tests need
`DEERFLOW_TEST_WORKFLOW_POSTGRES`, and the deployed acceptance test needs
`DEERFLOW_WORKFLOW_ACCEPTANCE=1` with Docker. The browser fixture and the
acceptance entry point are test-only and must never become a deployed
authentication or admission bypass.

## Boundaries

- **Import only `deerflow_extension_api`, the standard library and the declared
  QuickJS dependency.** Host `app.*` and `deerflow.*` modules are private.
- **The generated script runs only in the worker's isolated JavaScript context.**
  Never pass it a host callable, a capability handle, a credential or the
  environment. `Date` and random values are unavailable there.
- **The parent kills and reaps the worker**, and every IPC, stored and public
  payload is bounded.
- **Never serialize a capability handle**, and never rebuild authority from a
  stored user ID. Recovery binds a fresh authenticated session.
- **Owner scope applies to every public read and mutation.**

## Admission, cancellation and results

- **Persist the child thread, input message, attempt and idempotency identity
  before admission.**
- **A timeout or an unknown admission outcome is reconciled, never retried.** An admission that was provably rejected
  releases its capacity; an unknown one keeps it.
- **Workflow cancel is a signal to the supervisor.** Do not cancel the admission
  task itself, which would lose a child that already exists.
- **Keep admission uncertainty apart from an observation timeout after
  admission.** A known run is interrupted and observed.
- **Agent success is never human approval.** A human decision is bound to the
  output hash, the step and attempt, and the authenticated session.
- **A thread's latest state is not an immutable run output.** Check message and
  run attribution, interrupts and pending human input before you copy an output.
  Anchor a result on the visible human input.
- **Keep the supervisor outcome private until child tasks and fenced cleanup
  finish.** Publishing the terminal status early retires the PostgreSQL lease
  before the reservations are released.
- **This extension gives no hard currency limit and does not freeze external
  state.** Do not claim either.

## Recovery

- **Persist the bridge intent before a host effect, and the response before it is
  delivered to the worker.** Replay reuses committed outputs and decisions.
- **Replay after a restart needs an authenticated recovery action.** Legacy
  records are for inspection only.
- **A captured file is read by its stored step and version.** Do not overwrite it
  from a mutable source.
- **Compatibility checks include the worker source, the supervisor source and
  the engine version.** `constants.py` holds the registration and lease
  namespace as one declaration and is part of that signature.
- **A stored `cancelling` state is never replayed.** An expired one is
  recoverable for cancel cleanup only.

## Storage modes

- **SQLite mode holds the process lock for the life of the service.** Do not
  recover live records while another Gateway owns the file.
- **PostgreSQL mode shares one database and schema with the host.** Every
  supervisor write, file capture, child admission and child cancellation is
  fenced by a lease epoch on the database clock. Host admission and cancel lock
  the lease row inside their transaction; a preflight check is not a
  replacement.
- **Lease loss kills only the local worker.** Do not clean up children that a
  successor now owns. A takeover needs a fresh session and a matching runtime
  and configuration.
- **Drain a SQLite write through repeated cancellation** before you release the
  write lock.
