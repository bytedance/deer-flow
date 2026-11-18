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
  fencing, never by a read alone
- **Test against `backend/tests/kurrentdb_fake.py`.** When the live suite shows
  a divergence, fix the fake first, then the code
