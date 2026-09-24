# Full-stack plugin contributions

A deployment-installed Python extension can register a `PluginContribution` with
optional browser code, authenticated backend actions and model tools. This extends
the existing `install(registry, config)` workflow. MCP and Skills keep their existing
APIs and lifecycles. Public contracts live in `deerflow_extension_api` (0.2.3).

The browser contribution API is experimental. `BrowserModule(code=...)` remains the
self-contained transport; `BrowserAssets(root=...)` adds manifest-listed resources
without changing the page/action API or requiring a host frontend rebuild.

## What users see

Capability Center has an **Extensions** tab with read-only information and deployment
status. A plugin can add a conversation action, its own workspace page and an optional
sidebar entry. The [bookmarks example](../examples/deerflow-extension-bookmarks/README.md)
uses all three: save the last visible answer, then search, rename or delete it under
**My bookmarks**. Existing notification and Markdown/JSON export behavior is unchanged.

The [Jev context pruning example](../examples/deerflow-extension-jev-context/README.md)
combines a catalog contribution with public middleware hooks to shorten old read-only
tool results. It requires deployment opt-in and a separate Jev API key.

## Registration and execution

`registry.plugin(...)` returns `True` when accepted. Its default public protocol
implementation returns `False` on a host without support, so packages must check the
result. A declaration needs a unique namespace and at least one browser module,
backend action or tool. Validation happens before registration; install failures use
the existing positional rollback and source attribution.

- `BrowserModule(module, code, public_fields=())` contains a self-contained ES module,
  at most 512 KiB. It may export `surfaces` and `conversationActions` with `apiVersion: 1`.
- `BrowserAssets(module, root, manifest="ui_manifest.json", public_fields=())`
  loads a versioned resource manifest from an installed package (details below).
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

A plugin can also contribute tools alone. The
[text classification example](../examples/deerflow-extension-jev-classify/README.md)
registers one model tool and a status action, no browser code: the agent labels a
list of texts through a deployment-configured Jev or chat-model backend, and the
plugin keeps the whole call inside those bounds with its own batch and deadline
limits. It requires deployment opt-in and a separate backend API key.

Durable `batch_task` workers pin the Gateway app's extension snapshot at startup
and use it for both plugin tools and subagent execution. Recovered items use the
new worker's snapshot after restart; no Python snapshot is stored in the durable
`execution_spec`. Standalone batch services without an explicit snapshot capture
the process default once at construction.

## Browser API

The authenticated host exposes:

| Route                                                   | Purpose                                                         |
| ------------------------------------------------------- | --------------------------------------------------------------- |
| `GET /api/plugins`                                      | Deployed descriptors, public configuration and declared actions |
| `GET /api/plugins/modules/{module}/{sha256}.mjs`        | Installed code with a content revision                          |
| `GET /api/plugins/{namespace}/assets/{revision}/{path}` | One manifest-listed static resource                             |
| `POST /api/plugins/{namespace}/actions/{name}`          | Invoke one declared backend action                              |

The host does not accept filesystem paths, import strings or arbitrary remote URLs
from the browser. Inline modules use JavaScript content type and private no-store
caching; packaged assets use their declared file type and private immutable caching.
Both transports send `nosniff`. Existing Gateway session/CSRF policies apply; PATs do not gain a new
route allowlist. The browser sends its descriptor's viewer ID so the action route can
reject a stale view after account changes, in addition to normal request authentication.

Inline module downloads honor `NEXT_PUBLIC_BACKEND_BASE_URL`, including a path prefix,
and use the host's authenticated fetch helper before importing a temporary Blob URL.
The URL is released after import, including on failure. Browser modules must be
self-contained: relative imports and assets resolved against `import.meta.url` are
unsupported. Deployments with a Content Security Policy must allow `blob:` in
`script-src` and the configured backend in `connect-src`; split-origin backends must
allow credentialed CORS from the frontend, as for other host API calls.

A page surface declares `id`, `slot: "page"`, `title`, `mount(root, context)` and
optional `navigation: { label, labelZh?, icon? }`. The host generates the URL
`/workspace/extensions/{namespace}/{id}` and mounts only that registered page.
`mount` runs synchronously and returns an object `{ dispose }`, whose `dispose()` is called on unmount. The context includes locale,
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

## Packaged resources (`assets-v1`)

Register a package-owned directory alongside the Python implementation:

```python
from pathlib import Path
from deerflow_extension_api import BrowserAssets, PluginContribution

registry.plugin(PluginContribution(
    namespace="community.example",
    title="Example",
    frontend=BrowserAssets("example.v1", Path(__file__).parent),
))
```

Place `ui_manifest.json` at that root, and include it and every listed file in the
installed wheel. The [bookmarks package](../examples/deerflow-extension-bookmarks/README.md)
is a working example. Its manifest uses this schema:

```json
{
  "schema_version": 1,
  "entry": "static/dist/index.mjs",
  "files": [
    "static/dist/index.mjs",
    "static/dist/chunks/bookmarks.mjs",
    "static/dist/styles.css",
    "static/dist/bookmark.svg"
  ]
}
```

