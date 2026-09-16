# Capability Center integration contract

Capability Center is a discovery and configuration layer over DeerFlow's existing
MCP, Lark CLI, and skill services. It uses the existing administrator/user roles.
Agent selections configure the tools and skills assembled for a run; they are not
an authorization boundary. Customer-specific authorization can remain in the
existing policy extension points.

## Ownership

| Concern | Owner |
| --- | --- |
| Catalog and localized metadata | `backend/packages/harness/deerflow/capabilities/builtin.json` |
| Validated manifest schema | `deerflow.capabilities.catalog.PluginManifest` |
| Installation/status adapters | `backend/app/gateway/capabilities.py` |
| Catalog and safe discovery HTTP API | `backend/app/gateway/routers/capabilities.py` |
| MCP settings, secrets, enable/delete, cache reload | Existing `/api/mcp/config` services and `extensions_config.json` |
| Lark installation and personal account authorization | Existing `/api/integrations/lark` services |
| Skill archives, enable state, user storage | Existing `/api/skills` services |
| Agent selection | Agent config `mcp_plugins` and existing `skills` |
| Integration-specific UI | `frontend/src/components/workspace/capabilities/plugin-adapters.tsx` |

There is no second credential database, background plugin daemon, executable
package loader, or remote marketplace dependency. The operator Python extension
loader is separate from this user-facing directory.

## Bundled business integrations

Three entries ship working API clients with the harness, using the `business`
configuration adapter and the existing stdio MCP runtime. No separate service,
package download, or Dify runtime is needed. Configure them under **Capability
Center → Plugins** as an administrator:

| Plugin | Configuration | Tools |
| --- | --- | --- |
| DingTalk group notifications | The robot webhook's `access_token` and signing secret; enable signing in the robot settings | `send_message`: text or Markdown to that group |
| WeCom group notifications | The `key` parameter from the group robot webhook URL | `send_message`: text or Markdown to that group |
| HubSpot CRM | A private app access token | `get_companies`: paginated company list; `create_contact`: create a contact by email and optional profile fields |

HubSpot needs `crm.objects.companies.read` for company queries and
`crm.objects.contacts.write` for contact creation. A read-only token can be used
when only company lookup is needed; the provider rejects unauthorized writes.
Notifications do not read chats, documents, or calendars and do not configure
DeerFlow's incoming IM channels. Existing manually configured CLI connections
are not rewritten when the catalog entry changes.

Configuration saves credentials without sending a message or creating a CRM
record. These deployment credentials are shared by runs allowed to use the
configured MCP server; they are not personal OAuth connections. Credentials
remain in the existing MCP `env` configuration and its masked admin editor.
Edit, toggle and delete the configured entry using the existing MCP controls.
An Agent selects these connections through **Plugins and skills**, just like
other MCP servers. New tool selection applies on the next run.

`deerflow.capabilities.business` implements fixed HTTPS provider endpoints,
bounded responses and timeouts, no redirect following or automatic write retries,
and validates the robot's `errcode` even on HTTP 200. Errors omit provider bodies
and credential-bearing URLs. Tool schemas never include credentials. An exact
`sys.executable -I -m deerflow.capabilities.business <provider>` launcher with
only the provider's known credential environment keys is accepted by the MCP
API; arbitrary interpreter paths/modules/flags/environment remain rejected.
The isolated interpreter ignores the working directory and Python environment
injection. If a deployment moves its Python environment, enabling an old launcher
returns a targeted error with the current interpreter path. Edit that connection's JSON
and replace only `command` with the indicated path; preserve its capability
metadata and masked credentials. This repairs the connection in place without
changing its installation ID or existing Agent selections.

