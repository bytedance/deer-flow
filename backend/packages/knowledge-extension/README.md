# deerflow-knowledge-extension

The first-phase RAG knowledge base for DeerFlow, shipped as a plugin: document
ingestion (PDF / Word / Markdown / spreadsheets via MinerU) indexed offline into a
hybrid vector retrieval path (dense + sparse → RRF → rerank), exposed to a `rag`
custom agent as a single opt-in tool (`hybrid_search`).

## Install

The package lives in this repository as a workspace member
(`backend/packages/knowledge-extension`), so `uv sync --all-packages` in
`backend/` installs it alongside the host. For an external installation:

```bash
make extension-install SOURCE=packages/knowledge-extension
# or directly:
cd backend && uv add --project . --group extensions --no-workspace --no-sync -- packages/knowledge-extension
```

## Enable

Add the plugin record to `config.yaml` (the manager writes this for you on
`make extension-install`):

```yaml
plugins:
  - name: knowledge
    package: deerflow-knowledge-extension
    use: deerflow_knowledge.install:install
    enabled: true
    table_prefix: kb_
    config: {}
```

Until this record exists the extension is fully inert: no tables, no worker, no
probes, no routes. `enabled: false` keeps the same posture without uninstalling
the package. To take the feature down end to end, also set
`knowledge_base.enabled: false` in `config.yaml`: that is the hot-reloadable
flag the Gateway reports through `/api/features`, and with it off the workspace
hides the Knowledge entry and the frontend stops calling extension endpoints.
Either way the data stays; disabling never deletes rows or files.

## Tables

The extension owns its schema end to end — a private `MetaData`, never the host's
`Base`, so the host's empty-database `create_all` never creates these tables:

- `kb_knowledge_bases`, `kb_documents`, `kb_chunks`, `kb_eval_runs`
- bookkeeping in `kb_alembic_version` (its own chain, upgraded from
  `KnowledgeExtensionService.start()`; Postgres upgrades serialise with a
  dedicated advisory lock)

`table_prefix: kb_` tells the host's alembic autogenerate to leave those tables
alone. Disabling the extension keeps every row. Removing the plugin record stops
the prefix declaration and the chain; the tables remain until an operator drops
them deliberately (drop them only after confirming nothing else reads them).

## Runtime requirements

- **Qdrant** at `rag.qdrant_url` (default `http://localhost:6333`); the Gateway
  starts without it — documents fail per-item until it is reachable.
- **Spreadsheet parsing** (`python-calamine`) is a lazy dependency: it is
  deliberately outside the workspace lock. Install it in the environment that
  ingests `.xlsx`/`.xls` files: `uv pip install python-calamine`. Without it,
  table uploads fail with a clear parse error while everything else works.
- **Tokenizer cache** — chunking counts tokens with tiktoken (`cl100k_base`).
  Its BPE files are fetched on first use; air-gapped or restricted-network
  deployments must pre-seed the cache (`TIKTOKEN_CACHE_DIR`, or a primed image)
  or the first ingestion fails at the chunking stage.
- **Sandbox posture for the `rag` agent** — the built-in `rag` agent ships no
  per-agent skill files; on deployments configured with host bash
  (`sandbox.allow_host_bash: true` on the local provider) the upstream
  skill-isolation guard refuses to start that agent. Run knowledge-base chats
  with the default sandbox posture.
- Secrets come from `.env` (or `rag_config.json` via the settings UI):
  `DASHSCOPE_EMBEDDING_API_KEY`, `DASHSCOPE_RERANK_API_KEY`, `MINERU_API_TOKEN`
  (plus `RAG_EMBEDDING_API_KEY` / `RAG_RERANK_API_KEY` / `RAG_SPARSE_API_KEY`
  fallbacks for non-DashScope providers).

## Backup and restore

The extension ships **no** backup code: backups are an operator duty, like the
rest of the host. A complete backup contains:

- **Database rows** — the `kb_*` tables (knowledge bases, documents, chunks,
  eval runs), i.e. a copy of the host database or a dump of those tables.
