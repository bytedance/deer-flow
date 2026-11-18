# KurrentDB extension

All KurrentDB code stays in this package. Core only offers the vendor-neutral
`run_event_store` registration hook. Behaviour suites live in
`backend/tests/test_kurrentdb_*.py` with the `bundled_extension` marker

```bash
cd backend && uv run pytest tests -q -m bundled_extension -k kurrentdb
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
  an expected version
- **Memory state is a fold of its scope's stream** (`memory/fold.py`). Fold code
  skips fence events, and an unknown event type or a broken invariant is
  `MemoryStorageCorruption`, never a silent skip
- **Plan memory writes in `memory/changes.py`, commit them in one append.** A
  plan that removes facts or clears a scope goes through
  `KurrentdbMemoryStorage._commit_destructive` as a `MemorySnapshot` boundary,
  never as plain `FactDeleted` / `MemoryCleared` deltas
- **Sidecars never fail a memory call.** Sidecar reads and writes log a warning
  and fall back to empty; reads drop every record an open deletion intent's
  criteria match (`intents_provider`), and records carry the primary revision
  they were written under so a deletion's `cutoff` spares later records
- **Test against `backend/tests/kurrentdb_fake.py`.** When the live suite shows
  a divergence, fix the fake first, then the code
