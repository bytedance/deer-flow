# E2B lifecycle

Reconciliation floors active-client TTL renewals at the SDK's default timeout
and twice the sum of the configured reconciliation interval and pass budget
(subject to the E2B timeout cap). Release still uses the configured idle timeout.
Sweeping old local warm entries must not release deployment capacity: a peer
may have renewed the VM. Leave shared removal to revision-checked remote
inventory and its missing-entry grace period; partial/failed inventory cannot
prove absence.

Use the existing AcquireSerializer's two-part ("sandbox", id) keys for active
TTL writes, release, warm cleanup, and ownership publication/renewal. Recheck
snapshots after taking that lock. Lock order is thread key, VM key, then the
provider state lock; remote IO must not hold the provider state lock. Release
must own the final idle-TTL write, and cleanup must finish before a new lease
can be published. Do not renew ownership removed by a concurrent cleanup.
Release only needs the VM lock while leaving active state; do not hold it
during output sync, which must not prevent ownership heartbeats.
Track that release in `_remote_ops_in_progress` until it completes so
reconciliation cannot probe or re-adopt a VM between active and warm states.