The implementation is independently written against the provider contracts;
Dify's plugins informed the feature scope, not the source implementation:
[DingTalk](https://open.dingtalk.com/document/orgapp/custom-robot-access),
[WeCom](https://developer.work.weixin.qq.com/document/path/91770),
[HubSpot companies](https://developers.hubspot.com/docs/api-reference/legacy/crm/objects/companies/guide),
[HubSpot contacts](https://developers.hubspot.com/docs/api-reference/legacy/crm/objects/contacts/create-contact).

## Add a catalog entry

Add one object to `builtin.json` and, optionally, a licensed local image under
`frontend/public/images/plugins/` (record its source in that directory). Ordinary
HTTP MCP entries reuse the `mcp` adapter and form; the gallery needs no changes.
For example:

```json
{
  "schema_version": 1,
  "id": "example-search",
  "version": "1",
  "name": {"en-US": "Example Search", "zh-CN": "示例搜索"},
  "description": {"en-US": "Search the team knowledge base."},
  "setup": {"en-US": "Supply your administrator-provided MCP endpoint."},
  "category": "knowledge",
  "kind": "mcp",
  "adapter": "mcp",
  "source": "https://example.com/docs/mcp",
  "auth_methods": ["none", "api_key"],
  "contributions": ["tools"],
  "config_schema": {
    "type": "object",
    "properties": {
      "name": {"type": "string", "title": "Connection name"},
      "url": {"type": "string", "title": "Server URL"},
      "authorization": {"type": "string", "title": "Authorization header", "format": "password"}
    },
    "required": ["name", "url"]
  }
}
```

`kind` describes the execution mechanism, `auth_methods` describes supported
account mechanisms, and `adapter` selects the integration flow. `guide` entries
only link to setup instructions; listing them never claims they are installed.
The catalog version describes this manifest, not a remotely detected server
version. A catalog listing does not install, enable, or authorize anything.

The first MCP form supports HTTP endpoints and a deployment Authorization header.
The advanced JSON editor retains stdio, SSE, OAuth token configuration, and
per-user credential mappings supported by the existing MCP runtime. The presence
of `oauth` in a manifest is not a new interactive OAuth implementation. Lark
continues to use its existing personal account flow.

For a new integration protocol, implement the `CapabilityAdapter` interface,
register it once in `AdapterRegistry`, and register its settings component in
`pluginSettingsAdapters` when it requires a dedicated flow. Reuse the owning
service's authorization and validation; never add a provider branch to the gallery.

## API and state

- `GET /api/capabilities/catalog`: validated bundled manifests.
- `GET /api/capabilities/installations/{adapter}`: safe installation projections
  for `mcp`, `business`, `lark`, and `skills`; separate requests isolate integration failures.
- `POST /api/capabilities/installations`: administrator installation dispatch.
  Body: `plugin_id`, `name`, and adapter `configuration`. MCP configuration uses
  the existing server definition schema. HTTP/SSE connections require a valid
  HTTP(S) URL without embedded credentials; stdio connections require a command.
  Invalid transport configuration returns 422 before saving. Duplicate server
  names return 409.
- Existing owner APIs perform edit, enable/disable, uninstall, skill import/export,
  and account authorization. Query invalidation refreshes discovery after writes.

Discovery excludes MCP endpoints, commands, environment variables, headers,
OAuth secrets, and per-user credential mappings. `configured` means credentials
are present; it does not mean a connection test succeeded. `health: unknown`
is deliberate when no live check has run. Lark's existing configuration dialog
owns live account verification.

## Compatibility and execution

Catalog-installed MCP servers carry `capability: {id, plugin_id, version}` as
non-executable metadata in the existing config. Transport builders ignore it.
Configuration edits preserve installation identity, including edits by older
clients that omit metadata. Old entries get a deterministic ID from the existing
server key without rewriting files on GET. No provider identity is inferred from
a display name, including when choosing brand icons. Multiple installations of
one provider remain separate rows.

Installation IDs must be unique across all servers, including disabled entries
and legacy derived IDs. MCP writes reject collisions before saving. Old ambiguous
configurations remain visible with `selectable: false` and `health: ambiguous`;
explicit Agent selections load none of the colliding connections. Remove a
conflicting entry or repair the deployment configuration before selecting it.
The inherited-all mode retains its previous behavior.

`mcp_plugins: null` (or omitted) keeps the previous behavior: all enabled MCP
servers. `[]` selects none. A list selects installation IDs. Missing or disabled
installations provide no tools; their IDs stay in Agent configuration so editing
other settings cannot silently broaden the selection. The same semantics apply
to the existing skill-name selection. A selection never enables a disabled tool
or grants access to another user's account.

The lead Agent filters tools by their MCP source metadata. Ordinary delegated
and durable batch tasks carry the selection in their execution metadata. Each
Agent run gets a filtered list without altering the shared MCP tool cache.
The settings dialog omits unchanged plugin and skill selections on save, so an
unrelated edit does not overwrite a concurrent capability selection.
Existing skill policy, user-scoped MCP authentication, and tool execution guards
continue to run. Changes take effect on subsequent runs.

## Static demo

The read-only demo bundles a generated snapshot of the gateway catalog. After
editing `builtin.json`, run `cd frontend && pnpm catalog:sync`; the frontend unit
tests check that the snapshot matches the source. This keeps Docker and standalone
frontend builds independent of the backend source tree. Installation
projections come from existing same-origin MCP, Lark and Skills mock fixtures;
they do not require a running gateway. Demo projections omit credentials and
connection details, set `can_manage: false`, and do not imply live verification.
Writes still return 405 locally.

## Validation

Focused backend coverage includes real HTTP install/edit/delete against a
temporary config, role checks, secret-free discovery, identity preservation,
Agent persistence, delegated selection, and a real local stdio MCP invocation.
Browser tests cover catalog installation, Agent selection save/reopen, existing
icon editing, filtering, and desktop/mobile settings layouts. Browser fixture
screenshots show sample integrations; they are not production default settings.
