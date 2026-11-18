# KurrentDB

Optional extension that stores DeerFlow run events in
[KurrentDB](https://kurrent.io) streams, selected as `run_events.backend: kurrent`.
Memory storage and canonical kurrent-agents events follow in later changes of
this package.

Install from the repository root:

```sh
make extension-install SOURCE=/absolute/path/to/examples/deerflow-extension-kurrentdb
```

Enable the plugin and select the backend, then restart Gateway:

```yaml
plugins:
  - use: deerflow_extension_kurrentdb:install
    enabled: true
    required: true
run_events:
  backend: kurrent
```

## Settings

All settings come from environment variables, so every process that touches
KurrentDB reads the same values:

| Variable | Default | Meaning |
| --- | --- | --- |
| `KURRENTDB_CONNECTION_STRING` | required | KurrentDB connection string, for example `kurrentdb://localhost:2113?tls=false` |
| `KURRENTDB_TIMEOUT_SECONDS` | `10` | gRPC deadline per call; must be finite and greater than zero |
| `KURRENTDB_CANONICAL_EVENTS` | off | `1`, `true`, `yes` or `on` also writes kurrent-agents canonical events |

## Streams

User and thread ids are percent-encoded (every byte outside `[A-Za-z0-9_]`
becomes `%XX`), so names never contain a dash and stay disjoint:

| Stream | Purpose |
| --- | --- |
| `deerflow.memory-global`, `deerflow.memory-user.{user}` | Memory per scope |
| `deerflow.memory-meta-global`, `deerflow.memory-meta-user.{user}` | Memory sidecar per scope |
| `deerflow.run-events-{thread}` | Run events per thread |
| `deerflow.kurrent-deletions` | Deletion intents |

## Tests

The behaviour suites live in `backend/tests/test_kurrentdb_*.py` and use an
in-memory fake server (`backend/tests/kurrentdb_fake.py`):

```bash
cd backend && uv run pytest tests -q -m bundled_extension -k kurrentdb
```
