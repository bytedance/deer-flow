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
the package.

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
- Secrets come from `.env` (or `rag_config.json` via the settings UI):
  `DASHSCOPE_EMBEDDING_API_KEY`, `DASHSCOPE_RERANK_API_KEY`, `MINERU_API_TOKEN`
  (plus `RAG_EMBEDDING_API_KEY` / `RAG_RERANK_API_KEY` / `RAG_SPARSE_API_KEY`
  fallbacks for non-DashScope providers).

## Develop / test

```bash
cd backend
uv run pytest tests/knowledge tests/test_knowledge_extension_packaging.py -q
uv run ruff check packages/knowledge-extension
```

The extension's chain can be re-generated with a programmatic alembic config
(`deerflow_knowledge/migrations/`, `script.py.mako` included); routine upgrades
run automatically at Gateway startup.
