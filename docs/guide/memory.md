# Long-Term Memory

DeerMem trims oversized user/history summaries against the configured token
counter, including the omission marker and retained facts. Mixed-language text
does not rely on an average character/token ratio; the existing guaranteed-fact
allowance remains unchanged.

Automatic DeerMem summary updates accept only nonempty strings. An invalid
summary value preserves the existing section and its timestamp while valid facts
and other summaries in the same extraction response can still be saved.

Settings > Appearance > Language also supplies the preferred language for replies
and new automatic DeerMem facts and summary updates on subsequent chat turns and
replays. Explicit user language requests take precedence. Existing memories are
not bulk translated, and other memory backends retain their own language policy.
Model-native reasoning text may still use another language.
Scheduled runs and MCP task notification runs do not inherit this preference;
their replies and memory updates continue to infer language from run messages.

Mem0 search and management reads apply `failure_policy.read` to invalid record
scores, categories, and metadata. `fail_open` returns an empty result;
`fail_closed` reports a read error. A malformed later record never returns a
partial memory list.

Settings > Memory keeps successful clear, import, and fact edits visible even
when an older background read finishes afterward. Later reads still refresh
the view normally; failed actions preserve the existing cached memory.

DeerMem debounces pending updates independently per conversation, user, and agent.
`memory.backend_config.debounce_seconds` sets the quiet period (default 30 seconds),
and `max_wait_seconds` caps debounce deferral from the first pending update
(default 300 seconds). Activity in another conversation cannot extend that wait.
Extraction remains serial, so backlog and LLM latency can still delay completion.
Emergency snapshots of messages removed by compaction remain separate in arrival
order, so later compactions cannot replace earlier pending snapshots.
A backlog warning identifies the conversation, user, and agent at 32 pending emergency
snapshots and each doubling. These snapshots remain admitted beyond `queue_max_depth`
and stay in memory until processing. Check extraction latency when warnings appear;
process exit can still lose pending work.

Optional memory pre-screening and signal classification support TypeSafe (Jev)
and OpenAI Decisions. With `combine: auto`, their different endpoint paths keep
requests separate even behind the same gateway URL, model, and credentials.
Compatible requests to the same endpoint can still share one call. See the
[decision provider guide](../../backend/docs/GUARDRAILS.md).

The opt-in [DeerMem scope-isolation benchmark](../../backend/scripts/benchmark/deermem_scope_isolation/README.md)
checks semantic safety across facts and summaries, and fact routing across users
and agents. Failed extraction attempts are retryable execution errors, not safety passes.

For DeerMem, `memory.backend_config.storage_class: markdown` opts into tolerant
summary reads while keeping JSON writes and the existing UI. A hand-edited
`memory.json` can contain its JSON object inside a fenced `memory-json` block;
embedded backticks and later fenced notes are supported. Invalid UTF-8 bytes and
unparseable summary text are moved to `memory.json.corrupt-<timestamp>` for recovery
before rebuilding. File-access and I/O read errors preserve the original file and
fail the storage operation; retry after access recovers.
`storage_path` must point to the data root directory, not an existing JSON file.
Hand-edited DeerMem summaries and fact Markdown files may have a leading UTF-8
BOM; reads accept it, while writes remain BOM-free UTF-8.

Gateway shutdown drains memory updates before closing the backend, even when
shutdown is cancelled. Config reload failures are logged without aborting runtime
teardown. For Kubernetes, budget `terminationGracePeriodSeconds` for all shutdown
hooks, config/backend resolution, `memory.shutdown_flush_timeout_seconds`, and
backend close plus a safety margin. The flush timeout does not bound `close()`:
custom backends must make close quick or internally bounded, or shutdown can wait
until the process is forcibly terminated.

Most agents forget everything the moment a conversation ends. DeerFlow remembers.

