# Optional knowledge platform extension

Stage 3 of [#6269's five-stage follow-up](https://github.com/bytedance/deer-flow/issues/6269#issuecomment-6281785410): platform connection policies, hierarchical logical spaces, members and explicit resource sharing. It composes the management contracts delivered by #7293 and installs no page, model tool, parser, index or Trace service. The existing retrieval and management extensions continue to work independently.

## Install and configure

From the repository root, install the local management package first so its source is available to the dependency resolver, then this package:

```sh
make extension-install SOURCE=./examples/deerflow-extension-knowledge-management
make extension-install SOURCE=./examples/deerflow-extension-knowledge-platform
```

The management namespace must be registered for the host's second authorization check. Enable its entry point with `routes_enabled: false` to retain that namespace without exposing direct management routes or requiring a second Provider configuration. Configure the platform entry point in operator-owned `config.yaml` and restart Gateway. Use an absolute private SQLite path on local storage. Multiple workers on the same machine can share that file; this is not a multi-host database service.

```yaml
plugins:
  - use: deerflow_extension_knowledge_management:install
    config:
      enabled: true
      routes_enabled: false
  - use: deerflow_extension_knowledge_platform:install
    config:
      enabled: true
      storage_path: /absolute/private/path/knowledge-platform.db
      connections:
        - id: reference
          provider: weknora
          # Another trusted module:factory can implement ManagementProvider.
          provider_factory: deerflow_extension_knowledge_management.weknora:WeKnoraManagement
          provider_config:
            connections:
              - id: reference
                base_url: https://weknora.example
                tenant_id: "1"
                api_key_env: WEKNORA_MANAGEMENT_KEY
                grants:
                  - user_id: exact-deerflow-admin-user-id
                    knowledge_base_ids: [native-base-id]
                    operations: [capabilities, status, manual, url, upload, reprocess, cancel]
          resources:
            - base_id: native-base-id
              # Obtain the exact ID from the existing retrieval catalog or a
              # management snapshot for this endpoint/tenant/native base.
              dataset_id: wk1_replace_with_the_existing_dataset_id
              operations: [capabilities, status, manual, url, upload, reprocess, cancel]
              tools: [knowledge_search, knowledge_entries_search]
```

Set the key only in the Gateway environment. IDs, Provider factories, endpoints, grants, resource allowlists and credential references are deployment configuration. HTTP can change connection display names, enabled state and policy within that envelope; it cannot create executable factories, change endpoints or grant new upstream credentials. Adding another Provider connection or upstream base requires an operator config change and restart. Do not reuse a connection ID for a different upstream endpoint/tenant: allocate a new ID and explicitly remap spaces. An invalid dataset mapping is rejected when validating the management response; after a mutation this may be an uncertain write requiring reconciliation.

Installation is disabled by default. Removing the entry point or setting `enabled: false` and restarting removes the routes without deleting the private policy database. Back up that database with normal SQLite backup procedures; do not commit it or expose it as a downloadable browser asset.

## Policy and API

All routes are under `/api/extensions/knowledge-platform`. Gateway authentication, CSRF protection for writes and the host's namespace-specific plugin management authorization apply. No request body supplies a user, Agent, tenant or credential. The plugin registers its namespace through `PluginContribution`; no new core registry is needed.

| Route | Purpose |
| --- | --- |
| `GET /policy` | Administrator-only policy snapshot, revision and operator resource identities; no provider config or secrets |
| `PUT /policy` | Administrator-only atomic replacement with the expected revision; `409` on a stale revision |
| `GET /spaces` | Current member's accessible space IDs, titles and roles; no other members' identities |
| `GET /spaces/{space}` | Current member's effective resources, operation/tool policy and processing defaults |
| `GET /spaces/{space}/resources/{resource}/capabilities` | Space policy intersected with actual management Provider capabilities |
| `POST /spaces/{space}/resources/{resource}/documents` | Existing URL/manual `IngestRequest`; `202` is a processing snapshot |
| `POST /spaces/{space}/resources/{resource}/files?filename=guide.txt` | Raw octet-stream, at most 16 MiB; optional `X-Processing-Options` |
| `GET /spaces/{space}/resources/{resource}/documents/{document}` | Existing `ProcessingResult`, including unknown states |
| `POST /spaces/{space}/resources/{resource}/documents/{document}/{reprocess\|cancel}` | Existing processing options and uncertainty semantics |

First read `/policy` to discover the `kp1_...` resource ID derived from `(provider, connection_id, native_base_id)`. This local mapping identity is separate from the retrieval `dataset_id`. Two connections with the same native base name do not alias. The server checks management response provider, connection, dataset and requested document identities; it never rewrites an unrelated response into the selected resource.

Submit the whole policy with the last observed revision. The initial revision is `0`. This example creates four levels; the protocol has no fixed hierarchy depth. The bounded store allows 500 total spaces, 200 members per space and 1 MiB of policy JSON. Space/connection names use bounded ASCII IDs; titles and exact host user IDs support Unicode.

```json
{
  "revision": 0,
  "policy": {
    "defaults": {"default_tool": "knowledge_search"},
    "connections": {"reference": {"title": "Team reference", "enabled": true}},
    "spaces": {
      "organization": {
        "title": "Organization",
        "resources": ["kp1_replace_with_resource_id_from_GET_policy"],
        "members": {"exact-deerflow-admin-user-id": "manager", "another-host-user-id": "viewer"}
      },
      "division": {"title": "Division", "parent_id": "organization"},
      "team": {"title": "Team", "parent_id": "division", "operations": ["capabilities", "status", "manual"]},
      "project": {"title": "Project", "parent_id": "team", "processing": {"summary_enabled": false}}
    }
  }
}
```

To share a base with another organization, an administrator explicitly adds the same resource ID to that root's envelope and assigns its members. Sharing no longer needs a duplicate base or an alias to a tenant. Child spaces inherit resources, operations, tools and members when fields are absent. An empty set removes access; an explicit child set must be a subset of the parent. Child membership can only narrow ancestor grants. Roles are `blocked`, `viewer`, `editor`, `manager`; viewers have only status/capability operations. Editors and managers can request configured management operations, but all actual management requests retain the additional administrator floor below. The `manager` label does not grant host administrator status or policy-edit privileges.

The entire updated tree is checked before publication: cycles, missing parents, unknown resources/connections and child permission expansion reject the transaction. Reparenting, deletion and ancestor restrictions must leave descendants valid; when necessary narrow descendant grants in the same replacement. Disabling an ancestor or connection denies future admissions. Policy writes use `BEGIN IMMEDIATE` and compare revisions inside the transaction, preventing lost updates across independent connections/processes. A Provider call already admitted by the platform is in flight and is not cancelled by a later policy change, including its internal HTTP checks. Removing operator resources denies affected spaces while administrators can still read the old policy/revision and `unavailable_resources` to reconcile it; unrelated spaces remain available.

Processing defaults merge in this order: platform → connection → ancestors → selected space → explicit ingestion options. These are defaults, not an authorization grant. Operation and tool permissions intersect; configuration inheritance cannot expand those permissions. Unsupported options fail before mutation. Empty reprocess options retain the existing document's upstream policy; new-document defaults are not silently applied to old documents. A selected default retrieval tool must remain in the effective tool envelope. An absent `default_tool` inherits; explicit `null` clears it, including when a child disables all tools. Policy round trips preserve this distinction.

## Authorization boundary

Space-routed management requires **all** of:

1. Host `knowledge-platform` plugin read/write authorization.
2. Host `knowledge-management` plugin read/write authorization, even if its direct routes are disabled.
3. A host-resolved human administrator and an effective space membership/operation grant.
4. The unchanged management adapter's exact-user, native-base and operation grants.
5. Upstream resource authorization, including document/base membership checks.

The same principal is passed to the Provider. No member is promoted to an administrator, and no fallback credential or automatic write retry exists. A space grant alone cannot authorize an upstream mutation. Non-admin members can inspect their effective policy when the host grants platform read permission; they cannot invoke the initial administrator-only management backend. Enabling non-admin management or upstream per-user delegation requires a separate reviewed authorization change.

**This plugin enforces space policy on its own routes.** Tool/default policy in its effective projection is for future consumers; installing it does not reroute `knowledge_search`, modify saved `knowledge_scope`, add a chat space selector or change existing citations. Existing direct management routes keep their independent administrator grants. If every management request must cross space admission, keep its namespace entry point enabled with `routes_enabled: false` and expose only this plugin's management routes. Space sharing neither grants chat retrieval nor removes an independently configured retrieval grant. Do not present this plugin as a global retrieval ACL.

Management responses preserve #7293's contract: capability is not observed execution, `202` is not completion, searchable is not success of every Wiki/graph step, and unknown stays unknown. Writes are never retried. On timeouts, lost/malformed responses or identity mismatches, reconcile with the selected upstream base before submitting again. There is no exactly-once ledger. Errors omit provider messages/credentials; database or Provider exceptions are not exposed to clients. See [CONTRACT.md](CONTRACT.md) for the fourth/fifth-stage handoff.

SQLite failures, including an exhausted busy timeout when workers share the policy file, return a sanitized `503` without database paths or exception details. Reload the policy and its revision before deciding whether to retry a policy update; ingestion and processing writes are never automatically retried.

Policy evaluation resolves each ancestor once within the current snapshot, combines processing defaults per connection and reuses resource-envelope checks. Space listing performs the same admission checks as space details without constructing their resource/processing responses. These temporary calculations are discarded after each call; grants are never cached across requests or revisions.

## Verification

```sh
uv run --no-sync --project backend pytest backend/tests/test_knowledge_platform_extension.py -q
uv run --no-sync --project backend pytest backend/tests/blocking_io/test_knowledge_platform_extension.py -q
```

The offline tests use real SQLite, FastAPI routing and the existing WeKnora management adapter with synthetic HTTP responses. They establish policy enforcement and contract composition, not real ingestion/extraction quality or production identity integration. [VALIDATION.md](VALIDATION.md) records the checks and current acceptance boundary. The earlier `superbuzzy/deer-flow` branch informed the space/resource separation; its core persistence, old Provider loader and 512-character scope IDs are not transplanted into main.
