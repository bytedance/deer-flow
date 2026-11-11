# Configuration (`deerflow/config/`)

Pydantic models and loaders for `config.yaml` (operator-owned) and
`extensions_config.json` (MCP servers and skill state, writable through the
Gateway), plus the credentials key and shared secret files. Every field, its
default and its validation are in the models here and in `config.example.yaml`.
Operator reference: [CONFIGURATION.md](../../../../docs/CONFIGURATION.md).

## Verify

```bash
cd backend
python -m pytest tests -q -k "config or credentials_key or secret_file"
make test-blocking-io
```

When you add or rename a field, update `config.example.yaml` and raise its
`config_version` if operators have to act.

## Path resolution

- **`AppConfig.resolve_config_path` is the only resolver.** Scripts and tools call
  it; they do not copy the search order. The same holds for
  `ExtensionsConfig.resolve_config_path`.
- **An explicit path that is missing is an error.** This applies to the argument
  and to `DEER_FLOW_CONFIG_PATH` / `DEER_FLOW_EXTENSIONS_CONFIG_PATH`. Only the
  fallback search may find nothing.
- **Mount mutable config through a directory.** A single-file bind mount goes
  stale when a host editor replaces the file on save.

## Loading and reload

- **Read config through `get_app_config()` on each request.** It reloads when the
  resolved path or the content signature changes, so an edit applies to the next
  message. Do not cache `AppConfig` on `app.state` or in a module global.
- **Startup-only fields are registered.** `reload_boundary.py::STARTUP_ONLY_FIELDS`
  is the list, and each such field's description starts with `startup-only:`. A
  new field that is read once at startup joins both.
- **A failed reload keeps the last good revision.** An unreadable or invalid file
  must not replace a working configuration, in either loader.
- **The singleton has one lock.** Reads, reloads, resets and test injections
  publish the parsed revision, its signature and the extensions snapshot together.
- **`$NAME` values are resolved once, at load.** Consumers use the resolved value
  verbatim, because a secret can itself start with `$`. A substituted value is
  always a string, so numeric fields accept decimal strings and reject booleans
  before Pydantic coerces them.
- **A running run keeps its snapshot.** A changed model or agent setting produces
  a new effective snapshot and does not alter an active run.

## Runtime writes to `extensions_config.json`

- **Hold both locks for a read-modify-write**: the in-process write lock and the
  sidecar file lock. Several Gateway workers and instances share the file.
- **Write with the shared atomic replacement helper.** An in-place overwrite is
  allowed only when the file is a mount point that refuses replacement. A crash
  can then truncate the file, so warn about that fallback.
- **Derived caches use a reset marker.** MCP tool lists and skill catalogs go
  stale without a byte of the config changing. `SharedResetMarker` publishes a
  generation next to the config file, and every process polls it.
- **`plugins` and `middlewares` stay in `config.yaml`.** They import code, so no
  Gateway API writes them.

## Secrets

- **`DEER_FLOW_CREDENTIALS_KEY` comes from the environment only.** It is never a
  `config.yaml` key and is never derived from the JWT secret. The first key
  encrypts, all listed keys decrypt, which is how rotation works.
- **A value that cannot be decrypted is missing data.** Callers handle
  `CredentialsDecryptError` and continue. Error text carries no key material.
- **Register a new consumer of the cipher** in
  `app.gateway.deps.credentials_key_consumers`. That list drives Gateway loading
  and the multi-instance refusal.
- **Create shared secret files with `read_or_create_secret_file`.** Concurrent
  creators converge on one value, and a reader never sees an empty or partial
  file. Generating a key is file I/O, so async callers offload it.

## Agent and model settings

- **Stored agent config is parsed leniently, written strictly.** A reader ignores
  an invalid stored field and keeps the agent usable. Add a managed field to
  `MANAGED_AGENT_CONFIG_FIELDS`, or an unrelated update drops it.
- **Operator prompt overlays are operator text.** They are set in `config.yaml`
  only, and no run context can override them.
- **A knowledge scope narrows; it does not authorize.** Retrieval still checks
  the operator allowlist.