DeerMem can optionally suppress near-duplicate extracted facts with
`memory.backend_config.fact_dedup_enabled: true` and
`fact_dedup_similarity_threshold` (default `0.7`, range `0.5`–`1.0`).
This local, deterministic word/CJK-bigram heuristic compares facts only within
the same user, agent, and category; it is not semantic equivalence detection.
It keeps the existing ID, text, and creation time, raises confidence to the
maximum, and refreshes the source only when confidence increases. Explicit
correction replacements and facts proposed for removal are protected from
near-duplicate merging. A merge does not count as user confirmation. The gate
is off by default and does not affect targeted fact updates.

DeerFlow also includes an optional `openviking` memory backend. It uses the
official `langchain-openviking` package to capture completed turns into stable
OpenViking Sessions and recall memory for prompt injection while leaving
DeerMem as the default. The initial integration supports one DeerFlow user with
one credential-bound OpenViking USER API key in `memory.mode: middleware` and
does not inherit arbitrary HTTP headers from `ovcli.conf`.
See [OpenViking memory backend](../../docs/OPENVIKING.md) for its configuration,
behavior, and current boundaries.

Across sessions, DeerFlow builds a persistent memory of your profile, preferences, and accumulated knowledge. The more you use it, the better it knows you — your writing style, your technical stack, your recurring workflows. Memory is stored locally and stays under your control.

DeerMem and mem0 capture user inputs and final assistant replies. Assistant
turns that request tools, including malformed or provider-raw calls, are
excluded from memory extraction even when they contain visible text.

DeerMem remains the default local backend. An opt-in `mem0` backend is also
available for the hosted mem0 Platform API or API-compatible self-hosted
servers. Its token-bearing `base_url` must use HTTPS by default; plaintext HTTP
requires an explicit local-development opt-in. See the
[mem0 backend guide](../../backend/packages/harness/deerflow/agents/memory/backends/mem0/README.md).

Malformed, undecodable, or excessively nested mem0 JSON responses, non-object
envelopes, and invalid result containers follow the configured read failure
policy: `fail_open` returns empty recall data, while `fail_closed` raises a
memory read error. An invalid later page does not return a partial list.
Listing format errors identify the failing page.

An opt-in `honcho` backend is available for self-hosted or hosted Honcho (v3
API). It builds user-model memory — long-term preferences and a cross-session
working representation — on Honcho's server side, so the backend makes no LLM
calls locally. Each user gets an isolated workspace derived from `user_id`; a
missing user id fails closed instead of falling back to a shared workspace.
Framework-hidden user messages are excluded from Honcho writes; the host's
human-input filter preserves valid user clarification answers carried in hidden messages.
If that filter raises an exception, only the affected hidden message is skipped;
other messages in the batch can still be captured.
Fact CRUD and Settings-page fact editing are not available for this backend. See
the [Honcho backend guide](../../backend/packages/harness/deerflow/agents/memory/backends/honcho/README.md).

Memory updates now skip duplicate fact entries at apply time, so repeated preferences and context do not accumulate endlessly across sessions.
Legacy memory files are normalized when read or imported, including recoverable fact metadata, so older local data remains usable as the schema evolves. Frontend and backend normalization use confidence `0.5` when missing or invalid, default blank sources to `unknown`, and trim fact content. A stored confidence that cannot become a finite float, such as an unbounded JSON integer in a hand-edited file, also falls back to `0.5` instead of failing a memory read, import, prompt build or relevance ranking.

