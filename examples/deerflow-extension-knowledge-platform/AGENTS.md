# Knowledge platform

Keep platform connections, logical spaces and upstream tenants separate. This
optional plugin uses public principal/plugin authorization plus the existing
management Provider; do not introduce a second ingestion implementation or core
knowledge/ACL registry. No host-internal imports.

All policy writes require the host administrator floor and platform write grant.
Every space-routed management request additionally requires the management
namespace grant, explicit space membership, resource/operation policy and the
unchanged Provider's exact-user/base/operation authorization. Never manufacture
an administrator, accept client identities, silently widen filters, substitute
credentials or retry a mutation. Config/defaults and resource references are not
grants; inherited child sets/members must remain within ancestor limits.

Executable Provider factories/configuration are operator-only. HTTP policy must
never persist credentials, endpoints or factory paths. Use absolute private
SQLite storage, transactional revision checks and bounded validated snapshots.
Run all filesystem/SQLite work off async request loops; add strict blocking-I/O
regressions. Do not hold a database transaction across Provider HTTP calls.
Map SQLite failures to a sanitized 503; require policy reload before retrying
an update and never automatically retry Provider mutations.
Resolve ancestors incrementally within one policy snapshot. Never cache grants
across requests. Space listing must share detail admission checks without
materializing per-resource processing responses or repeating ancestor merges.

Keep resource identity provider/connection/native-base-qualified and bounded;
preserve retrieval dataset IDs and validate management result identities. Space
policies apply only to this plugin's routes. Do not claim global retrieval ACL,
upstream user impersonation, management pages, Trace or multi-host replication.
Never infer processing success or progress from policy/capability presence.

Tests use real SQLite and HTTP routing, mock only upstream transport. Real
upstream acceptance must be explicitly distinguished from synthetic coverage.
