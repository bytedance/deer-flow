# Sandbox0 provider

Use the optional official SDK. A persistent state directory stores user/thread
bindings; one Gateway holds its OS lock. Remote RootFS is the durable workspace,
and host workspace/output files are bounded artifact mirrors. Never replace a
missing binding target with an empty workspace. Commands use fresh bash
processes; prepared skills replace `/mnt/skills`, and inputs are copied on acquire.

Persist lifecycle intent in the binding before issuing pause/delete, using an
atomic file replacement and file/directory sync. Keep unresolved intent across
process restarts. `get()` must hide pending handles without doing I/O. Acquire
must reconcile a persisted pause before resuming, including when the server
still reports running; pending deletion requires an explicit destroy retry.
Clear pause intent only after a committed checkpoint. Publish readiness or drop
the retry handle atomically with clearing its in-memory quarantine. Release
retries skip artifact reads because the runtime may already be paused. Shutdown
preserves identities and bindings; destroy is explicit deletion.

Tests: `backend/tests/test_sandbox0_provider.py` and `test_sandbox0_transfer.py`.
Keep sync/async execution-lease and provider-restart failure regressions. The
real agent validation entry is `backend/examples/sandbox0/demo.py`.
