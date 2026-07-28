# Tenki backend

Runs each DeerFlow sandbox as a [Tenki](https://tenki.cloud) cloud sandbox — an
isolated microVM created from a stock base image, with no daemon or local
virtualization to manage. A cloud-hosted alternative to the container-based AIO
sandbox and the local-virtualization BoxLite backend.

## Configuration

```yaml
sandbox:
  use: deerflow.community.tenki:TenkiSandboxProvider
  api_key: $TENKI_API_KEY   # falls back to TENKI_API_KEY / TENKI_AUTH_TOKEN env var
  base_url: https://tenki.cloud  # optional; SDK default when omitted
  image: my-base-image      # optional; Tenki account default base image when omitted
  project_id: proj_...       # optional; auto-selected if the account has exactly one
  workspace_id: ws_...       # optional; auto-selected if the account has exactly one
  cpu_cores: 2               # optional per-sandbox vCPUs
  memory_mb: 2048            # optional per-sandbox memory
  replicas: 3                # active + warm microVM cap per gateway process (default: 3)
  idle_timeout: 600          # warm microVM idle seconds before terminate; 0 disables
  max_duration: 14400        # Tenki sandbox lifetime in seconds (default: 4h); 0 uses the account default
  sticky: false              # pin the microVM to its host (only matters with pause/resume)
  home_dir: /home/tenki      # writable dir backing /mnt/user-data (default: /home/tenki)
  environment:               # injected into every command (and as create-time env)
    PYTHONUNBUFFERED: "1"
```

Install the optional SDK before selecting this provider:

```bash
pip install "deerflow-harness[tenki]"
```

The `tenki-sandbox` package is an optional DeerFlow harness extra, not part of
the default install. Get an API key from <https://tenki.cloud/docs/sandbox/sdk>.

## Design

Tenki's Python SDK is synchronous, so — unlike BoxLite — the adapter calls the
SDK directly with no event-loop bridge. Sandboxes are named deterministically
from `user_id:thread_id`, released into an in-process warm pool after each agent
turn, and reclaimed (after a liveness health check) by the same thread on the
next acquire. A terminal session error evicts the sandbox and the next acquire
rebuilds it; other transport errors surface to the caller (`exec` is never
auto-retried — it is not idempotent, so re-running could double a command's side
effects). Sandboxes are created with `wait=False` and awaited via `wait_ready()`
so a readiness failure still leaves this provider holding the handle to
terminate, and with an explicit `max_duration` so a long-lived thread does not
lose its sandbox to Tenki's default lifetime mid-conversation.

| File | Role |
| --- | --- |
| `provider.py` | `SandboxProvider` lifecycle, warm pool, scope resolution |
| `sandbox.py`  | `Sandbox` adapter; `execute_command` + file ops |

## Contract coverage

The full `Sandbox` surface is implemented. File transport uses Tenki's native `sandbox.fs`
API; directory and content search shell out and reuse `deerflow.sandbox.search`,
mirroring `e2b_sandbox`:

- `execute_command` — `sh -lc`, with per-call env and timeout.
- `read_file` / `write_file` / `update_file` — native `fs.read_text` / `fs.mkdir` / `fs.write_stream` (binary-safe, streamed).
- `download_file` — native `fs.read_stream`, restricted to the `/mnt/user-data` prefix; the 100 MB cap is enforced on bytes actually received, so a file growing mid-transfer cannot slip past it.
- `list_dir` / `glob` / `grep` — `find` / `grep` with busybox-portable flags (the fs API is single-level and has no content search); results filtered/capped in Python and reported back under `/mnt/user-data`.

Tenki sandboxes run as the unprivileged `tenki` user with `/mnt` root-owned, so
DeerFlow's `/mnt/user-data` virtual prefix is remapped under the writable
`home_dir` (like `e2b_sandbox`). The provider also best-effort `sudo`-symlinks
`/mnt/user-data` → `home_dir` at create time so agent shell commands using the
literal `/mnt/...` path still work; if `sudo` is unavailable the file APIs keep
working via the remap.

Warm-pool capacity is governed by `sandbox.replicas` across active + warm
sandboxes. `sandbox.idle_timeout` controls how long released warm sandboxes stay
running; `0` disables idle reaping. Active sandboxes are never evicted to satisfy
the cap.

## Scope: stable features only

Only the stable Tenki surface is used — sandbox create/terminate plus
exec/shell/filesystem over shell commands. Volumes, snapshots, and template
builds are intentionally **not** used, so no prebaked image or unstable Tenki
feature is required and any stock base image works.

Not yet implemented (follow-ups): cross-process orphan reconciliation (adopting
sandboxes left by a previous gateway process) and a preview-URL surface.

## Status

Verified end-to-end against live Tenki sandboxes: provider resolution →
`execute_command` → full file-op surface (`read`/`write`/`update`/`download`,
`list_dir`/`glob`/`grep`) → warm-pool reclaim → terminate, plus the
`/mnt/user-data` sudo symlink. Unit tests run in CI without `tenki-sandbox`
installed; `test_integration_real_sandbox` exercises a real microVM when
`TENKI_API_KEY` is set.
