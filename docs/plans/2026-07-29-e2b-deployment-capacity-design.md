# E2B Deployment-Wide Capacity Design

Issue: [#4339](https://github.com/bytedance/deer-flow/issues/4339)

## Scope

#4391 already provides process-local atomic capacity and the `wait`, `reject`,
and bounded `burst` policies. This change adds only the remaining
deployment-wide admission boundary for Gateway workers that already share
Redis ownership.

It does not add per-user quotas, fair scheduling, or shared capacity for other
sandbox providers.

## Selected approach

Each ownership namespace uses one Redis Hash:

```text
<ownership.key_prefix>:e2b-capacity

meta:state           initializing | ready
meta:hard_limit      3
meta:revision        12
r:<token>            <created-at-ms>
s:<sandbox-id>       1
```

The effective hard limit is `replicas`, plus `burst_limit` only under the
`burst` policy. Lua atomically adds a reservation only while:

```text
count(r:*) + count(s:*) < hard_limit
```

A successful E2B create replaces its reservation with the returned sandbox ID.
Confirmed remote destruction removes the sandbox ID. Discovery and ownership
takeover only upsert the existing ID, so routing a thread through another
Gateway does not consume a second slot.

## Crash recovery

New E2B sandboxes carry the ledger key and their reservation token in remote
metadata. The existing bounded E2B reconciliation pass snapshots the Hash
revision, lists remote sandboxes from that ledger, then applies the inventory
only if no concurrent structural mutation changed that revision.

A complete inventory may remove missing sandbox IDs and old reservations. An
incomplete or failed inventory never frees capacity. This repairs the two
important crash windows:

- Redis reservation succeeded but no E2B VM exists.
- E2B creation succeeded but the Gateway died before Redis commit.

The Hash has no TTL. Redis errors and missing/uninitialized state fail closed
for new creates; already-running VMs are not killed because Redis is
unavailable.

## Alternatives rejected

- A single integer counter cannot be reconciled safely after a Gateway crash.
- Listing E2B before every create is not atomic across Gateways.
- A generic multi-backend ledger duplicates #4391 and adds abstraction not
  required by this issue.

## Tests

Focused coverage verifies:

- two Redis clients cannot both reserve the last slot;
- stale inventory cannot erase a concurrent reservation;
- remote metadata repairs create/commit crashes;
- incomplete inventory retains capacity;
- Redis failure and configuration mismatch fail closed;
- two provider instances share the hard limit and do not over-create;
- capacity is released only after confirmed remote destruction.
