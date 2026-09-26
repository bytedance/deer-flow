### Memory System

DeerMem `prompt_prepend`/`prompt_append` wrap the first system message from
`memory_update` after formatting, without touching its human data message or
cached templates. This is the live summary/fact extraction path; do not wire
extensions only to the legacy `FACT_EXTRACTION_PROMPT` alias. Settings belong
to the constructed backend and require backend recreation to change.

This directory owns memory capture, storage, retrieval, prompt injection, and model-driven memory tools.

#### Main components

- `manager.py` defines the backend-neutral `MemoryManager` contract.
- `agents/middlewares/memory_middleware.py` queues filtered conversations for passive capture.
- `summarization_hook.py` connects memory work to the summarization lifecycle.
- `tools.py` provides `memory_search`, `memory_add`, `memory_update`, and `memory_delete`.
- `backends/deermem/` contains the default local backend.
- `backends/mem0/`, `backends/openviking/`, and `backends/honcho/` contain optional adapters.

`cancel_by_agent` cancels only pending debounce contexts in one user scope.
`user_id=None` selects only the legacy no-user root.
`agent_name=None` selects all agent buckets in that user scope.
It does not interrupt a context after `_process_queue` removes it from `_items`.
Broader cancellation must iterate known user scopes.

Focused updater tests live in `backend/tests/test_memory_updater.py`.
Backend-specific tests use `backend/tests/test_<backend>_memory_backend.py`.

#### Identity and isolation

Resolve users with `resolve_runtime_user_id(runtime)` in middleware and tools.
This keeps Gateway and standalone LangGraph runs in the same user scope.

Server-owned `langgraph_auth_user_id` takes precedence over ordinary client identity.
Lead-agent construction normalizes it with `make_safe_user_id`.
Memory, custom agents, user skills, skill policy, and prompt assembly reuse that identity.
Gateway removes client-supplied `langgraph_auth_user` and `langgraph_auth_user_id` before graph construction.

Gateway memory routes use `_resolve_memory_user_id(request)`.
Trusted IM requests can act for the connection owner.
Other requests use `get_effective_user_id()`.
Only `AuthMiddleware` can authorize the internal owner header.

No-auth mode uses `DEFAULT_USER_ID`, which is `"default"`.
An absolute `storage_path` opts out of the default per-user root.
`UserRepository.list_user_ids()` returns registered IDs in creation order for
administrative workflows such as `scripts/load_memory_sample.py --all-users`.
The bulk loader requires persistent database mode and backs up each user's memory by default.

DeerMem uses this layout:

```text
{base_dir}/users/{user_id}/memory.json
{base_dir}/users/{user_id}/agents/{agent_name}/facts/{sha256-prefix}/{fact-id}.md
```

`memory.json` stores only shared summaries, revision data, and timestamps.
It never stores facts or a fact index.
Each Markdown file stores one fact with YAML front matter.

Custom agent files share the per-user agent directory.
The legacy shared agent layout is read-only fallback data.

DeerMem maps a missing agent name to `__default__`.
That name is reserved and cannot identify a custom agent.
Public agent names use lowercase canonical form.

#### Operating modes

`memory.mode: middleware` is the default passive mode.
`MemoryMiddleware` queues filtered user and final assistant messages.
It captures `user_id` when it enqueues work.
This identity survives the background timer boundary.

`memory.mode: tool` registers the four memory tools.
The model chooses when to search or change facts.
Tool mode still uses `MemoryMiddleware` for passive writes on supported remote backends.

Middleware injection includes shared summaries and the selected agent's facts.
Tool-mode injection includes only shared summaries.
Tool mode leaves agent facts behind `memory_search`.
`memory.injection_enabled: false` disables the complete injected block.

Per-user lead-agent Custom Agents may set `memory_enabled: false` in their own
`config.yaml`. This is a complete per-agent opt-out: dynamic context remains
date-only, passive capture is not installed, automatic and manual compaction do
not flush summarized messages, tool mode exposes no memory tools or tool
guidance, and the global memory configuration remains unchanged for other
agents. On the next run after an existing agent opts out, Dynamic Context emits
`RemoveMessage` updates for its server-tagged frozen `__memory` entries while
retaining date reminders and real user messages. Omission defaults to the
existing enabled behavior.

