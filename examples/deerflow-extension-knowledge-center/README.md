# Optional knowledge center extension

First usable UI slice of phase 4 in [#6269's five-stage plan](https://github.com/bytedance/deer-flow/issues/6269#issuecomment-6281785410), consuming the platform and management APIs merged in #7417 and #7293. This browser-only Full-Stack Plugin registers an independently enabled page. It adds no Provider, credentials, parser, document store, model tool or authorization bypass.

## Installation

From the repository root:

```sh
make extension-install SOURCE=./examples/deerflow-extension-knowledge-center
```

Install and configure the [knowledge platform](../deerflow-extension-knowledge-platform/README.md) and [knowledge management](../deerflow-extension-knowledge-management/README.md) separately. The management namespace must remain enabled; its direct routes may be disabled with `routes_enabled: false`. Add this entry alongside those entries in operator-owned `config.yaml`, then restart Gateway:

```yaml
plugins:
  # Keep the separately configured management and platform entries here.
  - use: deerflow_extension_knowledge_center:install
    config:
      enabled: true
```

The only page setting is boolean `enabled` (default `false`). Endpoints, keys, factories and identities are rejected. The package requires the host's optional `SurfaceContext.requestBackend` introduced with this example; older hosts display an update message. Open **Knowledge center / 知识中心** in the workspace sidebar, or `/workspace/extensions/knowledge-center/library`.

Set `enabled: false`, disable the entry point, or uninstall and restart Gateway to remove the page entry. Reload browser tabs to refresh discovery. This does not disable the platform/management API, delete policy data or upstream documents, or affect chat retrieval. Page hiding is not authorization. Installing the UI without the platform displays an unavailable state.

## Use and behavior

1. Choose an accessible space and mapped knowledge base. The current projection supplies native base IDs rather than human base titles; the selector preserves them and distinguishes connections. Empty membership/resource sets have explicit next steps.
2. The server intersects space policy with actual Provider capabilities. Non-admin members can browse effective resources but see no management controls when management authorization fails. Capability discovery is not a write grant: every server request still checks the real user, both plugin namespaces, space policy and unchanged Provider grants.
3. Import text, an HTTP(S) URL or a nonempty file up to 16 MiB using supported operations. Supported processing options preserve explicit `false` and validate paired chunk fields. Omitted new-document options inherit platform defaults. Files use the existing raw upload route, without base64 or plugin-action size limits.
4. Inspect returned document snapshots or look up an existing document by upstream ID. Refresh is explicit. Reprocess/cancel require inline confirmation; reprocessing sends empty options to preserve upstream settings. Document read ordering prevents an older status response from replacing a newer processing response.

Requests use the configured Gateway URL, host credentialed CSRF fetcher, page cancellation signal and descriptor-bound viewer header. Gateway rejects stale viewers before contributed routes run, including when another tab switches accounts. Redirects are rejected; writes are never automatically retried.

After **any failed submitted write**, the page warns that the Provider may already have accepted it and disables further writes until the user explicitly acknowledges upstream reconciliation. Check the upstream directory or query status first. Capability rejection before submission does not submit a write. Leaving the page can abort the browser wait but cannot cancel an already accepted upstream operation.

## Delivery boundary

- This is the first phase-4 slice, not the whole phase. The current management contract has no complete document/task listing, independent entry browsing/editing/versions or graph browsing API. The page explains unavailable features without inventing directories, graphs or editing endpoints. These require follow-up reviewed Provider contracts.
- At most 50 snapshots are held **for the selected resource during this visit**. They are not a durable task ledger. Reload, space/resource changes, unmount and account changes discard state. No user content is stored in localStorage/sessionStorage.
- Unknown stays unknown; `202` is not completion. `searchable` never implies all Wiki/graph/summary steps succeeded. No percentages, step timelines, elapsed times or Trace events are fabricated. Phase 5 still needs real events.
- This page does not edit platform policy/membership, create upstream bases, change chat scope, grant retrieval access or impersonate upstream users. Existing retrieval works independently.

## Verification

```sh
cd backend
uv run --no-sync pytest tests/test_knowledge_center_extension.py tests/test_auth_middleware.py tests/test_knowledge_platform_extension.py -q
cd ../frontend
pnpm check
pnpm exec rstest run tests/unit/core/extensions
pnpm exec playwright test tests/e2e/knowledge-center.spec.ts
```

Tests load the real extension/static registry, exercise Gateway authentication middleware over HTTP (including root paths and stale viewers), and load shipped native browser modules through the real host with mocked management HTTP. This is synthetic contract coverage, not a live WeKnora or production multi-user acceptance claim. Results are recorded in [VALIDATION.md](VALIDATION.md).
