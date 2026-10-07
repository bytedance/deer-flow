# AIO Sandbox

## Stdin contracts per transport

AIO has two distinct stdin contracts: the persistent `/v1/shell` transport is a
PTY, while `/v1/bash` uses a subprocess pipe that stays open for writes. Keep
persistent shell commands unchanged: the Lark broker shim already ignores TTY
input. Only fresh `_run_bash_exec` calls prefix the original command with
`exec < /dev/null` so default stdin gets immediate EOF; explicit
pipes/heredocs/files still override fd0. Those sessions are created and
released per invocation, so the prefix never closes a reusable terminal or
alters its state. Avoid brace-group/eval wrappers: they shift top-level
parsing (alias/extglob timing), disturb `PIPESTATUS` across calls, can fire an
`ERR` trap an extra time, or append a delimiter a trailing backslash consumes.

The broker shim forwards pipe/file input only after EOF: an idle pipe exits
124 without a broker request, and read errors fail rather than becoming empty
input. Window overrides must be finite positive seconds, at most 600. Broker
INFO logs contain argc/exit/elapsed only, never argument values.

Regressions: `tests/test_aio_sandbox.py`, `tests/test_lark_broker.py`.

## Reuse admission

An implicit-shell fence is sticky for the container's lifetime, even after a
successful explicit recovery session. `requires_container_recycle` includes
that fence and ambiguous/pending shell or bash creation. Release persists a
generation-bound record in `{DEER_FLOW_HOME}/sandbox-quarantine` before stopping;
failed stops, lease expiry and Gateway restarts never clear it. Docker discovery
restores the container ID; provisioner responses restore the Pod UID. Unknown
generations fail closed against existing records. New generations can reuse the
logical sandbox ID. Gateways sharing containers must share this home as well as
the configured ownership store. Keep `get`/`get_scoped` free of storage IO.
Before creation, retire records only under a local reservation and teardown
lease, after `SandboxBackend.is_absent` confirms logical-ID vacancy. It must
distinguish missing resources from stopped/Pending/Terminating resources and
probe failures; DELETE acceptance and discovery returning None are insufficient.
Remote proofs use `/api/sandboxes/{id}/presence`, which inspects the Pod directly;
the ordinary status GET can return 404 merely because its Service is missing.
This covers runtimes without a recoverable generation, including Apple Container.
`inspect_runtime` returns metadata independently of health, running state or
Service availability; only confirmed resource absence returns None. Probe failures
raise, including Docker context/daemon errors. Under the same teardown fences,
retry partial cleanup only if that current generation is quarantined, then prove
absence before retiring records. Preserve an unquarantined replacement generation
and its predecessor's records; unknown generations remain fenced.
Local retries recover published ports, including stopped Docker bindings, and
retain pending reservations by immutable generation until resource teardown
succeeds. Apple logical IDs are not generations or Docker policy metadata.
Remembered ports without a generation may be released only after confirmed name
vacancy; never attach them to metadata for a present replacement runtime.
A fenced sandbox still tracked by this instance (failed release recycle) is destroyed inline on the next acquire and the acquire falls through to create; deferral is a transient answer there, never a terminal one.
A Pod-attested broker mode outranks an unavailable deployment-level probe: the probe failure delays drift detection but never denies reuse of an attested runtime, while an unattested mode stays fail-closed.
Before retiring records, `complete_absent_teardown` releases pending local ports
under those same fences after confirmed absence, including a timed-out stop that
actually removed the container.
It also clears deterministic local proxy/network leftovers before recreation;
unknown cleanup errors retain the quarantine record.

Broker capability failures are unknown, never confirmed negatives. Cache only
successful observations per provisioner endpoint/auth identity; a failed refresh
may retain a confirmed broker requirement. A provisioner lark-configuration conflict marks its create response; the
Gateway drops that endpoint's cached observation so the next acquire re-probes
instead of outliving the negative TTL. Acquisition validates actual mode in
active, warm, discovered and create responses. Policy replacement keeps the
existing ownership and local teardown fences; do not stop a live peer's Pod.
`bash` uses the admitted sandbox's mode, never a fresh deployment-wide probe.
Contradictory Pod observations bypass cached capabilities before replacement.
One in-flight probe per endpoint/auth identity shares results/errors; cache locks
never cover network IO or waits. Failure retry time is separate from confirmation
freshness and cannot authorize credential mounts. All post-create registration
failures use the existing fenced cleanup, including policy/storage/probe errors.
Rejected provisioner creation metadata must retain its `SandboxInfo` for that
cleanup. Failed discovery registration closes only its own HTTP client.

Regressions: `test_aio_sandbox_provider.py`, `test_sandbox_quarantine.py`,
`test_remote_sandbox_backend.py`, `test_provisioner_request_threading.py`.