#### DeerMem storage contract

`memory.backend_config.storage_class: markdown` opts into tolerant summary
reads; writes still use JSON. Only a JSON object in a closed `memory-json`
fence is accepted from Markdown. Decode the value before checking its closing
fence so embedded backticks and later fenced notes stay lossless. Parser and
storage regressions belong in `tests/test_memory_storage.py`; configure a data
root directory, not the existing manifest file. Legacy v1 reads still migrate
and advance the revision. Unparseable summary text is quarantined before rebuild.

`FileMemoryStorage` owns canonical storage and the retrieval adapter.
Do not reach into its private adapter state from higher layers.

The repository supports fact CRUD, summary updates, migration, search, and index lifecycle operations.
Targeted writes change only the selected Markdown files.
Whole-document `load` and `save` remain compatibility operations.

`apply_changes()` returns `complete: false` with fact deltas.
It never labels a partial cache as a complete memory document.
Public callers reload only when their response contract requires a complete document.

Writes use a user lock, shared revision, fact revisions, and a recovery journal.
Point operations can rebase only when all original fact preconditions still hold.
Snapshot operations must reload and recompute after a manifest conflict.
Use the typed conflict classes instead of matching exception text.

The weak lock cache must not retain inactive user scopes.
Cache validation uses the manifest metadata and persisted revision.
Out-of-band Markdown edits require `reload()`.
POSIX atomic replacement must sync the parent directory.

DeerMem converts storage conflicts to the public `MemoryManager` error types.
The Gateway maps conflicts to HTTP 409.
The Gateway maps storage corruption to a stable HTTP 500 response.

#### Migration

A normal default-manager read migrates legacy facts into `__default__`.
It adopts an old `lead-agent` bucket only when no custom-agent config exists.
Unexpected files stop migration and remain on disk.

The v1-to-v2 migration is one-way during application operation.
Operators must stop DeerFlow and snapshot the storage root before migration.
Every destructive migration first writes a verified `{manifest_filename}.v1.bak` file.
Missing or mismatched backups abort migration without changing v1 data.
Delete legacy agent JSON only after safe summary adoption or equality checks.
Summary conflicts keep the source file and return an error.
Compare both summary operands after additive normalization; preserve extension
fields and keep fact migration validation strict. Replacement imports reject
invalid fact containers or unusable content before normalization or storage
access; recoverable metadata may default, but malformed facts never mean clear.

Run the proactive migration from `backend/`:

```bash
PYTHONPATH=. python scripts/migrate_memory_markdown.py --all-users --dry-run
```

Remove `--dry-run` to migrate.
Use repeated `--user-id` options for exact source identities.
Use `--storage-path` for a non-default DeerMem root.
The command is idempotent and continues after per-user failures.
It returns a nonzero status when any user fails.

The older isolation migration remains available:

```bash
PYTHONPATH=. python scripts/migrate_user_isolation.py --dry-run
```

It assigns legacy `memory.json`, `threads/`, `agents/`, `skills/`, and the global
`USER.md` to `--user-id` (default `default`).

#### Retrieval

`retrieval_adapter` owns indexing and retrieval.
DeerMem selects persistent SQLite FTS5 by default.
An empty value selects the substring fallback.

SQLite index data lives below `.retrieval/` and remains rebuildable.
Chinese tokenization uses `jieba` only with the `memory-zh` extra.
Malformed facts are logged and skipped during rebuild.
A fatal rebuild failure keeps lazy retry active.
A corrupt persistent database is deleted and recreated once.

Storage sends adapter updates after it releases durable locks.
Adapter failures mark the scope dirty.
Search then uses canonical substring matching until rebuild succeeds.

Gateway startup schedules `DeerMem.warm_retrieval()` without delaying readiness.
The first search can rebuild its exact scope.
Shutdown waits one second for retrieval warm-up.
It reserves the full configured timeout for canonical memory flush.
The Gateway closes the derived SQLite connection after that flush.

