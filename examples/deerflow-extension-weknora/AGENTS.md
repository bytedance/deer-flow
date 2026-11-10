# WeKnora read-only example

Provider code stays in this separately packaged extension. It registers through
`registry.knowledge_provider` and the public `deerflow.knowledge` contracts.
Core owns scope admission, formatting, budgets and citation evidence. Version
references, configuration and the authorization model are in `README.md`.

```bash
cd backend && python -m pytest tests -q -k "weknora"
```

Live tests need explicit opt-in and an instance that is already indexed. Do not
fabricate a live result.

## Scope and authorization

- **A missing binding, an invalid selection, an empty allowlist or an upstream
  failure never becomes an unrestricted search.**
- **Search goes through the KB-bound endpoint.** The global search endpoint
  rejects document targets for a KB-restricted key and unions base and document
  targets. Do not broaden credentials to work around that. Verify that each
  result belongs to the requested base.
- **`access_mode: users` needs exact user IDs.** `authenticated` mode needs a
  non-empty host authenticated user that equals the user ID. Do not infer a login
  from a default or storage ID or from serialized context.
- **Shared retrieval grants no management permission.**
- **Dataset IDs derive from endpoint, tenant and native base**, not from
  credentials or labels.
- **A malformed total or detail shape is a provider error.** Permission errors
  are for resource identity, membership and searchability failures.

## Wiki search and document checks

- **Wiki search covers published pages only.** Check the Wiki capability and the
  base of each returned page, and reject document filters before HTTP. The Wiki
  page-link graph is not a source of entity relations.
- **Only a successful empty page is retried with keywords**, in the same
  authorized base. Provider, auth and schema errors are not retried, and a
  non-empty phrase result stays as it is.
- **Validate selected documents before the search**, and after it validate only
  the hits that are returned. Drain sibling tasks on an error or a cancellation.
