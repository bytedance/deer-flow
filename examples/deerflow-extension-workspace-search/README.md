# Workspace message search

Adds message-body search to the workspace Search / ⌘K / Ctrl+K panel. The host
provides title search, permission checks, highlighted excerpts and deep links;
this package maintains the rebuildable message index. Requires a host with the
extension-api 0.2.12 workspace search contribution.

From the repository root, install through the existing extension manager:

```sh
make extension-install SOURCE="$(pwd)/examples/deerflow-extension-workspace-search"
```

Add `table_prefix: extension_workspace_search_` to the resulting `plugins:` entry
in `config.yaml`, then restart Gateway. A manually managed installation uses:

```yaml
plugins:
  - name: workspace-search
    package: deerflow-extension-workspace-search
    use: deerflow_workspace_search:install
    enabled: true
    table_prefix: extension_workspace_search_
    config:
      path: .deer-flow/workspace-search.db
```

The application database is reused when configured. `path` is only the fallback
SQLite index location for an in-memory application database. Index tables contain
message text and follow the same storage access controls as conversation data.

Search uses case-insensitive literal substrings, including Chinese, filenames
inside messages and code identifiers. SQLite uses FTS5 trigram acceleration when
available; one/two-character queries use a literal scan. PostgreSQL uses escaped
literal matching with a GIN trigram index when `pg_trgm` is already installed.
The extension never installs database extensions. Artifact names outside message
text, tool output, hidden controls, internal reasoning and subagent logs are excluded.

The first nonempty message search starts an owner-scoped historical backfill.
Requests wait at most one second and report indexing progress until ready. Later
searches compare thread revisions and rebuild changed threads; deletion, editing
and regeneration are reconciled before matching. The host rereads every candidate
from visible history before showing its excerpt. The index is not an authorization
source. Both default and custom-agent conversations preserve their own routes.

The current refresh reads revision metadata for all of the searching user's
threads. Very large histories may spend longer in the indexing state; no external
search service or background worker is required. Searches have cursor pagination
ordered by title match, thread update time and message sequence.

Validation: `backend/tests/test_workspace_search.py` covers memory, JSONL and
SQLite histories, Unicode/symbol queries, ownership, filters, index refresh and
historical windows. `frontend/tests/e2e-real-backend/workspace-search.spec.ts`
drives the real Gateway and frontend with synthetic history. Run the replay
Gateway with `--workspace-search` to enable this provider in that isolated stack.

Review follow-up behavior: message jumps use a single owned thread lookup, and
latest message versions win across storage pages. Legacy checkpoint-only
threads are seeded through the host history-migration reservation before
indexing. SQL membership checks use batches of 250 thread IDs. Clean SQLite
FTS projections survive restart; literal-fallback writes mark the projection
dirty and the next FTS-capable startup repairs it.

Title matching keeps Python Unicode casefold semantics across SQL dialects,
including German sharp-s. It scans metadata in batches of 200 and stops once
the requested result page is filled; a no-match query can still scan the
owner's title metadata.