#### Extraction safety

Extraction labels proposals with `scope`, `durability`, and `authority`.
Automatic writes accept only user-scoped, durable, descriptive facts.
Summary prose must be user-scoped and descriptive.
Missing labels reject that item without stopping unrelated updates.

Contradiction removals include `id`, `scope`, `reason`, and optional `replacementFactIndex`.
Task-scoped and project-scoped removals fail closed.
A paired removal requires its replacement to pass every write gate.
Tool-mode CRUD does not use the extraction gate.

Custom prompt directories must include the same classification fields.
Old templates cause extraction writes to fail closed.
The rejection counter and high-rejection warning expose this condition.

#### Capacity and review

All automatic, manual, tool, and import paths use `deermem/core/eviction.py`.
`confidence` is the default capacity policy.
`hybrid-v1` is opt-in and uses confidence, confirmation freshness, and access heat.
Shadow mode records disagreement while enforcing confidence-only selection.

Only deterministic message processing can confirm a fact.
The updater's `factsToReinforce` output supplies only the fact binding.
The deterministic gate matches a human message in the last six filtered batch messages.
It does not require a separate signal-to-fact match.
Search increments access heat only for facts it returns.
Prompt injection and `get_context()` do not increment access heat.

Usage and audit sidecars live below the agent `.metadata/` directory.
They must not change canonical Markdown timestamps or revisions.
Write audits only after canonical persistence succeeds.
User delete and clear operations must remove matching sidecar data.

Staleness review reuses the regular updater call.
It can keep, remove, or extend eligible aged facts.
Protected categories and non-aged facts cannot become removal targets.
Apply the per-cycle removal cap after candidate validation.
Do not extend a fact proposed for removal, even when the cap keeps that fact.
Extension bounds must prevent date overflow.

Consolidation also reuses the regular updater call.
Source facts must exist and cannot overlap across groups.
Enforce the source-count and confidence limits at apply time.
Use the newest source creation time for the merged fact.
Use the earliest source review deadline for its next review.

#### Remote backends

Strict reads use the backend-neutral `MemoryReadError`.
Backends declare their policy through `read_failures_are_fatal_for_config()`.
`DynamicContextMiddleware` preserves that policy at its injection timeout.
Policy methods must use only in-memory config. The non-loading lookup returns
unknown for a cold backend; discovery/config reload runs inside the existing
timed injection worker. Per-call policy state cannot leak across runs, and
timeout handling never submits more executor work. Unknown policy fails closed.
The prompt loader retains `MemoryManagerError` + `fail_closed` compatibility
for third-party backends that have not adopted the typed error.
The base policy resolver also honors legacy `fail_closed` at the timeout boundary;
other settings remain permissive unless the backend overrides the resolver.

OpenViking uses the maintained `langchain-openviking` package.
Keep it in middleware mode.
One API key is bound to one configured DeerFlow owner.
Reject another owner before remote access.

DeerFlow owns capture timing, the recall query, and the transcript cursor.
The package owns transport, message conversion, batching, and Session commits.
One DeerFlow thread maps to one stable OpenViking Session.
Store bounded hash-only cursors below `{storage_path}/openviking/sessions/`.

Async OpenViking entry points must offload synchronous SDK and file operations.
Shutdown must drain active work before closing the recorder client.
Pass an empty `extra_headers` mapping to prevent configuration-added transport headers.
Do not add embedded OpenViking imports, root-key access, or trusted identity headers.

Honcho is a remote HTTP adapter for user-model memory.
It creates one workspace per resolved `user_id`.
A missing user fails closed to no memory.
Its async methods offload synchronous HTTP work with `asyncio.to_thread`.
The default read failure policy logs and returns no results.
`failure_policy.read: fail_closed` rethrows recall failures.

Honcho configuration rejects non-finite or non-positive timeouts.
It also rejects non-positive character budgets during construction.

#### Run identity and token counting

Each run hashes its effective hidden memory block.
The run records one `context:memory` event with `content_sha256`.
The full memory text stays in checkpoint state.