- **Original files and images** — the knowledge directory under the data root
  (`data/knowledge/<kb_id>/<doc_id>/`).
- **Vector state** — either a Qdrant snapshot of the generation collections
  (`kb_chunks` plus any `_<width>` variants), or the *rebuild materials*: the
  chunk text (already in the database rows), the library's recorded embedding
  identity, and `rag_config.json`, which together allow a full re-embed.
- **Configuration** — `rag_config.json` (functional model targets and
  endpoints). Keep credentials in their own secret store.

Take database and files from one consistent point: stop the Gateway (or
quiesce knowledge writes) before copying, copy both, and verify the copies
with checksums before relying on them. SQLite: copy while no process is
writing; a hot copy can miss the WAL tail.

**Restore.** Stop the Gateway, restore database + files (+ the Qdrant snapshot
if that is what the backup carries), then start the Gateway. The worker
re-enqueues documents that were mid-processing at the snapshot, and a
per-library **Rebuild index** re-embeds everything from chunk text (no
re-parse) when the vector state is missing or came from another embedding
space.

Restoring an older snapshot brings back content that was deleted after it —
including deletions performed in the live system. Before reopening knowledge
reads and retrieval, review what the snapshot carried back and re-execute
those deletions; if that cannot be established, keep knowledge reads and
retrieval disabled and report why. A rebuild run after the deletions are
re-executed does not re-create deleted documents.

**Verify a restore** on three axes before declaring success: permissions (each
user sees exactly their libraries), query and citation (a known question
answers with the right source), and unfinished processing (a document that was
mid-flight at backup time completes after restart).

**Online cleanup vs history and backups.** Deleting a document or a library
clears the current business storage, files and vectors; excerpts already cited
in past conversations stay as they were, and existing backups keep the deleted
data until the retention period expires. Publish the retention period and
restrict who can read backups.

## Rebuild cost

A rebuild re-embeds every document that is not still mid-processing and writes
one upsert per embedding call. The call count is
`Σ ceil(chunks_of_document / batch)`, where `batch` is the model's per-call cap
(20 for `qwen3.7-text-embedding`; other DashScope models fall back to 10).
Reference measurement from the acceptance run: 18 documents / 264 chunks → 41
calls, work finished in well under a minute against a hosted endpoint, with the
worker picking the request up within about a minute. A fully completed rebuild
stamps the library's embedding identity; a partial run never does. The rebuild
entry is per library: **Settings → Models → Rebuild index**.

## Deployment positions and what leaves the environment

| Component | Where it runs | What leaves the deployment environment |
| --- | --- | --- |
| Parsing (PDF / Office / images) | configured MinerU service (cloud or self-hosted); text/markdown/tables parse locally | cloud service: the original file (its cloud flow includes object-storage upload); self-hosted or local parse: nothing |
| Embedding (dense + sparse) | configured provider (cloud or self-hosted) | cloud provider: chunk text and queries; self-hosted: nothing |
| Reranking | configured provider (cloud or self-hosted) | cloud provider: the query and candidate slices; self-hosted: nothing |
| Image captioning (VLM) | configured provider | cloud provider: image crops; self-hosted: nothing |
| Vector index | Qdrant at `rag.qdrant_url` | in-environment when run alongside; a Qdrant outside the environment receives vectors and payloads |
| Business data | host database (SQLite/Postgres) | nothing unless the database itself is remote |
| Files and images | data root on local/persistent disk | nothing; downloads go only to authorized users |

The settings surface for global model/service configuration is admin-only, and
secrets are masked on every read path, in logs, and in evaluation artifacts.

## Develop / test

```bash
cd backend
uv run pytest tests/knowledge tests/test_knowledge_extension_packaging.py -q
uv run ruff check packages/knowledge-extension
```

The extension's chain can be re-generated with a programmatic alembic config
(`deerflow_knowledge/migrations/`, `script.py.mako` included); routine upgrades
run automatically at Gateway startup.
