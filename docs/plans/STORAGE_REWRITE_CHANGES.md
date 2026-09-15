# DeerMem Storage Rewrite: Implementation Guide

> This document explains the final PR behavior for readers who are new to the codebase. It complements `STORAGE_REWRITE_PLAN.md`: the plan explains the intended contract; this file explains where the code changed and how a request travels through it.

## 1. What changed on disk

Before the rewrite, facts and summaries could live together in a coarse JSON document. The final layout is:

```text
users/alice/
├── memory.json
├── memory.json.v1.bak
└── agents/
    ├── __default__/facts/30/fact_a.md
    └── research-agent/facts/ee/fact_b.md
```

`memory.json` owns project-independent summaries. Each Markdown file owns one atomic fact. No JSON fact index duplicates the Markdown repository.

## 2. Main files

### `deer_mem.py`

This is the DeerMem implementation of the public `MemoryManager` plugin interface.

It:

- maps omitted agents to `__default__`;
- canonicalizes explicit agent names to lowercase;
- translates storage-private exceptions to public manager errors;
- converts structured internal source metadata to the legacy public string;
- reloads complete documents where the manager/API contract promises completeness.

Gateway code does not import DeerMem storage internals.

### `deermem/core/paths.py`

This owns user, agent, and fact path validation. The internal `__default__` sentinel is deliberately outside the public custom-agent regular expression.

Fact paths are sharded by the first two hexadecimal characters of `SHA-256(fact_id)`. This gives deterministic direct lookup while distributing generated IDs that all begin with `fact_`.

### `deermem/core/storage.py`

This owns canonical parsing/rendering, locks, revisions, journaling, recovery, migration, cache invalidation, fact repository operations, and retrieval notifications.

### `deermem/core/updater.py`

This converts manual CRUD and LLM extraction results into repository change sets. It decides whether an operation is a point mutation or depends on a complete snapshot.

### `app/gateway/routers/memory.py`

This keeps the HTTP schema compatible. It catches only backend-neutral MemoryManager exceptions and maps concurrency to 409 and corruption to a stable 500.

### `scripts/migrate_memory_markdown.py`

This optional CLI lets operators preview or proactively run the same migration that normal first reads perform lazily.

## 3. Read trajectory

For an ordinary request with no explicit agent:

```text
Gateway / middleware
  -> MemoryManager.get_memory(user_id, agent_name=None)
  -> DeerMem canonicalizes agent to __default__
  -> FileMemoryStorage.load(__default__)
  -> recover journal / migrate legacy data when needed
  -> compare memory.json (mtime_ns, file_size, revision) with cache
  -> cache hit, or parse selected agent Markdown files
  -> DeerMem converts source metadata to public strings
  -> Gateway validates and returns the compatibility document
```

For a custom agent, the same trajectory reads that lowercase agent bucket and combines it with the user's shared summaries.

## 4. Single-fact update trajectory

```text
MemoryManager.update_fact(fact_id)
  -> storage.get_fact(fact_id)
  -> build one upsert with expected fact revision
  -> acquire in-process + cross-process locks
  -> recover an interrupted prior journal if present
  -> validate shared revision and target fact revision
  -> journal only memory.json + the addressed fact
  -> atomically replace the Markdown fact and memory.json
  -> fsync files and the POSIX parent directory
  -> notify retrieval for that fact only
  -> reload a complete compatibility response
```

Unchanged sibling facts are not backed up, rewritten, or re-indexed.

## 5. Why there are two revisions

The shared JSON revision protects the multi-file transaction. The fact revision protects one Markdown object.

They answer different questions:

```text
manifest revision: Did anything in this user's memory change?
fact revision:     Is the exact fact I read still the same object version?
```

Direct `upsert_fact` and `delete_fact` therefore accept separate expected manifest and fact revisions.

## 6. Safe rebase versus fresh-snapshot retry

A point update to `fact_a` can safely move from manifest revision 10 to 11 if `fact_a` still has the expected revision. A scoped clear cannot: its meaning depends on every fact that existed at the successful commit.

The final implementation uses this rule:

```text
point mutation + valid fact preconditions
    -> explicit bounded manifest rebase is allowed

clear / trim / consolidation / collection-derived set
    -> manifest conflict
    -> reload full document
    -> recompute complete operation
    -> bounded retry
```

This fixes two reviewed races:

- a fact created between a scoped-clear snapshot and commit no longer survives behind a successful “empty” response;
- two creators starting from 9/10 facts cannot commit 11 facts.

## 7. Clear semantics

The manager distinguishes two calls:

```text
clear_memory(user_id=alice)
    clears shared user/history summaries and every agent fact bucket
    preserves custom-agent config.yaml and SOUL.md

clear_memory(user_id=alice, agent_name=research-agent)
    clears only research-agent facts
    preserves shared user/history summaries
```

The file backend's all-user clear holds the user lock while enumerating buckets. It first migrates facts from any unread legacy per-agent `memory.json` without adopting legacy summaries that are about to be cleared, then deletes the resulting canonical fact files; retained `.v1.bak` files are inactive migration evidence and are never read back, while custom-agent configuration remains untouched.

## 8. Source compatibility

