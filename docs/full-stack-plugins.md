# Full-stack plugin contributions

A deployment-installed Python extension can register a `PluginContribution` with
optional browser code, authenticated backend actions and model tools. This extends
the existing `install(registry, config)` workflow. MCP and Skills keep their existing
APIs and lifecycles. Public contracts live in `deerflow_extension_api` (0.2.2).

The browser contribution API in this slice is experimental. `BrowserModule(code=...)`
is an MVP transport for validating page/action host interfaces, not the final asset
packaging contract or a requirement that all future plugins ship one JavaScript file.

## What users see

Capability Center has an **Extensions** tab with read-only information and deployment
status. A plugin can add a conversation action, its own workspace page and an optional
sidebar entry. The [bookmarks example](../examples/deerflow-extension-bookmarks/README.md)
uses all three: save the last visible answer, then search, rename or delete it under
**My bookmarks**. Existing notification and Markdown/JSON export behavior is unchanged.

## Registration and execution

`registry.plugin(...)` returns `True` when accepted. Its default public protocol
implementation returns `False` on a host without support, so packages must check the
result. A declaration needs a unique namespace and at least one browser module,
backend action or tool. Validation happens before registration; install failures use
the existing positional rollback and source attribution.

- `BrowserModule(module, code, public_fields=())` contains a self-contained ES module,
  at most 512 KiB. It may export `surfaces` and `conversationActions` with `apiVersion: 1`.
- `BackendAction(name, handler)` declares an async handler receiving a JSON object and
  `ActionContext(principal, settings)`. The principal comes from host authentication.
- `ModelTool(name, description, input_schema, handler, group="extensions")` declares
  an async handler with a `ToolContext` that additionally carries the thread ID.
  Object schemas must be inline: reference resolution is rejected. Tools enter the
  ordinary host tool assembly, including group filtering and later authorization.
- `SettingsField` describes a non-secret deployment value. There is no online override
  store or settings write API. Browser clients see only `enabled` and explicitly
  listed public fields. Plugin code remains responsible for business authorization.

Tool names are namespace-derived and collision-checked. Tool inputs are bounded to
256 KiB, outputs to 64 KiB and execution to 30 seconds. Backend actions accept object
inputs up to 256 KiB and have a 30-second timeout. Cancellation does not guarantee
rollback of external effects or already-running worker-thread operations.

Durable `batch_task` workers pin the Gateway app's extension snapshot at startup
and use it for both plugin tools and subagent execution. Recovered items use the
new worker's snapshot after restart; no Python snapshot is stored in the durable
`execution_spec`. Standalone batch services without an explicit snapshot capture
the process default once at construction.

## Browser API

The authenticated host exposes:

| Route                                            | Purpose                                                         |
| ------------------------------------------------ | --------------------------------------------------------------- |
| `GET /api/plugins`                               | Deployed descriptors, public configuration and declared actions |
| `GET /api/plugins/modules/{module}/{sha256}.mjs` | Installed code with a content revision                          |
| `POST /api/plugins/{namespace}/actions/{name}`   | Invoke one declared backend action                              |

The host does not accept filesystem paths, import strings or arbitrary remote URLs
from the browser. Asset responses use JavaScript content type, `nosniff` and private
no-store caching. Existing Gateway session/CSRF policies apply; PATs do not gain a new
route allowlist. The browser sends its descriptor's viewer ID so the action route can
reject a stale view after account changes, in addition to normal request authentication.

Module downloads honor `NEXT_PUBLIC_BACKEND_BASE_URL`, including a path prefix,
and use the host's authenticated fetch helper before importing a temporary Blob URL.
The URL is released after import, including on failure. Browser modules must be
self-contained: relative imports and assets resolved against `import.meta.url` are
unsupported. Deployments with a Content Security Policy must allow `blob:` in
`script-src` and the configured backend in `connect-src`; split-origin backends must
allow credentialed CORS from the frontend, as for other host API calls.