In the default DeerMem `middleware` mode, automatic extraction now classifies every proposed fact by scope, durability, and authority before a deterministic write gate accepts it. The user memory pool stores only durable, descriptive user-level facts. Conversations assigned to a project can also retain durable, descriptive project facts in a separate [project pool](projects.md#project-memory). Temporary task state and one-time action permissions stay in conversation state. User-global summaries require both user scope and descriptive authority, contradiction removals are scope-gated, and a replacement-dependent removal is applied only when its replacement actually survives validation and storage. These classification labels are extraction-only metadata, add no extra LLM call, and are not written into the fact files. The explicit CRUD tools in `memory.mode: tool` remain a separate, model-directed path. Deployments that override the bundled DeerMem prompts via `memory.backend_config.prompts_dir` must add the new classification fields to their custom templates (the `memory_update` fact/summary/removal formats and the `consolidation` consolidated-fact schema): the write gate fails closed, so an un-migrated template stops every extraction-driven fact, summary, and removal write, surfacing only through the `rejected_by_scope_gate` metrics and the high-rejection-rate warning.

When a fact scope reaches `max_facts`, DeerMem still uses the historical confidence-only eviction order by default. Operators can opt in to `memory.backend_config.fact_eviction_policy: hybrid-v1`, which combines bounded confidence (65%), explicit-confirmation freshness (25%), and query-driven access heat (10%). Hybrid signal metadata is collected only while hybrid-v1 or shadow mode is enabled. Automatic confirmation from lexical reinforcement signals and model-selected fact IDs is disabled: a phrase elsewhere in a batch cannot establish that the user confirmed a particular fact. Existing confirmation metadata remains readable; extraction and injection never increment it. Custom prompts may retain factsToReinforce for compatibility, but that proposal alone cannot update confirmation counters or reset staleness. Access heat is stored in a separate decaying sidecar and increases only when `memory_search` actually returns the fact, so reads do not rewrite canonical Markdown or its `updatedAt`. Hybrid mode also reserves a bounded minimum of correction slots (10% of the cap, at most 10; unused slots return to normal competition). Capacity deletion remains physical, but a bounded metadata-only audit records fact IDs, categories, policy scores, and reasons without copying fact content. `fact_eviction_shadow_enabled: true` evaluates hybrid-v1 alongside the default policy without changing actual retention. This feature adds no LLM invocation and can be rolled back by selecting `confidence`.

When `eviction_reserved_categories` includes `correction`, corrections take priority within the shared reserve. Other configured categories use the remaining reserved slots in score order. The audit field `reservedCorrectionSlots` counts the correction facts selected by that reservation.

When `lastConfirmedAt` is absent, hybrid confirmation freshness and staleness review use `createdAt`. Repeated mentions in conversation do not refresh either timestamp.

File-backed memory now separates global user context from agent facts. Each user has one `memory.json` containing only the project-independent `user` and `history` summaries; every fact is a canonical Markdown file below `agents/{agent_name}/facts/`. Existing lead-agent middleware, API, Settings, import/export, and embedded-client calls that omit `agent_name` resolve inside DeerMem to the reserved `__default__` bucket. That bucket is outside the valid custom-agent name grammar, so a real custom agent named `lead-agent` has a separate fact repository and deleting a custom agent cannot delete a memory-only directory without `config.yaml`. Public agent identifiers are case-insensitive and canonicalized to lowercase. Runtime/API readers still receive a compatibility `facts` array for the selected/default agent, so the frontend does not read agent facts from `memory.json`; structured Markdown `source` metadata is projected to the historical string field at the MemoryManager boundary. An unscoped Clear All first migrates facts from unread legacy per-agent JSON without adopting its soon-to-be-cleared summaries, then removes shared summaries and facts from every agent bucket while preserving agent configuration files, so a later read cannot resurrect skipped legacy facts; an explicitly agent-scoped clear removes only that agent's facts. On first normal read, old facts embedded in the user JSON are migrated automatically to `__default__`; facts written to the earlier implicit `lead-agent` bucket are also moved when that directory is not a real custom agent. Migration and normal writes notify the configured retrieval adapter only after durable storage locks are released. DeerMem uses a scope-aware SQLite FTS5/BM25 adapter by default, stores only rebuildable derived index data under `.retrieval/` (or under `memory.backend_config.retrieval_index_path` when set; a relative value resolves against `storage_path`), and rebuilds it in the background during Gateway startup or lazily on the first scoped search. A corrupt derived index is recreated automatically. When several Gateway instances share one `storage_path`, point `retrieval_index_path` at instance-local disk: SQLite's WAL mode is unsupported on network filesystems, each instance re-syncs a user's index on its next search after a peer writes, and a declared multi-instance deployment (`deployment.multi_instance: true` / `DEER_FLOW_MULTI_INSTANCE=1`) that leaves the index under the memory root logs a warning at startup. The Helm chart mounts a Pod-local `emptyDir` for it. Set `memory.backend_config.retrieval_adapter` to an empty string to disable it and use the local substring fallback. Chinese tokenization is optional; install the backend `memory-zh` extra (`uv sync --extra memory-zh`) for jieba-assisted sub-phrase search. Journaled writes, a shared user lock, and optimistic user-memory revisions prevent silent lost updates.

FTS5 search selects the highest combined BM25, time-decay, and confidence scores across all matching facts before applying the requested result count. Requesting fewer results preserves the same ranking.

Set `memory.backend_config.retrieval_relevance_enabled: true` to opt into deterministic relevance/confidence ranking and query-aware injection. This **bypasses `retrieval_adapter` for search**, including the default FTS5/BM25 and custom adapters; indexing remains configured. `retrieval_relevance_weight` controls the blend and `retrieval_diversity_weight` enables near-duplicate penalties (default 0). Scoring uses at most the first 4096 characters and 128 tokens per query/fact. Search diversifies only up to `top_k`; injection diversifies guaranteed and regular facts independently until their token budgets are reached. Leave the feature disabled to retain the existing retrieval and injection behavior.

Lexical relevance measures IDF-weighted coverage of distinct query terms, so
repeated partial matches cannot tie a complete match merely by saturating the
score. Prefix matches require one complete token to prefix the other, not just
four shared characters. For uploads, query-aware injection uses the preserved
user request rather than the prepended file descriptions; attachment-only
messages retain query-less injection. Older custom memory backends can keep their existing `get_context`
signature: prompt injection and the inherited async wrapper pass `query` only
when that callable supports the keyword and the hint is not `None`.
Search and automatic injection use the same IDF weighting for the same
user/agent candidate scope. Category-filtered search and injection's separate
guaranteed/regular token budgets can still yield different final selections.

Memory injection follows the configured operation mode. In `middleware` mode, DeerMem injects the user-global summaries and the selected agent's facts. Custom-agent bootstrap conversations use that agent's fact bucket as well, so setup details do not leak into the default agent's memory. In `tool` mode, the automatic `<memory>` block contains only the global `user` and `history` summaries; agent facts are retrieved explicitly through `memory_search`, avoiding duplicate automatic and tool-returned fact context. Setting `memory.injection_enabled: false` still disables the entire block in either mode. When a fact ID is already known, `memory_get(fact_id)` returns that exact fact from the current user and agent scope without searching by content. Missing or out-of-scope IDs return a not-found error; backends without the required read or agent-scope capability return an unsupported error.

An individual Custom Agent can opt out of memory without changing the global setting. Add `memory_enabled: false` to that agent's `users/{user_id}/agents/{name}/config.yaml`. The agent still receives the current-date reminder, but DeerFlow does not inject recalled memory, queue passive or summarization-driven memory updates (including manual `/compact`), expose memory tools, or add memory-tool instructions for that agent. If an existing agent is switched off, its previously injected memory block is removed from checkpoint state before the next model call while its date reminder and conversation remain. Omitting the field (or setting it to `true`) preserves the existing global `memory` behavior.

`DeerFlowClient(agent_name=...)` manages memory in the same bucket the agent
uses in conversations. An unnamed client uses the default bucket. Named clients
raise `NotImplementedError` when the backend lacks agent-scoped management.
The Gateway returns HTTP 501 for the same request.

This also applies to the `noop` backend. On a named client, `get_memory()`,
`export_memory()`, `reload_memory()`, `get_memory_status()`, `clear_memory()`,
and `import_memory()` now raise `NotImplementedError`. These methods previously
returned empty memory data with that backend.

Single-fact repository operations are genuinely incremental: an upsert/delete reads, journals, writes, and re-indexes only the addressed fact files, and returns an explicit incomplete delta rather than a cache-dependent fake full document. Summary change sets merge the supplied `user`/`history` child keys over the persisted sections so a partial update cannot erase omitted siblings; full imports normalize both sections to the complete compatibility schema before applying replacement values. Imports reject malformed fact lists or blank/non-text content with HTTP 400 before changing stored memory; recoverable legacy metadata still receives defaults. An explicit empty fact list remains an intentional clear. Manager/API compatibility methods materialize a fresh full document only when their public response contract requires one. Fact-level point operations use separate expected user-memory and fact revisions and may explicitly rebase when every addressed fact precondition still holds. Snapshot-derived operations such as scoped clear, capped create, consolidation, and trimming never replay stale delete/trim sets: a manifest conflict reloads the complete document and recomputes the operation, with a bounded retry. Fact paths use the first two hexadecimal characters of `SHA-256(fact_id)` so generated `fact_*` IDs distribute across shards. The cache token combines the shared JSON's nanosecond mtime, size, and persisted revision; this prevents coarse-mtime same-size writes from returning stale data without scanning fact files. Direct out-of-band Markdown edits require an explicit reload. Storage-specific conflicts and corruption are translated at the MemoryManager boundary; the Gateway returns conflict as HTTP 409 and a stable, non-sensitive corruption error as HTTP 500. Full-document `save()` remains a compatibility API and computes a diff before writing; malformed or missing `facts` can no longer silently erase an agent's Markdown files. Legacy migration preserves non-empty `user`/`history` before deleting an agent `memory.json`; conflicting summaries keep the legacy file and fail loudly instead of choosing a winner.

DeerMem backup imports restore saved fact contents even after those facts have
been edited, using the current stored revisions to protect the restore. Older
backups may omit fact revisions. Backup revisions are validated before the
importer substitutes current revisions. Rejected imports preserve stored memory.
Backups with duplicate fact IDs are rejected before replacing the selected bucket.
The import endpoint requires an explicit `facts` array. Omitting it returns
HTTP 422, while `facts: []` explicitly clears the selected fact bucket.
A concurrent write during import still returns HTTP 409 so the caller can reload
and retry.

Legacy facts in `memory.json` migrate automatically into the reserved `__default__` Markdown bucket on the user's first normal memory read. Operators who prefer to audit or complete the migration before serving traffic can run the optional idempotent CLI from `backend/`:

```bash
PYTHONPATH=. python scripts/migrate_memory_markdown.py --all-users --dry-run
PYTHONPATH=. python scripts/migrate_memory_markdown.py --all-users
# A custom DeerMem root or original non-directory-safe identity can be explicit:
PYTHONPATH=. python scripts/migrate_memory_markdown.py --storage-path /path/to/deerflow-home --user-id 'test@example.com'
```

The v1-to-v2 storage migration is one-way for a running application: pre-PR code does not read Markdown facts. Before upgrading a persistent deployment, stop DeerFlow and take a filesystem snapshot or full backup of the configured memory storage root. The migration also durably retains each destructive JSON source beside the original path as `{manifest_filename}.v1.bak` before writing v2 data; an existing mismatched backup or a backup-write failure stops migration without modifying the v1 source. This local backup preserves pre-migration data but is not a substitute for a full snapshot and does not contain facts created after the upgrade.

`--user-id` may be repeated. `--all-users` discovers the existing directory-safe buckets below the selected storage root; standalone integrations that passed raw IDs containing characters such as `@` should use the original value with `--user-id`. A failed user's migration is reported without hiding the rest of the audit, and the command exits non-zero when any user fails. The automatic first-read path remains enabled, so running this CLI is not required for startup.
