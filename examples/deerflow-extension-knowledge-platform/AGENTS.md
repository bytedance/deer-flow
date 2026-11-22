# Knowledge platform example

An optional plugin that keeps platform connections, logical spaces and upstream
tenants separate. It uses the public principal and plugin authorization APIs and
the existing management Provider. It adds no second ingestion implementation and
no knowledge or ACL registry in core, and imports nothing host-internal.

Tests use real SQLite and real HTTP routing and mock only the upstream
transport. Report real upstream acceptance separately from synthetic coverage.

## Authorization

- **Every policy write needs the host administrator floor and the platform
  write grant.**
- **A space-routed management request needs four more checks**: the management
  namespace grant, explicit space membership, the resource and operation policy,
  and the Provider's own authorization for the exact user, base and operation.
- **Config, defaults and resource references are not grants.** Inherited child
  sets and members stay within the limits of their ancestors.
- **Do not create an administrator, accept an identity from the client, widen a
  filter, substitute credentials or retry a mutation.**
- **Grants are never cached across requests.** Resolve ancestors step by step
  inside one policy snapshot.
- **Space policies apply to this plugin's routes only.** The plugin claims no
  global retrieval ACL, no upstream user impersonation and no multi-host
  replication.

## Storage

- **Provider factories and their configuration are operator-only.** HTTP policy
  never stores credentials, endpoints or factory paths.
- **Filesystem and SQLite work runs off the request loop**, with a strict
  blocking-I/O test for each new path.
- **No database transaction is held across a Provider HTTP call.**
- **A SQLite failure maps to a sanitized 503.** An update is retried only after
  the policy was reloaded.
- **Resource identity is qualified by provider, connection and native base.**
  Presence of a policy or a capability never implies processing success or
  progress.
