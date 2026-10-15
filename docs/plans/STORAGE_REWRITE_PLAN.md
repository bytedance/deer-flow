# DeerMem Storage Rewrite Plan

> Status: implemented in PR #4279 and retained as the design record requested during review.
> Scope: file-backed storage only. Retrieval ranking, embeddings, project scope, and recall policy remain separate work.

## 1. Objective

Separate durable memory into two ownership layers:

```text
user_id
├── memory.json                    # project-independent user/history summaries
└── agents/{agent_name}/facts/     # agent-related atomic facts
    └── {sha256-prefix}/{fact_id}.md
```

The rewrite must:

1. keep one global summary JSON per user;
2. store every fact as one canonical Markdown document;
3. prevent custom agents from sharing a fact repository accidentally;
4. make single-fact writes genuinely incremental;
5. preserve the existing MemoryManager and HTTP response shape;
6. give future retrieval implementations a stable fact repository API;
7. survive stale writers, process concurrency, and interrupted multi-file writes;
8. upgrade existing JSON facts without requiring application downtime.

## 2. Non-goals

- No `project` or `project_id` storage scope in this PR.
- No vector database, BM25, embedding, MMR, or reranking implementation.
- No change to when facts are recalled or injected into prompts.
- No SQLite/Postgres backend.
- No new frontend memory-management experience.
- No support for disabling the safety journal or selecting another fact format.

## 3. Canonical layout

```text
{storage_root}/users/{safe_user_id}/
├── memory.json
├── memory.json.v1.bak             # retained only after migrating this v1 source
├── .memory.lock
├── .memory.journal.json          # exists only during/recovering a transaction
├── .recovery/                    # transaction backups
└── agents/
    ├── __default__/
    │   └── facts/{sha256-prefix}/{fact_id}.md
    └── {custom-agent}/
        ├── config.yaml           # owned by the custom-agent subsystem
        ├── SOUL.md
        └── facts/{sha256-prefix}/{fact_id}.md
```

`memory.json` contains only:

```json
{
  "version": "2.0",
  "revision": 12,
  "lastUpdated": "2026-07-19T00:00:00Z",
  "user": {},
  "history": {}
}
```

It never contains facts, fact paths, hashes, embeddings, or a fact manifest.

`sha256-prefix` is the first two hexadecimal characters of `SHA-256(fact_id)`, giving a deterministic 256-way shard that also distributes generated `fact_*` IDs.

## 4. Scope rules

The storage scope in this PR is:

```text
user_id + agent_name
```

- `thread_id` is source metadata only.
- Omitted `agent_name` resolves inside DeerMem to the reserved `__default__` bucket.
- `__default__` is outside the public custom-agent grammar.
- Public agent identifiers are case-insensitive and canonicalized to lowercase.
- A custom agent named `lead-agent` is distinct from `__default__`.
- The custom-agent delete route must require `config.yaml`; a memory-only directory is preserved.

## 5. Fact document

Each Markdown file has YAML front matter plus one human-readable body:

```markdown
---
id: fact_ab12
schemaVersion: 2
category: constraint
topics: [python, runtime]
confidence: 0.95
status: active
user_id: alice
agent_name: research-agent
source:
  type: conversation
  threadId: thread_123
createdAt: 2026-07-19T00:00:00Z
updatedAt: 2026-07-19T00:00:00Z
revision: 1
consolidatedFrom: []
---

# Runtime constraint

Project uses Python 3.12.
```

Storage validates IDs, content, category, confidence, timestamps, lifecycle status, scope, source, revision, and consolidation metadata before committing.

## 6. Compatibility boundary

Internally, `source` is structured metadata. Public MemoryManager/API documents preserve the historical string field:

```text
{type: conversation, threadId: thread_123} -> "thread_123"
{type: manual, threadId: null}             -> "manual"
```

Manager/API reads materialize a compatibility `facts` array for the selected/default agent. The frontend never reads facts from `memory.json`.

Storage-specific conflict and corruption errors are translated at the MemoryManager boundary. The Gateway maps conflicts to HTTP 409 and returns a stable, non-sensitive HTTP 500 for corruption.

## 7. Repository contract

The file backend exposes:

- `get_fact` / `list_facts`
- `upsert_fact` / `delete_fact`
- `apply_changes`
- summary reads/updates
- migration
- index lifecycle and scoped search

`apply_changes()` returns an explicit incomplete delta. A caller that promises a full compatibility document must reload after committing.

Direct fact CRUD uses separate preconditions:

- expected shared `memory.json` revision;
- expected target fact revision or expected absence.

## 8. Concurrency model

Every transaction holds an in-process scope lock and a cross-process user file lock. Fact files and the shared JSON are protected by a recoverable journal.

Operations are divided by intent:

### Point operations

An update/delete of named facts depends only on addressed fact preconditions. It may explicitly rebase after a manifest conflict if all expected absence/revision checks still hold.

### Snapshot-derived operations

Clear, max-fact trimming, consolidation, and other collection-derived set operations depend on the complete fact snapshot. They must not replay an old delete/trim set against a newer manifest.

On conflict they:

1. reload the complete selected-agent document;
2. recompute the complete operation;
3. retry at most three times;
4. return a conflict if contention continues.

This preserves Clear All/scoped-clear meaning and the `max_facts` invariant.

Summary change sets are patches at the `user`/`history` child-key level: omitted siblings remain persisted. Import remains replacement-oriented by normalizing incoming sections against the complete empty compatibility schema before it calls storage.

## 9. Cache model

Every supported fact mutation advances and atomically replaces the shared `memory.json`. Cache validation uses `(mtime_ns, file_size, revision)` from that file. The persisted revision prevents a stale hit when a coarse-mtime filesystem reports identical metadata for same-size writes.

The read path does not glob/stat every Markdown fact merely to validate a cache hit, so validation cost does not grow with the number of fact files. It reads the shared JSON revision on every check. Direct out-of-band edits to Markdown require an explicit `reload()` or restart.

Inactive per-scope locks are weakly cached and may be garbage-collected.

## 10. Migration

The first normal default read detects legacy facts in `memory.json`, acquires the normal locks, and migrates them into `__default__`. User/history summaries are preserved and the JSON is rewritten without `facts`. Explicit and lazy migrations return their committed fact deltas through the call chain and notify a configured retrieval adapter after releasing storage locks.

Clear All enumerates every agent while holding the user lock. Facts from any unread legacy per-agent JSON are migrated first without adopting legacy summaries that are about to be cleared, and the resulting canonical facts are then deleted with the rest of the bucket. This prevents both summary conflicts from blocking an explicit clear and a later read from resurrecting skipped facts. The immutable `.v1.bak` remains inactive and agent configuration files remain untouched.

The v1-to-v2 migration is one-way for the running application because pre-PR code does not read Markdown facts. Operators must stop DeerFlow and create a filesystem snapshot or full backup of the configured storage root before upgrading a persistent deployment. Before the first destructive v2 write, storage atomically and durably retains every migrated JSON source as `{source_filename}.v1.bak`. An existing backup is never overwritten: if it differs from the source, or if the backup cannot be written, migration stops before changing v1 data. These local backups preserve pre-migration data only and do not replace the required full snapshot.

An optional idempotent operator CLI supports preflight audits and proactive migration:

```bash
cd backend
PYTHONPATH=. python scripts/migrate_memory_markdown.py --all-users --dry-run
PYTHONPATH=. python scripts/migrate_memory_markdown.py --all-users
```

Repeated `--user-id` and custom `--storage-path` are supported. The CLI is optional; lazy first-read migration remains the zero-administration path.

Legacy per-agent JSON is deleted only after its summaries are safely adopted or confirmed identical. Conflicting non-empty summaries and different same-ID facts fail loudly and preserve the source.

## 11. Fixed storage invariants

This release has one canonical fact format and requires crash recovery:

```text
fact format = Markdown
journal = enabled
```

These are implementation invariants, not public `DeerMemConfig` fields. If `fact_format` or `journal_enabled` is supplied in `backend_config`, it follows the normal unknown-key behavior: DeerMem logs a warning and ignores it.

## 12. Acceptance criteria

- Global JSON contains no facts or manifest.
- Default and custom-agent fact sets remain isolated.
- One fact mutation writes/notifies only addressed facts.
- Same-ID creates and stale same-fact writes fail.
- Snapshot-derived operations recompute after conflicts.
- Persisted fact count never exceeds `max_facts` after concurrent creates.
- Scoped clear either clears facts committed before its successful revision or returns conflict.
- Legacy global facts migrate through normal reads and the CLI.
- Public source remains a string.
- Cache validation does not scale with the number of fact files and includes the persisted revision.
- Every destructive v1 JSON source is durably backed up before migration.
- Tests cover Windows locking, POSIX directory sync, recovery, migration, concurrency, API compatibility, and portability.
