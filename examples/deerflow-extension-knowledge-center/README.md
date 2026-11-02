# Optional knowledge center extension

The optional phase-4 page in [#6269's five-stage plan](https://github.com/bytedance/deer-flow/issues/6269#issuecomment-6281785410), consuming the platform and management extensions. It provides a document directory, processing controls, Wiki entry editing and version history, and entity-relation queries with graph/evidence views. This browser-only Full-Stack Plugin registers an independently enabled page. Provider adapters remain in the management package; the browser contains no credentials or document store.

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

1. Choose an accessible space and mapped knowledge base. The selector starts with native IDs and adds the provider's title once a library response arrives, preserving connection identity. Empty membership/resource sets have explicit next steps.
2. The server intersects space policy with actual Provider capabilities. Non-admin members can browse effective resources but see no management controls when management authorization fails. Capability discovery is not a write grant: every server request still checks the real user, both plugin namespaces, space policy and unchanged Provider grants.
3. Import text, an HTTP(S) URL or a nonempty file up to 16 MiB using supported operations. Supported processing options preserve explicit `false` and validate paired chunk fields. Omitted new-document options inherit platform defaults. Files use the existing raw upload route, without base64 or plugin-action size limits.
4. Inspect returned document snapshots or look up an existing document by upstream ID. Refresh is explicit. Reprocess/cancel require inline confirmation; reprocessing sends empty options to preserve upstream settings. Document read ordering prevents an older status response from replacing a newer processing response.
5. Open **Documents** to search the provider directory, paginate and filter processing state, then select a document to inspect or manage its processing. Reload re-reads the provider rather than a browser task ledger.
6. Open **Knowledge entries** to search/paginate Wiki pages, edit title/content and inspect historical snapshots. Restoring requires confirmation and a current-version guard; it restores title/content/summary as a new version. Oversized or credential-bearing editable content is rejected rather than silently truncated or replaced. Drafts lock resource selection and warn on ordinary link navigation/reload. Save/discard before leaving: drafts are not persisted, and programmatic host navigation is outside this plugin's guard.
7. Open **Entities and relations**, enter a query and inspect the bounded graph, accessible entity list, relation descriptions and retrieved evidence. Only real returned edges are drawn. Evidence joins only returned `source_id`/`chunk_id`; an absent quotation is explicitly marked. Layout and missing edges carry no semantic claim.

Upgrade management and platform packages to **0.1.1** for library routes. New operations require explicit operator grants and an explicit resource operation ceiling. See [library contract and configuration](../deerflow-extension-knowledge-management/LIBRARY.md), including the optional LightRAG connection. Unavailable capabilities display an explicit state without an upstream request; ingestion-only Providers remain compatible.

Requests use the configured Gateway URL, host credentialed CSRF fetcher, page cancellation signal and descriptor-bound viewer header. Gateway rejects stale viewers before contributed routes run, including when another tab switches accounts. Redirects are rejected; writes are never automatically retried.

After **any failed submitted write**, the page warns that the Provider may already have accepted it and disables further writes until the user explicitly acknowledges upstream reconciliation. Check the upstream directory or query status first. Capability rejection before submission does not submit a write. Leaving the page can abort the browser wait but cannot cancel an already accepted upstream operation.

## Delivery boundary

- WeKnora v0.8.3 supplies document directories and Wiki pages/versions. It has no stored **entity-relation** query API: `/wiki/graph` is a page-link graph and is not substituted. Configure the optional LightRAG library Provider for entity graphs. Every Provider need not support every page.
- Processing management uses provider document states plus reprocess/cancel. It is not a system-wide queue inspector or an attempt history. Phase 5 remains responsible for real spans, retries and diagnostics.
- At most 50 snapshots are held **for the selected resource during this visit**. They are not a durable task ledger. Reload, space/resource changes, unmount and account changes discard state. No user content is stored in localStorage/sessionStorage.
- Unknown stays unknown; `202` is not completion. `searchable` never implies all Wiki/graph/summary steps succeeded. No percentages, step timelines, elapsed times or Trace events are fabricated. Phase 5 still needs real events.
- This page does not edit platform policy/membership, create upstream bases, change chat scope, grant retrieval access or impersonate upstream users. Existing retrieval works independently.

## Verification

```sh
cd backend
uv run --no-sync pytest tests/test_knowledge_center_extension.py tests/test_knowledge_library.py tests/test_knowledge_management_extension.py tests/test_knowledge_platform_extension.py -q
cd ../frontend
pnpm check
pnpm exec rstest run tests/unit/core/extensions
pnpm exec playwright test tests/e2e/knowledge-center.spec.ts
```

Tests load the real extension/static registry, exercise Gateway authentication middleware over HTTP (including root paths and stale viewers), and load shipped native browser modules through the real host with mocked management HTTP. This is synthetic contract coverage, not a live WeKnora or production multi-user acceptance claim. Results are recorded in [VALIDATION.md](VALIDATION.md).

Screenshots: [English desktop / dark](screenshots/library-en-dark.png) and [Chinese mobile / light](screenshots/library-zh-mobile.png), rendered with synthetic data through the host sidebar entry point.
