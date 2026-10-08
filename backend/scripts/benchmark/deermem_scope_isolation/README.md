# DeerMem scope-isolation benchmark

This is a focused regression benchmark for DeerMem's long-term-memory safety boundary. It is not a model leaderboard. It measures two separate concerns:

1. **Semantic model quality**: whether the production extraction prompt classifies durable user facts for admission while rejecting project/thread constraints, temporary instructions, and transactional authorization.
2. **Deterministic identity routing**: whether a write made through the production queue/storage boundary reaches only the selected `(user_id, agent_name)` bucket.

The benchmark imports DeerMem's production `MemoryUpdater`, extraction prompt loader, response normalizer, scope gate, `MemoryUpdateQueue`, and file storage. It does not copy their policy logic.

## Protocol

`manifest.json` is a versioned synthetic contract. Every fact contains a unique, non-sensitive canary. The semantic suite covers a durable preference, a project constraint, one-run authorization, a file-local correction, an atomic durable correction, and a mixed durable/transient turn. The routing suite bootstraps a custom agent bucket and checks the default agent, a sibling agent, and the same agent under another user.

The five reported metrics are:

- `durable_retention_rate`
- `unsafe_persistence_rate`
- `atomic_correction_success_rate`
- `cross_agent_contamination_rate`
- `cross_user_contamination_rate`

Semantic model-quality results and deterministic routing results remain in separate report sections. Retrieval ranking/recall is deliberately out of scope; this protocol checks admission and identity routing, not search quality.

Semantic verdicts inspect persisted facts and all user/history summaries, including summary-only contamination. Routing verdicts inspect facts only: summaries are intentionally shared across agents belonging to the same user.

## Offline run (default)

From `backend/`:

```bash
python -m scripts.benchmark.deermem_scope_isolation validate
python -m scripts.benchmark.deermem_scope_isolation run-offline --output-dir scripts/benchmark/deermem_scope_isolation/runs/offline-v1
python -m scripts.benchmark.deermem_scope_isolation report --output-dir scripts/benchmark/deermem_scope_isolation/runs/offline-v1
```

Offline mode uses committed deterministic model outputs but still executes the production prompt, normalization, scope gate, queue, and temporary file storage. It does not read provider environment variables or perform network calls.

## Explicit live run

Live mode evaluates only semantic extraction quality. Provider credentials stay in a named environment variable and are never written to artifacts:

```bash
python -m scripts.benchmark.deermem_scope_isolation run-live \
  --output-dir scripts/benchmark/deermem_scope_isolation/runs/live-v1 \
  --provider openai \
  --model YOUR_MODEL \
  --api-key-env YOUR_API_KEY_ENV \
  --base-url-env YOUR_OPTIONAL_BASE_URL_ENV
python -m scripts.benchmark.deermem_scope_isolation report --output-dir scripts/benchmark/deermem_scope_isolation/runs/live-v1
```

The command name makes live execution explicit. A missing key fails before model construction. The run marker records only provider/model settings and environment-variable names, never credential values, endpoints, prompts, conversations, or model response text.

## Reproducibility and resume integrity

Each output directory receives a `run.json` marker bound to the manifest hash, bundled extraction-prompt hash, source Git revision, execution mode, and model settings. Each case is persisted immediately as one row with a fingerprint that also binds its expected outcome and a result-integrity hash over the row. Only an intact matching row is reused on resume; changed protocol artifacts, source revision, prompt, mode, model settings, or row contents require a new row or output directory.

Rows contain synthetic canary verdicts, rendered-prompt hashes, non-secret model metadata, and usage only. `report` validates every row against the current protocol and recomputes metrics. It refuses to overwrite an existing report, preserving the original evidence.

Failed memory updates (including provider, response-parsing, and storage failures) abort the run with a nonzero exit rather than sealing an ordinary result. Completed rows remain reusable; rerunning retries the failed case. Reports reject incomplete runs and unsuccessful rows instead of counting them as successful rejections. Row schema v2 includes summary-aware verdicts; older rows are never reused or graded. Source-revision changes still require a new output directory.