On disk:

```yaml
source:
  type: conversation
  threadId: thread_123
```

Public API:

```json
{"source": "thread_123"}
```

Manual/import/consolidation sources similarly return their type string. The richer internal form is ready for retrieval metadata without breaking the frontend.

## 9. Cache behavior

The earlier cache signature scanned and statted every fact file on every `load()`. The final cache observes the shared `memory.json` only.

The token is `(mtime_ns, file_size, revision)`. Every supported storage mutation replaces the JSON and increments its revision, so another process's write invalidates cached agent documents even when a coarse-mtime filesystem reports identical metadata for same-size writes. Validation reads one shared JSON and does not scale with the number of fact files. This may invalidate more agents than strictly necessary, but it avoids an O(n) fact-directory walk without introducing a second manifest.

Manual out-of-band Markdown edits are not part of the supported write API and require `reload()`.

Per-scope in-process locks live in a weak-value dictionary, so inactive users do not permanently grow the lock map.

## 10. Migration trajectory

When a v1 `memory.json` still contains facts:

```text
first load/reload
  -> detect legacy facts/version
  -> acquire normal locks
  -> durably retain every source as memory.json.v1.bak
  -> normalize facts into __default__ scope
  -> commit Markdown files and preserved summaries through the journal
  -> rewrite memory.json without facts
  -> release storage locks and notify the configured retrieval adapter
  -> continue the original read
```

The explicit CLI path emits the same retrieval upserts. Re-running an idempotent migration emits no duplicate notification because no fact is rewritten.

Operators may run:

```bash
cd backend
PYTHONPATH=. python scripts/migrate_memory_markdown.py --all-users --dry-run
PYTHONPATH=. python scripts/migrate_memory_markdown.py --all-users
```

The command is idempotent, accepts repeated `--user-id`, supports `--storage-path`, continues reporting after one user fails, and exits non-zero if any user failed. It is not required for startup.

This is a one-way application migration: pre-PR code cannot read Markdown facts. Before upgrading a persistent deployment, stop DeerFlow and take a filesystem snapshot or full backup of the configured storage root. Storage also retains each destructive v1 JSON source beside its original path as `{source_filename}.v1.bak` before committing v2 data. Existing backups are immutable; a mismatch or backup-write failure aborts before changing the source. The local backup contains pre-migration data only and does not replace the full snapshot requirement.

## 11. Configuration changes

`manifest_filename` and lock timeout remain configurable. Markdown format and journaling are required invariants, not modes.

`fact_format` and `journal_enabled` are not `DeerMemConfig` fields. If supplied in `backend_config`, they follow the normal unknown-key behavior: DeerMem logs a warning and ignores them.

## 12. Agent naming

The Gateway already stores custom-agent names in lowercase. DeerMem now makes the same rule explicit at its manager boundary:

```text
Lead-Agent == lead-agent == LEAD-AGENT
```

This gives Linux, macOS, and Windows the same behavior. A cross-layer contract test pins that both public naming patterns reject `__default__`, while storage may use the sentinel internally.

## 13. Failure behavior

- Stale same-fact write: conflict, no overwrite.
- Same-ID concurrent create: conflict, no conversion into update.
- Continuing collection contention: conflict after bounded retries.
- Corrupt JSON/Markdown: stable public corruption error; original files retained.
- Conflicting legacy summaries/facts: migration fails loudly and preserves the legacy source.
- Missing, unreadable, or mismatched persistent v1 backup: migration stops before changing the source.
- Retrieval adapter failure: persistence remains committed; the failure is logged/reported per fact.

## 14. Review-driven fixes retained in the implementation

- Default bucket changed from colliding `lead-agent` to reserved `__default__`.
- Custom-agent deletion requires a genuine config file.
- Legacy global facts migrate on first read and through an optional CLI.
- Public responses retain string `source`.
- Conflicts map to HTTP 409 through MemoryManager-neutral errors.
- Clear All and scoped clear have distinct semantics.
- Full index rebuild validates original email-style user IDs correctly.
- Lock cache is reclaimable.
- Manifest and fact revisions are separate.
- Retry dispatch uses exception subtypes, not message text.
- POSIX atomic replacement fsyncs the parent directory.
- Stale default-bucket test now asserts `__default__`.
- Snapshot-derived set operations recompute instead of replaying stale intent.
- Cache validation no longer scans every fact on every read.
- Cache tokens include the persisted revision to survive coarse-mtime same-size writes.
- Fact paths shard by `SHA-256(fact_id)[:2]` rather than the constant `fa` prefix.
- Destructive migration writes immutable `.v1.bak` sources before v2 data.
- Fixed storage invariants are no longer presented as configurable features.

## 15. Verification map

Primary coverage lives in:

- `tests/test_memory_storage_markdown.py`
- `tests/test_deermem_self_contained.py`
- `tests/test_memory_router.py`
- `tests/test_memory_markdown_migration_cli.py`
- `tests/test_custom_agent.py`

Tests cover layout, compatibility, incremental writes, concurrency, cap enforcement, clear semantics, corruption, migration, retrieval delegation, cache invalidation, path containment, portability, Windows lock behavior, and POSIX directory sync.
