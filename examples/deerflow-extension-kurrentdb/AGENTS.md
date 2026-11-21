# KurrentDB extension

All KurrentDB code stays in this package. Core only offers the vendor-neutral
`run_event_store` registration hook. Behaviour suites live in
`backend/tests/test_kurrentdb_*.py` with the `bundled_extension` marker. The
user guide is `README.md`; its guarantees section changes with the behaviour

```bash
cd backend && uv run --frozen pytest tests -q -m bundled_extension -k kurrentdb
# live server: see the docstring of tests/test_kurrentdb_extension_live.py
cd .. && docker compose -f docker/docker-compose.kurrentdb.yaml config -q
```

## Rules

- **Settings come only from environment variables** (`_settings.load_settings`),
  never from `plugins[].config`: the memory storage is built by DeerMem in
  processes where the plugin was never loaded
- **Build every stream name through `_naming`.** Ids are percent-encoded so a
  name never gains a dash and global, user, meta and thread streams stay disjoint
- **Get clients through `_client`.** Factories are lazy: importing or installing
  the extension never connects to KurrentDB
- **Every append carries an expected version.** Settle an ambiguous append by
  fencing, never by a read alone. The one exception is a sidecar record
  (`memory/sidecars.py`): a blind `StreamState.ANY` append that is never retried,
  because the records commute and are best-effort; sidecar snapshots still use
  an expected version. Deletion index events (`deletions.py`) are the other
  exception: keyed by intent with deterministic ids, they commute and a
  duplicate is harmless
- **Memory state is a fold of its scope's stream** (`memory/fold.py`). Fold code
  skips fence events, and an unknown event type or a broken invariant is
  `MemoryStorageCorruption`, never a silent skip
- **Plan memory writes in `memory/changes.py`, commit them in one append.** A
  plan that removes facts or clears a scope goes through
  `KurrentdbMemoryStorage._commit_destructive` as a `MemorySnapshot` boundary,
  never as plain `FactDeleted` / `MemoryCleared` deltas
- **Every deletion runs through `deletions.DeletionEngine` (or `AsyncDeletionEngine`).** Intent first, then
  a boundary carrying `intent_id`, derived steps, `$tb` (derived streams, then
  the primary, only ever raised) and `DeletionDone`. A missing boundary is
  abandoned only after a fence lands at its position. Every truncation sits on a
  boundary, so a fold from the newest boundary is never partial
- **Run-event deletions are boundaries, never stream deletes.** `delete_by_run`
  appends `RunsCompacted` plus copies of every survivor (original data and
  metadata, `"survivor": true`) in one append; `delete_by_thread` appends
  `ThreadCleared`. Both carry `seq_high_water` (`run_events/seq.py`), so `seq` is
  never reused. A thread with nothing to delete writes no intent
- **Sidecars never fail a memory call.** Failures log and read as empty. Reads
  drop records that a committed intent (open or done, `committed_intents_for`)
  matches below its `cutoff`; records carry their primary revision
- **A sidecar-only clear is a deletion too** (`clear_metadata`): whole-agent or
  fact-id `clear_fact_metadata`, and `clear_all` of an empty scope. Its boundary
  keeps the state but moves the revision; it covers no canonical event
- **Trap:** sidecar records take the cached primary revision (no head check), so
  one from a process that missed another's deletion stays hidden
- **Canonical events are best-effort and never on the caller's path.** Map in
  `canonical/mapping.py` (schema payloads only; DeerFlow identities and
  `deerflow.origin` in event metadata; deterministic ids). Emit through
  `canonical/emitter.py`: queued in commit order (memory: `BackgroundQueue`,
  run events: `AsyncChains`), pre-check against `committed_intents_for`, append
  with an expected version (after a rejection at `NO_STREAM`, retry at the
  server-reported head: reads lag a recreation of a soft-deleted stream for a few
  milliseconds), post-check and `reopen_canonical`, all within
  `MAX_LIFETIME_SECONDS` of the commit. Never fence a canonical stream: it holds
  only schema event types. The global memory scope emits nothing, an
  upsert that keeps a fact's content emits nothing, and a thread is one session:
  `SessionStarted` only opens a newly created session stream (no per-run events)
- **Canonical cleanup is a separate obligation (`canonical/cleanup.py`).** It
  starts only once the intent's primary boundary is present, selects survivors
  against every primary-committed intent of the stream, appends copies (fresh
  ids, `deerflow.intent_id`) at the head it read or soft-deletes with that head,
  and reselects on a conflict. `CanonicalCleanupDone` is followed by verification
  after `MAX_LIFETIME_SECONDS` plus one timeout; only `CanonicalCleanupVerified`
  closes it. One pure decision per attempt (`plan_cleanup`) serves the sync and
  async cleaners, which differ only in I/O. It runs with or without
  `KURRENTDB_CANONICAL_EVENTS`, which gates emission only, so copies written
  while it was on still go after a deletion. Stores kick it after their own writes;
  `KurrentRecoveryService` (`service.py`, registered by `install()`) reads the
  Gateway config, stays idle unless memory or run events use KurrentDB, builds
  the memory storage from the Gateway's `DeerMemConfig` (sidecar caps must
  match), recovers primary sides at start with a budget per backend, and runs
  every obligation in the background. Never run it on a caller's path
- **Test against `backend/tests/kurrentdb_fake.py`.** When the live suite shows
  a divergence, fix the fake first, then the code
- **Demos and docs read named streams or categories, never `$all`.** `$all`
  ignores `$tb` and returns deleted events until a scavenge, so a `$all`
  example would contradict the deletion guarantee
