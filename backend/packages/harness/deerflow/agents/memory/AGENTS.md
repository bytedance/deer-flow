### Memory System

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
Dropped pending snapshots still advance the conversation watermark so a later turn cannot restore them.
That advance is monotonic per `(thread_id, user_id, agent_name)`: each snapshot carries the
call-arrival sequence it was assigned before it ever competed for the queue lock (not the
sequence it would get by lock-acquisition order), and a watermark write with a lower sequence
than what is already recorded is refused rather than rewinding it. This covers a delayed
in-flight extraction that finishes after a newer snapshot for the same key was already queued
and cancelled.
The sequence counter and the watermark are both process-local, in-memory state on one
`MemoryUpdateQueue`/`MemoryUpdater` pair -- they do not span Gateway workers. A turn sitting only
in one worker's debounce queue (not yet flushed, cancelled, or fenced anywhere) is invisible to
a clear that lands on a different worker; that turn's pre-clear content can still be re-fed and
persisted once the conversation is next resent in full, because no process ever recorded that it
should be excluded. Only the durable clear-generation fence below is cross-worker. Closing this
queue-level gap needs the debounce queue itself to become shared/durable, a cancel broadcast to
active workers, or per-thread sticky routing -- none of which this fix attempts.
Broader cancellation must iterate known user scopes.
A durable clear generation in `memory.json` fences that in-flight window and other Gateway workers.
The queue captures the generation at enqueue, before the process-local queue lock.
A later clear bumps the generation in the same locked commit as the wipe.
User-wide `clear_all` raises that generation before per-agent wipes so an
in-flight writer cannot rebase onto an emptied agent.
Extraction drops before the LLM call, and again at commit, when a newer clear exists.
A generation-fenced drop still advances the conversation watermark and the clear-exclusion
coverage set. If the LLM call times out, raises, or returns illegal JSON after a newer clear
landed, the failed feed is still consumed when the captured generation is stale; ordinary
retryable failures are not consumed.
Same-key queue merges refuse an incoming snapshot whose call-arrival sequence is older than
the queued item, even when both peeks share a generation: otherwise a delayed shorter feed
can overwrite a newer snapshot before the watermark ever sees it.
The extraction watermark and the clear-exclusion coverage set are distinct. Emergency
(summarization) flushes set `bypass_watermark` so they can re-feed a subset about to be
removed without regressing extraction progress; they still drop any message whose
identity is in the clear-exclusion set. That set is the whole cleared prefix -- every
identity from a cancelled snapshot or from extracted coverage -- not only the tail
message. Coverage is merged by union and never shrinks: a later emergency subset
cannot replace a wider prefix, and call-arrival sequence does not decide which
identities stay. Emergency flushes still publish extracted coverage without
advancing the extraction watermark, so a later `clear_memory` can promote
emergency-only threads. `promote_clear_exclusions` scans published coverage, not
only keys that already have a watermark. `clear_memory` unions matching extracted
coverage into that set so a later `add_nowait` cannot restore already-extracted,
then-cleared turns. A persist that finishes, then sees a newer clear, also
registers exclusion on that completion path: promote only copies coverage that is
already published, so a clear that lands between persist and publish cannot be the
only writer of the exclusion set. If a
summarization flush carries only an older prefix that does not include the previous
tail, those prefix identities are still dropped; messages that are not in the set
remain eligible. Content-based identities (no message id) are membership-only --
they are not a prefix-cut boundary, because a later turn can repeat the same
assistant wording.
DeerMem's `aadd` / `aadd_nowait` offload enqueue (including the uncached manifest peek) with
`asyncio.to_thread`. The lead summarization path fires `memory_flush_hook.as_async`
(`amemory_flush_hook`) from `acompact_state`. That async hook also offloads
`get_memory_manager()` (backend scan + construction) with `asyncio.to_thread`,
matching `MemoryMiddleware.aafter_agent()`, so a cold start cannot `os.stat` on
the Gateway event loop.

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

DeerMem uses this layout:

```text
{base_dir}/users/{user_id}/memory.json
{base_dir}/users/{user_id}/agents/{agent_name}/facts/{sha256-prefix}/{fact-id}.md
```

`memory.json` stores shared summaries, revision data, timestamps, and durable clear-generation counters.
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
It captures `user_id` and the scope clear-generation fence when it enqueues work.
Both survive the background timer boundary.
The fence peek is a cheap counter read and runs before the queue lock.
File storage reads JSON counters only, not fact files.
Custom `storage_class` providers must override `peek_clear_generation` with an equally cheap read; `create_storage` rejects a provider that leaves the base peek in place.
Same-key merges keep the earlier token unless a newer clear is already visible.
A visible newer clear consumes the pre-clear snapshot and starts a fresh fence.
An incoming peek older than the queued context cannot inherit the newer token.
That refused add still unions its signals onto the queued snapshot.
If consuming the refused snapshot fails, the queued fence stays as-is.
Same-generation merges also keep the already-queued snapshot when the incoming
call-arrival sequence is older; they union signals and do not consume the
incoming feed as a clear.

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
A clear bumps `clearGeneration` / `agentClearGenerations` in the same locked commit as the wipe.
User-wide `clear_all` raises the user generation before per-agent wipes.
`apply_changes` and `clear_all` must honor `expected_clear_generation` atomically.
Custom `storage_class` providers must override `capabilities()` to advertise `clear-generation`, and `peek_clear_generation` so enqueue does not load fact files.
`create_storage` rejects providers that only pass those values through `**scope` or that leave the base peek in place.
Snapshot-derived writes never rebase extracted facts onto an emptied document.

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

The enqueue token is the commit fence.
Direct `update_memory` callers without a queue token fence from the pre-LLM snapshot.
A generation-fenced drop still advances the conversation watermark and the
clear-exclusion coverage set. The next turn must not replay the same pre-clear
messages against the newer generation, including emergency (bypass) flushes.
Manual `create_memory_fact` retries a concurrent clear: it re-reads the fence each attempt and stores the new fact on the emptied document instead of raising `MemoryClearGenerationConflict`.

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
- Custom `storage_class` providers must advertise `clear-generation`, override `peek_clear_generation`, and bump the fence atomically on clear.

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
