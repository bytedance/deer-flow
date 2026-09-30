# Capability Center integration contract

Capability Center is a discovery and configuration layer over DeerFlow's existing
MCP, Lark CLI, and skill services. It uses the existing administrator/user roles.
Agent selections configure the tools and skills assembled for a run; they are not
an authorization boundary. Customer-specific authorization can remain in the
existing policy extension points.

Skill installation discovery applies the same caller visibility policy as
`/api/skills`, including its configured fail-open or fail-closed behavior.
Public host APIs for skill evolution (mutation transactions, completed-task
snapshots, evaluation runners, lifecycle events and command registration) are
deferred to a separate proposal and PR.

## Ownership

| Concern | Owner |
| --- | --- |
| Catalog and localized metadata | `backend/packages/harness/deerflow/capabilities/builtin.json` |
| Validated manifest schema | `deerflow.capabilities.catalog.PluginManifest` |
| Installation/status adapters | `backend/app/gateway/capabilities.py` |
| Catalog and safe discovery HTTP API | `backend/app/gateway/routers/capabilities.py` |
| Personal MCP settings, secrets, enable/delete | `/api/mcp/personal/config` and `.deer-flow/users/<user_id>/integrations/mcp.json` |
| Deployment MCP settings and cache reload | Administrator-only `/api/mcp/config` and `extensions_config.json` |
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
Center → Plugins** using your own account:

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
record. Connections created under **My plugins** are personal: credentials,
enabled state and edits belong to the signed-in user, including administrators.
They are stored under `.deer-flow/users/<user_id>/integrations/mcp.json` and
remain masked in the editor. Existing deployment connections in
`extensions_config.json` stay shared and are not copied to any personal account.
The page separates **Platform provided** (deployment setup guides and shared MCP
entries) from **My plugins** (personal connections, configuration templates and
Lark account authorization). Existing search and category filters apply to both.
Administrators can add, edit, toggle and delete shared MCP entries under
**Platform provided**. These changes apply to all users; ordinary users see
shared entries read-only.
Edit, toggle and delete personal entries using the existing MCP controls.
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

The MCP form saves a personal HTTP endpoint and Authorization header.
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
- `POST /api/capabilities/installations`: installation dispatch with `plugin_id`,
  `name`, adapter `configuration`, and optional `scope` (default `deployment`).
  Deployment scope requires an administrator; authenticated users may choose
  `scope: "user"` for MCP and bundled business connections. Other adapters
  still require an administrator. MCP configuration uses
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
and legacy derived IDs. Creation, replacement and state changes reject collisions
before saving. Deletion still validates the configuration schema but permits
remaining ID collisions: administrators can remove entries one at a time, even
with multiple independent collision pairs. Other writes remain blocked until
those collisions are repaired; deletion never changes surviving connection IDs.
Old ambiguous configurations remain visible with `selectable: false` and `health: ambiguous`;
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

## Personal and deployment MCP configuration

`config.yaml` tools and existing `extensions_config.json` MCP servers remain
platform-provided capabilities. The administrator-only `/api/mcp/config` API
continues to manage deployment MCP configuration.

The web editor uses `/api/mcp/personal/config`: GET reads only the authenticated
user's definitions; POST `/servers`, PUT `/server`, PATCH and DELETE
`/servers/{name}` manage that same user's file. No caller-supplied user ID selects
the owner. Catalog installation accepts `scope: "user"`; catalog discovery
accepts `scope=user` or `scope=all` (deployment plus the caller's connections).
The default API scope remains deployment for existing integrations.

Personal files use the existing atomic file writer and cross-process lock. Keep
`DEER_FLOW_HOME` on persistent storage; multiple Gateway workers must share it.
Personal values are literal and cannot read deployment environment variables.
A missing personal connection never falls back to a same-named shared one.
Personal tools are discovered per run, outside the process-wide platform cache.
Calls check ownership and the current stored revision. Credential edits, disable
and delete invalidate already assembled personal tools; restart the run after
an edit. Durable tasks bind the same owner and connection revision, including
after recovery; changing that connection blocks its pending remote calls until
the original configuration is restored.

Allowing personal configuration does not grant host execution privileges:
ordinary users may configure public HTTP/SSE endpoints and the fixed bundled
business launchers. Arbitrary stdio commands, internal endpoints and OAuth token
endpoints still require an administrator. Public endpoints are checked again on
HTTP requests, with redirects and environment proxies disabled.

Connections saved with administrator privileges require the owner's current
administrator role during discovery and before every tool call, including
durable submit, poll and cancel calls. Demotion, account deletion or an authority
lookup failure blocks those connections even if tools or callers are cached.
The owner can save a compatible connection again under ordinary-user policy.
Gateway workers query current account records; standalone hosts must install
an authority lookup to use privileged personal definitions. Already admitted
operations are not forcibly terminated by a subsequent role change.
