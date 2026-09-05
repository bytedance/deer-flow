# DeerMem scope-isolation benchmark

This benchmark answers two questions about automatic long-term-memory writes:

1. Does the production extraction prompt classify durable user facts separately
   from task constraints, project rules, and one-time permissions?
2. Does the production DeerMem write path keep a fact inside its selected
   `(user_id, agent_name)` scope?

The protocol is intentionally small. It is a regression benchmark for the
scope-safety boundary, not a general memory-quality leaderboard.

## What it exercises

Each semantic case passes synthetic `HumanMessage` and `AIMessage` objects
through the public `DeerMem.add()` queue and `shutdown_flush()` lifecycle. The
normal updater builds the committed production prompt, parses the model output,
normalizes it, applies the deterministic scope gate, and writes to a temporary
`FileMemoryStorage` root. Assertions inspect only the resulting public memory
document.

The identity suite reuses the durable-preference write and probes the same
storage root through the public `get_memory()` API. It checks the source scope,
a second custom agent, the default-agent bucket, and another user. This keeps
the semantic and routing checks on one real write without adding paid calls.
Identity metrics inspect facts only: DeerMem summaries are intentionally
user-global and therefore are not an agent-isolation boundary.

The committed manifest uses unique `DFMEM_...` canaries and synthetic
identities. Public row files omit conversation text, prompts, current memory,
model responses, credentials, and provider headers.

## Run offline

From `backend/`:

```bash
uv run python -m scripts.benchmark.deermem_scope_isolation validate-contracts
uv run python -m scripts.benchmark.deermem_scope_isolation run-offline \
  --output-dir .tmp/deermem-scope-isolation-offline
```

Offline mode uses the manifest's deterministic model responses but still runs
them through the complete production DeerMem pipeline. It makes no provider or
dataset request and should produce perfect metrics.

## Run a live model

Configure a model in the normal DeerFlow model configuration, then run:

```bash
uv run python -m scripts.benchmark.deermem_scope_isolation run-live \
  --model your-model-name \
  --temperature 0 \
  --output-dir .tmp/deermem-scope-isolation-live
```

A complete live run makes six model calls. Each completed case is written
atomically under `responses/`, so rerunning the same command reuses valid rows.
The run directory is bound to the manifest hash, production-prompt hash, model,
and temperature. Changed settings require a new output directory. A malformed,
reassigned, or stale response row is called again instead of being trusted.

Recompute metrics from the public rows without calling a model:

```bash
uv run python -m scripts.benchmark.deermem_scope_isolation report \
  --output-dir .tmp/deermem-scope-isolation-live
```

## Metrics

- `durable_retention_rate`: eligible durable canaries that were stored.
- `unsafe_persistence_rate`: task, project, temporary, or transactional
  canaries that were incorrectly stored. Lower is better.
- `atomic_correction_success_rate`: corrections where the replacement was
  stored and the contradicted fact was removed together.
- `identity_retention_rate`: source-scope facts visible in their own scope.
- `cross_agent_contamination_rate`: source facts visible to another agent of
  the same user. Lower is better.
- `cross_user_contamination_rate`: source facts visible to another user. Lower
  is better.

Every metric stores its numerator and denominator. A zero denominator produces
`null`, never a misleading zero-percent rate.

## Protocol maintenance

`scope-isolation-v1.json` pins the SHA-256 of the production
`memory_update.chat.yaml`. If that prompt changes, contract validation fails.
Review the semantic cases and expected classifications before updating the
hash. A behavior or case-set change should normally use a new protocol ID so
results remain comparable.

The benchmark deliberately does not evaluate retrieval ranking, fact-capacity
eviction, shared summaries, additional memory backends, or UI behavior. The
DeerMem eviction benchmark covers capacity policy separately.
