# Knowledge management example

An optional, separately installed extension that holds the management business
logic, the provider configuration and the HTTP API. Core retrieval never depends
on it. It uses the public principal and plugin authorization APIs and imports
nothing host-internal. Real validation results are in `VALIDATION.md`.

```bash
cd backend && python -m pytest tests -q -k "knowledge_management"
make test-blocking-io
```

Live tests need both `DEER_FLOW_RUN_LIVE_TESTS` and
`KNOWLEDGE_MANAGEMENT_ALLOW_WRITES`, a dedicated synthetic base and credentials
the caller supplies. Record mock coverage and real validation separately.

## Authorization

- **Administration is opt-in.** It needs an explicit grant for the exact user,
  base and operation, on top of the host administrator floor and the upstream
  authorization. A retrieval binding grants no write.
- **Identities come from the session.** Do not accept a user, tenant, agent or
  space identity from the client, widen a resource selection, follow a redirect
  that carries credentials, or fall back to other credentials.
- **Check document and base membership before a mutation.**
- **`routes_enabled: false` keeps the plugin namespace for downstream
  authorization** and mounts no route and no Provider. Disabling the whole
  install removes the namespace too.

## Writes and states

- **A write is never retried or cleaned up automatically.** Keep the native IDs,
  so an uncertain write can be reconciled.
- **A processing capability describes upstream configuration, not an observed
  success.** Unknown states stay unknown. A terminal parse status does not prove
  that Wiki or graph processing finished.
- **The WeKnora mappings are pinned to one upstream release.** On a parent-child
  base, reject chunk size and overlap overrides before the mutation, because
  upstream derives them on its own. Empty reparse options keep the stored
  policy.
- **Capability options reflect the fetched base.** Omit graph controls without
  graph support, and omit chunk overrides when the base has no chunking config or
  uses parent-child chunking.
- **Request bodies never carry credential, model or parser configuration.**
- **A local credential failure returns 503 before any HTTP call**, without
  reconciliation guidance, because no write was sent.
- **Failure logs hold the exception type, the numeric HTTP status and a fixed
  failure category.** Exception text, payloads, URLs and credentials stay out.