Only current `DynamicContextMiddleware` output can establish first-run memory identity.
Checkpoint reuse requires the block to exist before the run.
Gateway input handling removes forged dynamic-context markers.

`prompt.py::_count_tokens` controls the injection budget.
Default `tiktoken` mode loads and caches its encoding lazily.
A failed load uses character estimation for a 600-second cooldown.
Concurrent callers use character estimation while one load is active.
Set `memory.token_counting: char` to prevent network access.

#### Configuration

The schema lives in `deerflow/config/memory_config.py`.
Do not duplicate its complete field list here.

Keep these cross-component constraints in sync:

- The shutdown flush budget is between 1 and 300 seconds.
- The pod grace period must include retrieval wait, flush time, and shutdown margin.
- `retrieval_adapter` selects FTS5, a custom factory, or the empty fallback.
- Eviction weights must total `1.0`.
- `watermark_max_keys: 0` makes the conversation watermark cache unbounded.
- A dropped watermark can re-extract one batch on the next turn.

#### Write-side near-duplicate fact gate (opt-in)

`fact_dedup_enabled` / `fact_dedup_similarity_threshold` implement the
write-side counterpart to relevance-aware retrieval (issue #5252): a proposed
NEW fact that paraphrases an existing same-category fact merges into it
(existing id/content/createdAt kept, confidence raised to the maximum, source
refreshed only when confidence increases) instead of being appended, and one `facts_merged_dedup` metric
increment records the merge. The similarity is deterministic and network-free
(bounded token-Jaccard via the updater-local tokenizer). Exact-content
duplicates keep going through the existing content-key check; targeted updates
by fact id are untouched.

Paired replacement proposals bypass near-dedup so their content remains
available to the post-capacity replacement check. Any ID proposed for normal
or stale removal is excluded from merge targets, even if a removal guard or
cap retains it. Scope, confidence, exact-content, and capacity gates still
apply; dedup never authorizes a removal or supplies a confirmation signal.
Latin words and CJK bigrams both participate in mixed-script similarity.
Whitespace-separated CJK runs retain adjacent-character ordering.
INFO logs identify the target and proposal index without memory content and
explicitly describe a proposed merge, not a completed persistence audit.

#### Relevance-aware retrieval (opt-in)

The deterministic lexical strategy behind issue #4495 lives in
`deermem/core/relevance.py` (token overlap + idf weights + confidence blend +
greedy MMR diversity). It never touches the persisted memory format and never
runs by default.

- `retrieval_relevance_enabled: true` opts in. `memory_search` then ranks every
  fact in scope (not only literal substring matches) and prompt injection ranks
  facts against the current query before the token-budget selection.
  This takes precedence over `retrieval_adapter`: search bypasses FTS5/custom
  retrieval, while adapter indexing and warm-up remain configured.
- Ranking reads at most 4096 characters and 128 tokens per query/fact. The
  no-jieba fallback emits both Latin words and CJK bigrams, including mixed text.
  `DeerMem.warm()` initializes optional jieba before serving requests, even
  with character-based token counting. Invalid/missing confidence defaults to 0.
- Search stops MMR after `top_k` picks. Injection diversifies guaranteed and
  regular pools independently and lazily, stopping when each token budget is
  exhausted; it never truncates candidates before the guaranteed partition.
  MMR caches token sets and incrementally updates maximum similarity penalties.
- `retrieval_relevance_weight` blends lexical relevance with confidence;
  `retrieval_diversity_weight` demotes near-duplicate facts. Defaults preserve
  legacy ordering. Relevance is distinct-query-token IDF coverage; repeated
  content cannot replace missing terms or saturate a partial match.
  Prefix matching requires one complete token to prefix the other; a shared
  four-character bucket alone is not a match (Postman is not PostgreSQL).
- DeerMem injection builds IDF once from the selected user/agent fact scope,
  before guaranteed/regular partitioning, using the same bounded tokenizer as
  search. No IDF work runs without an active lexical query. Category-filtered
  search uses its filtered corpus; budgets and separate diversity pools can
  still produce different final selections. No IDF cache crosses calls/scopes.
- The current-turn query flows from `DynamicContextMiddleware` (bounded,
  user-message text) through the optional `query` keyword on
  `MemoryManager.get_context` / `aget_context`. Shared signature inspection
  omits `query` when it is `None` or the backend is old/uninspectable, preserving
  forwarding wrappers' absent-hint contract; backend errors never cause retries.
  Query extraction prefers preserved `original_user_content` before applying
  the character cap, so upload descriptions never displace the user's request.
  Attachment-only messages with an empty preserved request stay query-less.
- Ranking must be deterministic, network-free, and mutation-free: caller-owned
  fact dicts are read-only inputs.

Legacy fact normalization in DeerMem and `frontend/src/core/memory/import-memory.ts` uses neutral confidence `0.5` for missing or invalid values, clamps finite confidence to `[0, 1]`, trims content, and defaults blank or missing sources to `unknown`. Keep these compatibility defaults aligned.

#### Extraction cost gate and model hints (opt-in)

`memory.prescreen` and `memory.signal_classification` are host slots wired into
DeerMem through one injected `judge` hook (`judge(context) -> verdict`; a plain
mapping in, so the vendored backend imports no host judging types, exactly like
`extraction_callback`). Both default to `off`, and `off` resolves no class path,
constructs nothing and validates no credentials, so an unconfigured deployment
behaves exactly as before.

- The pre-screen is a **cost gate, never a safety boundary**. It gates no
  execution and no write; it only decides whether the extraction call is worth
  paying for. Every failure direction is extraction: error, timeout, unusable
  response, missing verdict, provider exception, or an over-limit batch extract
  as usual. A judge failure is logged and treated as "no opinion" — judging can
  never lose a memory, and it can never block one either.
- **`max_state_chars` is a character count of the judged text, per side, and
  nothing is truncated to fit.** The judged text is exactly
  `format_conversation_for_update`'s output (including its own head/tail
  retention for long single messages); over a side's limit that side falls back,
  and each side enforces its own limit. The shared client counts UTF-8 bytes
  (`wire_size`) but replaces no consumer's limit (shared-client design §2.4): a
  byte count would trip the fallback three times early on CJK text.
