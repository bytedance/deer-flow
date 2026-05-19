# RAG / Knowledge Base Operations

Operator-facing reference for tuning the indexing pipeline, choosing a cross-KB scoring strategy, and recovering from embedding-model migrations. Code-level architecture lives in [backend/CLAUDE.md → RAG / KB Indexing](../CLAUDE.md). The full design + sprint history is in [docs/plans/2026-05-19-knowledge-base-usability-improvement-design.md](../../docs/plans/2026-05-19-knowledge-base-usability-improvement-design.md).

## 1. Pipeline Overview

```
upload → DocumentRepository (status=pending) → IndexingDispatcher.submit()
                                                         │
                                                  asyncio.Queue
                                                         │
                                                 worker pool (×N)
                                                         │
                  with_kb_context(tenant_id, user_id) ───┤
                                                         │
                                            IndexingService.execute_index_job
                                            ├── DocumentIngestor (chunk → embed)
                                            └── ChromaVectorStore.add()
```

Three invariants the dispatcher enforces:

1. **Idempotency** — `(kb_id, doc_id, version)` is held in an in-memory `_inflight` set. Clicking "Reindex" twice in quick succession produces one queued job, not two.
2. **Crash recovery** — `submit()` writes `index_status=pending` *before* enqueueing. `recover()` re-enqueues anything still `pending` / `indexing` after a restart. `execute_index_job` is idempotent (deletes old chunks before writing new), so re-running a partially completed job is safe.
3. **Tenant isolation** — every job runs inside `with_kb_context(tenant_id=..., user_id=...)`. Without this wrap, the worker would resolve `tenant_id="default"` inside Chroma and silently mix every tenant's vectors into one bucket.

## 2. `cross_kb_score_strategy` — choosing between `comparable` and `raw`

`multi_kb_retrieve` merges chunks from multiple KBs. When two KBs use the same embedding model the scores are directly comparable; when they use *different* models, the raw provider scores are not on the same scale and naive merging gives whichever model returns larger numbers an unfair advantage.

| Strategy | What it does | When to use |
| --- | --- | --- |
| `comparable` (default) | Rescales scores from each KB to a `[0, 1]` post-hoc band before merging. Slight loss of absolute precision; cross-KB ranking becomes meaningful. | Production, especially when the user has KBs created against different embedding providers (e.g. a local nomic-embed KB plus an OpenAI text-embedding-3-large KB). |
| `raw` | Preserves each provider's raw similarity score; merges by sort order alone. Faster, no precision loss, but cross-KB ranking is meaningless when models differ. | Single-model deployments where every KB is guaranteed to share an embedding model — typically internal/dev setups. Also useful when downstream code wants the original scores for thresholding. |

**Tradeoff in one line**: `comparable` is correct-by-default; `raw` is faster but only safe under a homogeneous embedding policy.

To change: edit `config.yaml`:

```yaml
rag:
  cross_kb_score_strategy: comparable  # or "raw"
```

The setting is read per-call by `multi_kb_retrieve`, so a config reload picks it up without a restart.

## 3. Reindex-All SOP (embedding model migration)

When you change a KB's embedding model — or you change the global `rag.embedding_model` and want existing KBs to follow — you must rebuild the vectors. New documents always embed with the KB's bound model; old vectors don't auto-migrate.

**Endpoint**: `POST /api/knowledge-bases/{kb_id}/reindex-all` (admin or KB owner).

**What it does**, in order:

1. Marks every document in the KB as `index_status=pending` (UI shows a "rebuilding" badge).
2. Calls `ChromaVectorStore.delete_collection(...)` to drop the old vectors. **This is the destructive step** — until step 4 finishes, the KB returns zero retrieval results.
3. Clears `embedding_dim` on the KB row so the next successful index lazily re-binds it.
4. Bumps `version` on every document and dispatches one indexing job per document via the standard `IndexingDispatcher`.

**Operator checklist**:

- [ ] Confirm `rag.indexing_workers > 0` before triggering — with the dispatcher disabled, every doc runs inline and a large KB will block the request thread.
- [ ] If you are switching to a different embedding *provider* (e.g. local → OpenAI), update the KB's `embedding_model` column **before** triggering — otherwise the rebuild uses the old binding and the migration is a no-op.
- [ ] Watch `index_status` counts via the KB detail API. The endpoint returns `{kb_id, doc_total, doc_queued, doc_failed}` for the kickoff result, but completion is asynchronous.
- [ ] Expect the KB to be temporarily empty between steps 2 and 4 finishing. Schedule reindex-all during low-query hours; communicate the window to anyone relying on retrieval.
- [ ] If a doc lands in `failed` after the rebuild, check the dispatcher worker log for `EmbeddingDimensionMismatchError` — usually means the KB's `embedding_dim` was hand-edited and no longer matches the model's output.

**Rollback**: there is none — the old Chroma collection is deleted in step 2. Take a Chroma snapshot before triggering reindex-all on a production KB.

## 4. Common Failure Modes

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `RuntimeError: ... refusing to resolve collection name with tenant_id='default'` | A background task ran without restoring the submitter's tenant context. Usually a code path that bypassed `IndexingDispatcher` and didn't wrap its work in `with_kb_context`. | Wrap the call site in `deerflow.rag.job_context.with_kb_context(tenant_id=..., user_id=...)`. The error message names the offending caller. |
| Documents stuck in `index_status=pending` after an upload | Dispatcher disabled (`rag.indexing_workers=0`) **and** the inline fallback in `KnowledgeBaseService._run_index_job` errored. | Tail the gateway log for the inline-execution traceback. Set `rag.indexing_workers > 0` once the bug is fixed so future jobs go through the queue. |
| `EmbeddingDimensionMismatchError` on a doc but the KB previously indexed fine | The KB's `embedding_model` config drifted from what `embedding_dim` was originally measured against. | Run `POST /api/knowledge-bases/{kb_id}/reindex-all` to re-bind. |
| Cross-KB retrieval returns results dominated by one KB even though all KBs have similar content | `cross_kb_score_strategy=raw` with KBs using different embedding models. | Switch to `comparable`, or migrate the lagging KB to the same embedding model. |
| Upload to KB returns `422` with `code=EMPTY_RESULT` | Document is image-based / scanned and neither `pymupdf4llm` nor `markitdown` could extract text. | Either OCR the document client-side and re-upload as text, or check `GET /api/system/pdf-converter` to confirm the right backend is installed (Sprint C.3.3). |
| All PDF uploads fail | `pdf_converter` is configured against a backend whose package is missing. | Hit `GET /api/system/pdf-converter` — the response carries a `warning` describing which `pip install` command fixes it. |

## 5. Related Files

- `packages/harness/deerflow/knowledge_base/dispatcher.py` — async pump
- `packages/harness/deerflow/knowledge_base/service.py` — public KB API + `_run_index_job` inline fallback
- `packages/harness/deerflow/knowledge_base/indexing.py` — single-job execution + dimension binding
- `packages/harness/deerflow/knowledge_base/retrieval.py` — `multi_kb_retrieve` cross-KB merge
- `packages/harness/deerflow/rag/job_context.py` — `with_kb_context` tenant restoration
- `packages/harness/deerflow/rag/backends/chroma.py` — default-tenant guard
- `packages/harness/deerflow/rag/embeddings.py` — `get_embedding_provider(model_spec)`
- `app/gateway/routers/knowledge_bases.py` — REST surface (incl. `reindex-all`)
- `app/gateway/routers/system.py` — `GET /api/system/pdf-converter`
