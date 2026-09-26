# Memory System Improvements

This document tracks memory injection behavior and roadmap status.

## Status (As Of 2026-03-10)

Implemented in `main`:
- Accurate token counting via `tiktoken` in `format_memory_for_injection`.
- Facts are injected into prompt memory context.
- Facts are ranked by confidence (descending).
- Injection respects `max_injection_tokens` budget.

Planned / not yet merged:
- TF-IDF similarity-based fact retrieval.
- `current_context` input for context-aware scoring.
- Configurable similarity/confidence weights (`similarity_weight`, `confidence_weight`).
- Middleware/runtime wiring for context-aware retrieval before each model call.

## Current Behavior

Function today:

```python
def format_memory_for_injection(memory_data: dict[str, Any], max_tokens: int = 2000) -> str:
```

Current injection format:
- `User Context` section from `user.*.summary`
- `History` section from `history.*.summary`
- `Facts` section from `facts[]`, sorted by confidence, appended until token budget is reached

Token counting:
- Uses `tiktoken` (`cl100k_base`) when available
- Falls back to a network-free CJK-aware character estimate if tokenizer import or encoding load fails
  (CJK characters count as ~2 chars/token, other characters as ~4 chars/token)

## Extraction cost gate (opt-in, off by default)

`memory.prescreen` decides whether a batch of new conversation is worth paying
for the extraction LLM call; `memory.signal_classification` adds model hint
labels (and, in one narrow case, vetoes a skip). Both are off by default, and
`off` resolves no class path, constructs no provider and validates no credential.

Modes:

| Setting | Modes | Effect |
|---|---|---|
| `memory.prescreen.mode` | `off` / `shadow` / `enforce` | `shadow` records the verdict and extracts as usual; `enforce` lets a low-probability batch skip the call **and advance the watermark** (that batch is then consumed as "nothing durable here") |
| `memory.signal_classification.mode` | `off` / `shadow` / `hints` | `hints` merges `reinforcement` / `correction` labels into the extraction hint text and, only while the pre-screen is `enforce`, vetoes a skip |
| `memory.signal_classification.combine` | `auto` / `always` / `never` | Whether the two sides share one request. `auto` shares only when every effective client setting matches (model, base URL, credential fingerprint, timeouts, retries, `max_state_chars`, cache settings); `always` fails at construction on a mismatch; `never` always splits |

Failure direction is always extraction: an error, timeout, unusable response,
missing verdict, provider exception, or an over-limit batch extracts as usual.
Nothing is truncated to fit a limit. A skip changes **no** post-extraction gate
(confidence, scope, durability, authority, dedup, capacity eviction) and is not a
safety boundary.

Batches that are never judged: no judge configured; the emergency
(pre-summarization) flush; the shutdown drain (`flush_sync`, whose budget belongs
to persistence); batches with a **deterministic** signal on the feed (a positive
signal outranks a model negative); and any batch while
`staleness_review_enabled` (default **true**) or `consolidation_enabled` is on,
because a skip would also skip that batch's maintenance review. With the shipped
defaults the pre-screen therefore sees no batches until `staleness_review_enabled`
is turned off — do that deliberately, with the evaluation below.

**Egress.** The formatted conversation text (user plus final assistant turns, which
may contain file paths or credentials) is sent to the TypeSafe API: a second
destination beyond the deployment's own extraction model. Existing memory, fact
ids and tool arguments are never sent. `pii_redaction_middleware` does not cover
this path. `mode: off` is the rollback: no request, no behavior change, no data
migration.

**Before `enforce`.** Run the shadow evaluation and publish its gates:
`miss_rate` (a skip on a batch whose extraction would have been accepted) at or
below 1% with a confidence upper bound, zero misses on the identity / preference
/ correction strata, at least 200 reviewed skips whose manual review confirms
none was worth remembering, and the recorded savings evidence — calls and tokens
saved, their p50/p95 verdict latency, and the no-network heuristic baseline on the
same data; if the heuristic already captures the savings, the third-party call is
not justified. `scripts/eval_memory_prescreen.py` reads
shadow records and reports those populations and gates, and reports a gate that
lacks evidence as `INSUFFICIENT` rather than passing it. `skip_threshold` (0.2)
and `hint_threshold` (0.5) are provisional and unmeasured.

**Online `hints` is a different gate.** The signal-classification design §6
requires its own independently human-reviewed dataset, a pre-registered maximum
allowed increase δ with a confidence upper bound and per-stratum sample sizes,
and a `veto_recovered_facts` benefit reading built on human-confirmed recovered
facts. The pre-screen evaluation above measures none of that, so its gates
approve `enforce` only; `hints` stays `off`/`shadow` until that evidence exists.

## Known Gap

Previous versions of this document described TF-IDF/context-aware retrieval as if it were already shipped.
That was not accurate for `main` and caused confusion.

Issue reference: `#1059`

## Roadmap (Planned)

Planned scoring strategy:

```text
final_score = (similarity * 0.6) + (confidence * 0.4)
```

Planned integration shape:
1. Extract recent conversational context from filtered user/final-assistant turns.
2. Compute TF-IDF cosine similarity between each fact and current context.
3. Rank by weighted score and inject under token budget.
4. Fall back to confidence-only ranking if context is unavailable.

## Validation

Current regression coverage includes:
- facts inclusion in memory injection output
- confidence ordering
- token-budget-limited fact inclusion

Tests:
- `backend/tests/test_memory_prompt_injection.py`
