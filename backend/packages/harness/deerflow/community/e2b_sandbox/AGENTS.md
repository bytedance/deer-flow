# E2B lifecycle

Fresh VM creation restores owner/thread-scoped workspace, uploads, outputs and
ACP files from Gateway-visible `Paths` directories before registering the VM.
Do not use `host_*` paths: those address the Docker host, not Gateway storage.
Restoration is required and shares the creation upload budget with optional
skills and mounts. Errors discard the VM through ownership-fenced cleanup and
retain capacity if destruction is unconfirmed. Active, warm and discovered VM
reuse must never replay persisted files over live contents.
Reject symlinked resource roots/ancestors; skip nested symlinks, special files,
upload staging files and output-sync temporary files. Directory scan failures
must propagate rather than masquerading as empty directories. Release sync is
still copy-only; deletion reconciliation is a separate contract.
Capacity breaches raise `_ThreadResourceRestoreLimitError` with the logical tree,
cap and operator remediation; deadlines remain ordinary restore errors. Do not
silently truncate required resources or imply unchanged over-limit data can succeed
on retry. Log restore failures with owner/thread context and the exception chain;
caller-facing errors identify the logical tree without exposing host paths.
Regressions: `tests/test_e2b_sandbox_provider.py` exercises release, expiry and
recreation using saved bytes, plus isolation, reuse and failed restoration.

Reconciliation floors active-client TTL renewals at the SDK's default timeout
and twice the sum of the configured reconciliation interval and pass budget
(subject to the E2B timeout cap). Release still uses the configured idle timeout.
Sweeping old local warm entries must not release deployment capacity: a peer
may have renewed the VM. Leave shared removal to revision-checked remote
inventory and its missing-entry grace period; partial/failed inventory cannot
prove absence.

Per-VM `_sandbox_lifecycle` locks have independent `timeout` and `ownership`
domains. Timeout locks serialize active TTL writes with removal from the active
map. Ownership locks serialize publication/claim/renewal/release with warm-entry
cleanup. Never hold both domains: slow E2B timeout requests must not block lease
heartbeats for this VM or subsequent VMs in the renewal pass.
Snapshot readers recheck sandbox identity, parked-entry identity and acquisition
intent under that lock before acting. Lock order is thread key, lifecycle, then `_lock`;
never wait for a lifecycle lock while holding the metadata lock or perform
remote I/O under `_lock`. Holders and waiters retain one refcounted RLock per domain/ID,
reclaimed on the last exit. Cleanup remains available during shutdown without
an executor or a permanent per-sandbox lock table.

Release must own the final idle-TTL write, and cleanup must finish before a new
lease can be published. Do not renew ownership removed by a concurrent cleanup.
Release only needs the VM lock while leaving active state; do not hold it
during output sync, which must not prevent ownership heartbeats.
Track that release in `_remote_ops_in_progress` until it completes so
reconciliation cannot probe or re-adopt a VM between active and warm states.
Acquire drops the lease of a VM it finds gone (dead cached client, reaped
warm entry): no later path sees that ID, and the renewer re-claims any lapsed
lease it still tracks.

Shutdown owns both maintenance workers as well as sandbox registries. After
signalling the lease-renewal and reconciliation threads, a bounded join is only
a wait budget: verify each worker actually exited before clearing registries or
tearing down resources. If either worker is still alive, keep admission fenced
and preserve all tracked state so a later `shutdown()` can retry cleanup.
That fence covers cached sync/async acquisition too: recheck after serializer
waits and immediately before exposing a reused client. Signal-triggered shutdown
may report deferred cleanup, but it must still forward the process's original
SIGTERM/SIGINT/SIGHUP action while retaining the pending E2B state. Under
`hold_sandbox_shutdown_ownership()` (Gateway lifespan) only SIGHUP is
installed; the lifespan shuts the provider down after the run drain.

## File search

Quote the complete `grep --include=<pattern>` argument with `shlex.quote` before
passing it to the shell. The shell must not split or expand filename patterns;
grep owns basename globbing and `path_matches` owns root-relative directory
scoping. `tests/test_sandbox_search_contract.py` pins this across providers using
real temporary files and offline shell transports.

Use `grep --null` to separate the filename from `line:text`, then parse the
line number only after that NUL delimiter. Colons are valid path characters,
so never split the whole record on them. Real-shell regressions in
`tests/test_e2b_sandbox_provider.py` cover colon-containing files and directories.

Split `grep` and `glob` output records only on `"\n"`, matching
`parse_remote_search_output`. Do not use `splitlines()`: its other boundaries
(carriage returns, vertical tabs, form feeds, and control/Unicode separators)
can occur inside filenames or matched text. The real-shell tests cover these
characters in filenames, parent directories, and grep content; their transport
decodes captured bytes without universal-newline conversion.

## Mount uploads

E2B uploads host mounts during sandbox creation using binary file objects.
Per-mount limits: 100 MiB/file, 512 MiB total, 2,000 files. The full creation
pass shares a 512 MiB / 2,000-file budget across skill projections and mounts.

The pass has a cooperative deadline controlled by
``mount_upload_deadline_seconds`` (default: 120 seconds). The provider checks it before
each mount, during directory preflight, and before each SDK write. The deadline
does not interrupt active filesystem or E2B SDK calls.

The provider checks mount limits before upload. It rechecks each opened file descriptor against its preflight size before SDK upload.

For policy-scoped turns, clearing the four managed remote skill categories and
uploading their prepared projection is one per-user/thread/skills-root critical
section, shared with acquire and release. The provider snapshots that canonical
root at startup and carries it through warm-pool identity and E2B metadata; a VM
from another root is never adopted. A second policy sync cannot reset the remote
tree until the first upload pass has completed.

An invalid mount does not block later mounts.

Each successful upload logs its source, destination, file count, byte count, and elapsed time.

A stopped pass logs its limit reason and elapsed time. It reports attempted and completed upload totals separately.

After creation, ``E2BSandbox.mount_upload_result`` holds a ``MountUploadResult``.
``result.truncated`` is true only for resource-limit stops (deadline, file count,
bytes), not logged mount failures (missing paths, SDK errors). A provider-level
map preserves creation results within the Gateway process; ``None`` on a
reclaimed sandbox means unavailable.