- **A judging-config edit is hot-reloaded onto the cached manager.** The manager
  singleton (and its judge) is built once, but `memory.prescreen` /
  `memory.signal_classification` are documented as hot-reloadable
  (config/AGENTS.md "Config Hot-Reload Boundary"). `get_memory_manager()` rebuilds
  and re-injects the judge through `MemoryManager.refresh_judge` when either
  slot's config changes, so `enforce` → `off` stops skipping extraction and
  sending conversation text to the provider, and `off` → `shadow` starts
  recording, without a restart. The invalidating signature covers the shared
  top-level `typesafe:` connection block and each enabled side's *resolved*
  connection identity (including the credential's fingerprint), so a judged side
  that inherits its endpoint, model, credential, or deadlines from that block
  picks up an edit there, and a rotated credential invalidates the judge, without
  a slot edit. A config that cannot build a judge is logged and leaves the
  previous judge in place, recorded so the rebuild is not retried on every call.
  Publication is serialized on the manager lock and **revalidates the config
  generation** before installing: a judge built just before a rollback
  (`enforce` → `off`) is dropped rather than landing after it, so queued batches
  cannot keep judging against a superseded mode.
- **The combined request's cache is consulted before eligibility narrows the
  question set, and it is keyed by the *full* logical question set** (signal
  classification design §2.2.3 / §2.2.6). A round in which only one side is still
  eligible — L3, L8, or an over-limit side — reuses the answers already bucketed
  for that digest instead of re-asking them, so `mode` and phase-A eligibility
  never change what a cache hit already answers.
- **A partially answered bucket is not a hit.** Entries hold a per-question
  answer mapping, and consumption is per question, never per side (S18): an
  answer missing or malformed in a response falls back for that question this
  round and is asked again on the next request with the same digest, while the
  other direction in the same response is cached and consumed as usual. Coverage
  is attributed per answer, not per round: a side's `cached` flag (and the model
  it reports) reflects the answers it actually consumed, so a verdict reused from
  the bucket stays a cache hit even when the round fetched the other side's
  questions — otherwise the shadow evaluation counts it as a second network
  sample and inflates the confidence-bound denominator. The bucket also keeps the
  served model **per answer**, so filling it with a newer model does not
  re-attribute an answer it already held: a later full cache hit still audits each
  verdict under the model that produced it, and a retry that validates no answer
  reports the cached answer's model rather than the empty response's.
