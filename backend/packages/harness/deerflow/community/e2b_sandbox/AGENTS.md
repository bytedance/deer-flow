# E2B sandbox provider (`deerflow/community/e2b_sandbox/`)

Runs sandboxes as E2B cloud VMs: creation with file restoration, warm reuse,
lease renewal, reconciliation with the remote inventory, and shutdown. General
sandbox rules are in the [sandbox guide](../../sandbox/AGENTS.md).

## Verify

```bash
cd backend
python -m pytest tests -q -k "e2b or sandbox_search_contract"
make test-blocking-io
```

## Restoration

- **A new VM restores the thread's files before it is registered.** Read them
  from the Gateway-visible `Paths` directories. The `host_*` paths address the
  Docker host, not Gateway storage.
- **A reused VM keeps its live contents.** Persisted files are never replayed
  over an active, warm or discovered VM.
- **A failed restore discards the VM** through ownership-fenced cleanup, and keeps
  the capacity charged when destruction is not confirmed.
- **A scan failure propagates.** It must not read as an empty directory. A
  required resource over the limit raises with the remedy; it is not truncated.
- **Reject a symlinked resource root or ancestor**, and skip nested symlinks and
  special files.
- **Caller-facing errors name the logical tree, not a host path.**

## Locks and leases

- **Each VM has two lock domains, `timeout` and `ownership`, and they are never
  held together.** A slow E2B timeout request must not block lease heartbeats.
- **Lock order is thread key, then lifecycle, then `_lock`.** Do no remote I/O
  under `_lock`.
- **After a lock wait, check the sandbox identity and the acquisition intent
  again** before you act on a snapshot.
- **Sweeping old local warm entries does not release deployment capacity.** A
  peer may have renewed the VM. Shared removal follows the revision-checked
  remote inventory, and a partial or failed inventory proves no absence.
- **Release owns the final idle-timeout write, and cleanup finishes before a new
  lease is published.** Do not hold the VM lock during output sync.

## Shutdown

- **A bounded join is a wait budget, not proof.** Check that the renewal and the
  reconciliation thread have exited before you clear registries. If one is
  alive, keep admission closed and keep the state, so a later `shutdown()` can
  retry.
- **A signal-triggered shutdown still forwards the original signal action.**
  Under the Gateway lifespan the provider is shut down after the run drain.

## File search

- **Quote the whole `--include=<pattern>` argument**, so the shell does not expand
  the pattern.
- **Use `grep --null` and parse the line number after the NUL.** A colon is a
  valid path character.
- **Split output records on `"\n"` only.** `splitlines()` also splits on
  characters that can occur inside a file name.

## Mount uploads

- **The upload deadline is cooperative.** It is checked between steps and does
  not interrupt an SDK call that is running.
- **`mount_upload_result.truncated` reports a resource-limit stop only.** A mount
  that failed is logged, and it does not block later mounts.
- **Clearing the managed remote skill categories and uploading the new projection
  is one critical section**, shared with acquire and release. A VM that was
  created from another skills root is never adopted.
