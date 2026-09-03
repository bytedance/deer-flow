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
