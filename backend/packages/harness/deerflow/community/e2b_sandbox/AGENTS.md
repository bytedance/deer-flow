# E2B lifecycle

Reconciliation floors active-client TTL renewals at the SDK's default timeout
and twice the sum of the configured reconciliation interval and pass budget
(subject to the E2B timeout cap). Release still uses the configured idle timeout.
Sweeping old local warm entries must not release deployment capacity: a peer
may have renewed the VM. Leave shared removal to revision-checked remote
inventory and its missing-entry grace period; partial/failed inventory cannot
prove absence.
