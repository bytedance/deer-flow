# Platform-space handoff, version 1

This is an extension-owned contract, separate from core retrieval and the management Provider protocol. Resource references are not grants. A logical space is not an upstream tenant, connection, dataset or user's identity.

## Management and pages

Read the administrator policy using its revision, edit it, then submit an atomic replacement. `409` requires reloading and reconciling; never silently overwrite another administrator's change. The policy can enable/disable declared connections and constrain operations/tools/defaults, not create new executable Provider configurations. Provider settings and credentials stay operator-owned.

`GET /spaces` and `/spaces/{space}` use the authenticated host principal and return only authorized projections. `operations` is a **space policy ceiling**, not proof of Provider support or host/admin authorization. Actual capabilities require the space resource capability endpoint, which rechecks both plugin namespaces, the administrator floor, space membership and the existing Provider's resource grant. Pages must distinguish a visible policy from permission to submit a write. Hiding a page is never a server authorization check.

Processing/default configuration is inherited, while resource/operation/tool permissions can only narrow. Child membership cannot exceed ancestor membership. An ancestor restriction that invalidates descendant declarations must narrow those declarations in the same atomic update; disabled ancestors/connections deny all new requests. Editing the policy is restricted to host administrators with platform write permission, regardless of a member's `manager` label.

`resource_id` is a bounded hash of `(provider, connection_id, native_base_id)`, not a replacement retrieval scope ID. Keep `dataset_id` unchanged and preserve the existing management response's `document_id`. Management results cannot create citations or retrieval permissions. Retries of uncertain writes still need upstream reconciliation.

## Trace and retrieval consumers

This stage does not emit processing spans, run IDs or fabricated task history. Use real management snapshots and the original Provider contract. A future Trace implementation must independently authorize access and consume actual events; it cannot infer step success from platform capability, default configuration or terminal document state.

No current chat tool consumes these space grants. Any future retrieval consumer must explicitly bind trusted user/executor/space context, intersect operator and upstream authorization, honor all selected document filters and validate sources through existing contracts. A client space ID, raw resource mapping or tool name alone must never confer access.

The policy revision identifies a checked snapshot, not a durable execution lease. Mutations recheck policy after the upstream capability lookup before submission. The last platform admission check is the boundary: later revocation does not cancel an admitted Provider call, including its internal HTTP checks or upstream processing. There is no exactly-once admission promise or cross-host policy replication.