- **An enabled side always leaves a record, including when it cannot judge.**
  The judge emits the `prescreen` / `signal_classification` payload with a
  `fallback_reason` for every round in which a side is enabled, so the
  pre-screening design §5 "local fallbacks" population (L3 / L4 / L5 / L7 / L8 or
  a failure fallback) is countable from the records. A round with no record at
  all now means no side was enabled (or the drain path forbade judging) — not
  "every enabled side was ineligible".
- **Only `enforce` + `skip` changes persistence:** it drops the extraction call
  and **advances the watermark**, consuming the batch as "nothing durable here",
  and emits a `prescreen` record with the digest. `shadow` records and extracts as
  usual; the watermark advance on extraction success is unchanged.
- Batches excluded from judging, in this order: no judge injected (L1),
  `bypass_watermark` (emergency flush), the shutdown drain (`judge=False`),
  non-empty **deterministic** `detect_signals` on the feed (L3), and
  `staleness_review_enabled` / `consolidation_enabled` (L8 — a skip would also
  skip that batch's maintenance review). Note the shipped default
  `staleness_review_enabled: true` therefore makes the pre-screen inert until an
  operator turns it off; that is the intended conservative Phase 1 policy.
- Model hints are **additive**: the hint text takes the union of deterministic
  signals and model labels, but the reinforcement evidence gate reads the
  **deterministic set only**, so a model verdict can never write a confirmation.
  A model hint may veto a pre-screen skip (only `prescreen enforce` ×
  `classifier hints`); it can never cause one. Weakening hints only add text —
  they never drive deletion or demotion.
- **Online `hints` is a separate gate from the pre-screen evaluation below.** The
  signal-classification design §6 requires its own independently human-reviewed
  dataset, a pre-registered δ with per-stratum sample sizes for
  non-inferiority/superiority, and a `veto_recovered_facts` benefit reading.
  `eval_memory_prescreen.py` measures none of those and does not stand in for that
  dataset, so passing its gates approves `enforce` only; `hints` stays off or
  `shadow` until the §6 evidence exists.
- `mutations_accepted` is counted at the real apply sites (accepted new facts,
  accepted removals, accepted confirmations, accepted consolidations) and is the
  definition of "worth remembering": a batch whose only effect was a summary
  rewrite counts zero, so a skip that dropped it is not a missed memory. A new
  fact counts only if it survives capacity enforcement (and any consolidation
  that consumes it as a source); a near-duplicate merge counts only when it
  actually raised the target's confidence (a no-op restatement changes nothing)
  and the target survives (matched by id, or by identity for legacy id-less
  facts); a removal or reinforcement counts only for an
  id that actually existed — a proposal that passes its gate but changes no
  persistent fact must not register as a lost memory. Scoring runs against the
  scrubbed fact set (upload-event facts are dropped on the way to persistence), so
  a proposal the scrub removes is not counted either. The counter is published
  only after persistence succeeds: a failed apply (rejected commit, storage
  error) omits it, so the evaluation censors that record as a missing sample
  rather than reading it as a lost memory.
- **`enforce` stays gated by the shadow evaluation, and the evaluation's gates
  read evidence, not counts alone.** `scripts/eval_memory_prescreen.py` needs
  ≥200 reviewed skips *that the review confirms were none worth remembering* (a
  reviewed skip found worth remembering fails gate 3), and recorded savings
  evidence — saved calls, their tokens, p50/p95 verdict latency, and the
  mandatory no-network baseline on the same records. Missing any of that is
  `INSUFFICIENT`, never a pass; the exit code is the verdict.
- Signal classification is not admission control and not a write path: it never
  participates in queue admission, never alters `ConversationContext.signals` or
  the union merge, and neither hook touches the journal or the Gateway API.
