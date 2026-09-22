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