`entry` must be a listed `.js` or `.mjs` ES module exporting the existing browser
API v1 object. Relative static/dynamic imports and `new URL(..., import.meta.url)`
resolve within the revision's URL tree. Bundle third-party dependencies into the
package: bare npm imports and shared host React instances are not provided. Emit
relative URLs, not absolute `/assets/...` paths from a bundler's default public path.

The manifest accepts only `schema_version`, `entry` and `files`; unknown versions,
extra/duplicate keys, duplicate paths, missing files and symlinks are rejected at
registration. The declared root itself must not be a symlink (including a dangling
link); ordinary parent directory aliases are resolved before checking package files.
Paths use ASCII letters, digits, `_`, `-`, `.` and `/` separators;
segments must start with a letter, digit, `_` or `-`. Dotfiles, dot segments, empty
segments, percent encoding, query strings and backslashes are rejected. No directory
listing or unlisted file is served. Limits: 64 KiB manifest, 256 files, 4 MiB per
file and 16 MiB total per plugin. These limits bound the in-memory startup snapshot.

Supported types are JS/MJS, CSS, JSON/source maps, WASM, PNG/JPEG/GIF/WebP/SVG/ICO
and WOFF/WOFF2/TTF/OTF. HTML and executable server files are not served. SVG can
contain active document content, so asset responses carry
`Content-Security-Policy: sandbox`: direct navigation cannot execute scripts or
retain the Gateway's origin.
This document restriction preserves image, stylesheet and module subresource use;
it does not sandbox the plugin JavaScript deliberately loaded into the host page.
Do not list secrets or private build sources; any authenticated user can download listed assets,
including source maps, even when the contribution is disabled.

The host snapshots all listed bytes during registration and computes a SHA-256
revision over the manifest, paths and file content hashes. Changing any resource
changes every resource URL's revision. Requests read that immutable snapshot, not
the filesystem. Responses require authentication and send
`Cache-Control: private, max-age=31536000, immutable`, `Vary: Cookie, Authorization`
and the file's MIME type. Missing files/revisions return 404 with `private, no-store`.
There is no public CDN contract or retained historical snapshot. A browser can retain
already cached code after removal; uncached old resources require a page reload after
restart/upgrade. Installation and authorization are not instantaneous cache revocation.

Discovery labels the transport `inline-v1` or `assets-v1`. The frontend rejects unknown
transports and treats an omitted transport as legacy inline v1. Deploy the matching
host frontend/backend together before installing an assets-v1 plugin; this does not
make old host frontends support the new transport.

For packaged JavaScript the host inserts a native module script with
`crossorigin="use-credentials"`, then obtains exports from the document's module map.
This preserves authenticated static and lazy imports without rewriting source or Blob
URLs. See the [HTML module-script credential rules](https://html.spec.whatwg.org/multipage/scripting.html#attr-script-crossorigin).
URLs honor `NEXT_PUBLIC_BACKEND_BASE_URL`, including relative/absolute prefixes.
The host stops waiting after 30 seconds and rejects that contribution, removing its
loading script node. This is a waiting deadline, not execution cancellation: native
module fetching/evaluation can continue and top-level side effects can occur later.
A late completion cannot change the already rejected host result. Blocking synchronous
plugin code can also delay the deadline's timer. Trusted plugins should keep top-level
code free of user-visible side effects, start UI work in `mount` and release it in
`dispose`. This loader does not provide preemption, rollback or a security sandbox.

Module exports are shared within a document. Keep viewer data in per-mount state,
observe the host abort signal and clear it on dispose; never retain principals or
private results in module-level state across account changes.
Split-origin deployments need exact-origin credentialed CORS and working session
cookies; browser third-party cookie restrictions still apply.

Other resource requests are the plugin's responsibility: attach a stylesheet or image
with `crossOrigin = "use-credentials"`, and use `fetch(url, { credentials: "include" })`
for WASM, JSON or binary assets. CSS font/background requests do not universally carry
cross-origin session cookies. Prefer same-origin deployment for such CSS references,
or fetch with credentials and construct a `FontFace`/Blob URL, releasing it on dispose.
The host does not rewrite CSS URLs or add authorization tokens to URLs. CSP must allow
the backend origin in the applicable `script-src`, `style-src`, `img-src`, `font-src`
and `connect-src` directives. Inline-v1 still needs `blob:` in `script-src`.

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

`plugin-assets.spec.ts` also checks authenticated static/lazy imports, CSS and images,
plus direct SVG navigation through the real Gateway asset route. Its script-execution
control removes the sandbox header from the same SVG to verify the restriction.
To exercise the actual Turbopack development build, start the frontend with
`DEER_FLOW_DEV_BUNDLER=turbo pnpm dev`, then run
`PLAYWRIGHT_SKIP_WEB_SERVER=1 pnpm exec playwright test tests/e2e/bookmark-plugin.spec.ts`.
Set `PLAYWRIGHT_BASE_URL` if the development server uses a port other than 3000.