A page surface declares `id`, `slot: "page"`, `title`, `mount(root, context)` and
optional `navigation: { label, labelZh?, icon? }`. The host generates the URL
`/workspace/extensions/{namespace}/{id}` and mounts only that registered page.
`mount` returns a synchronous `dispose()` callback. The context includes locale,
public settings, an abort signal and a namespace-bound `callBackend` helper.
The optional `openConversation(threadId)` host helper reads current conversation
metadata through the authenticated API and uses the host's normal/custom-agent
routing rules. Missing or inaccessible conversations reject without navigating;
unmount/account changes abort pending reads and prevent late navigation. Cleanup
aborts outstanding work and fences late callbacks. Plugin async work should observe
the signal and release resources in `dispose()`.

Conversation actions receive a conversation context and host services. The
`latestVisibleAnswer` and `conversationText` services reuse the existing export
sanitizer; sidebar reads go through the authenticated conversation API. Plugin code
must still escape user/model text when rendering it.
Factories and availability callbacks must be synchronous; invalid Promise returns
are rejected and their rejections consumed. The host validates each locale-dependent action group and evaluates availability
inside a per-plugin error boundary. A malformed or throwing contribution is omitted
without removing healthy plugin actions or failing the conversation page. Plugin tool
names that collide with ordinary tools follow the host's ordinary-first deduplication;
unrelated tools remain available. Duplicate names within the plugin tool set still fail
strict validation.

## Packaged assets and compatibility direction

RFC #5510 proposes a manifest plus packaged static resources (`ui_manifest.json` and
`static/dist/...`). That remains the intended direction for larger plugins. The current
single-file transport cannot naturally support relative chunks, separate CSS, images,
fonts, WASM, source maps or `import.meta.url` assets, and holds the module as a Python
string. Its `no-store` response intentionally provides no immutable cache reuse.

A follow-up should add a distinct, versioned packaged-asset declaration alongside the
inline form, rather than silently changing the meaning of `BrowserModule.code`:

- A validated manifest identifies the entry module and permitted files under a
  package-owned asset root. The root comes from the installed package, never a browser
  supplied filesystem path.
- Namespace/revision-scoped URLs, for example
  `/api/plugins/{namespace}/assets/{revision}/{path}`, must confine canonical paths to
  that root, reject traversal and escaping symlinks, and serve only manifest-listed
  files with correct MIME types and `nosniff`.
- Revisioned assets should support immutable caching. Private assets must retain
  authentication and private-cache policy; public/CDN caching needs an explicit public
  distribution contract. Cache invalidation and removal semantics must be specified.
- Entry modules and relative dependencies must share an authenticated loading design
  for both same-origin and split-origin deployments. The current Blob importer cannot
  simply be reused for relative chunks; an authenticated same-origin asset proxy is
  one option to evaluate.
- Discovery should negotiate the supported transport/version and reject unsupported
  transports clearly. Existing inline v1 packages should keep working while the new
  transport reuses the namespace, page/action interfaces and deployment lifecycle.

These are compatibility requirements for the follow-up, not implemented asset APIs.
The stable packaging contract requires review before plugin authors rely on it. Neither
transport should require rebuilding DeerFlow's frontend for each compatible plugin.

## Trust and lifecycle

**Browser and Python plugins are trusted operator-installed code.** Browser modules
run in the main page. Shadow DOM scopes CSS; it is not a security sandbox, and a
plugin can access same-origin browser capabilities. No shared React instance is
promised: plugins mount their own DOM rather than providing a component for the
host React tree. Sandboxed iframes, right-side panels, composer selection and version
negotiation beyond API v1 checks are follow-up designs discussed in #5510 and #5539.

Install, remove, enable/disable or upgrade with the existing deployment/CLI workflow
and restart the service. Python packages must be delivered into the actual execution
environment. Once this host contract is installed, a new compatible plugin does not
require plugin-specific host frontend compilation. Container delivery still needs a
persistent package installation or an image containing the package.

Browsers retain their discovered plugin set until manual refresh; there is no automatic
refresh or hot-unload guarantee. Old UI does not guarantee old backend code is retained
across a service restart. A changed asset revision or removed action fails explicitly
and requires reload. Disabled/unloaded pages have no navigation entry after refresh;
visiting an unavailable page directly does not mount a plugin.

## Validation scope

The bookmark E2E test runs the production frontend against real Python action handlers
and SQLite, with synthetic authentication and scripted LangGraph ToolNode calls.
It covers persistence, owner isolation, read-only deployment management and the full
page workflow. It does not claim live model behavior or a full production deployment.
The example uses single-host storage, not a multi-node persistence contract.
