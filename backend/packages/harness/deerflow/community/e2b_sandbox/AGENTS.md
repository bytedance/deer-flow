# E2B lifecycle

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

Shutdown owns both maintenance workers as well as sandbox registries. After
signalling the lease-renewal and reconciliation threads, a bounded join is only
a wait budget: verify each worker actually exited before clearing registries or
tearing down resources. If either worker is still alive, keep admission fenced
and preserve all tracked state so a later `shutdown()` can retry cleanup.
That fence covers cached sync/async acquisition too: recheck after serializer
waits and immediately before exposing a reused client. Signal-triggered shutdown
may report deferred cleanup, but it must still forward the process's original
SIGTERM/SIGINT/SIGHUP action while retaining the pending E2B state.

## File search

Quote the complete `grep --include=<pattern>` argument with `shlex.quote` before
passing it to the shell. The shell must not split or expand filename patterns;
grep owns basename globbing and `path_matches` owns root-relative directory
scoping. `tests/test_sandbox_search_contract.py` pins this across providers using
real temporary files and offline shell transports.
