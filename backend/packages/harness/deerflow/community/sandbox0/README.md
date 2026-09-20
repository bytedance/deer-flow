# Sandbox0 persistent workspaces

The optional provider runs DeerFlow commands and file tools through the official
[Sandbox0 Python SDK](https://github.com/sandbox0-ai/sdk-py). One user/thread owns
one durable sandbox identity. At the end of a turn, `release()` mirrors bounded
workspace/artifact files to DeerFlow and waits for a committed RootFS checkpoint.
The next acquire resumes the same identity with a new runtime generation.

## Install and configure

```bash
pip install 'deerflow-harness[sandbox0]'
# From the source checkout's backend directory:
uv sync --extra sandbox0
```

Set `SANDBOX0_API_KEY` and optionally `SANDBOX0_BASE_URL` in the Gateway
process environment. Credentials stay outside the guest. Add this to
`config.yaml`, keeping your existing models and tools:

```yaml
sandbox:
  use: deerflow.community.sandbox0:Sandbox0Provider
  template: default
  # api_key: $SANDBOX0_API_KEY
  # base_url: https://api.sandbox0.ai
  # state_dir: /data/deerflow/sandbox0
  # request_timeout: 660
  # lifecycle_timeout: 120
  # bash_command_timeout: 600
  # ttl: 3600
  # hard_ttl: 604800
  # replicas: 10
  # environment:
  #   PYTHONUNBUFFERED: "1"
skills:
  container_path: /mnt/skills
```

Use a Linux template containing `bash`, `python3`, `find`, `grep`, and `base64`,
with permission to create `/mnt/user-data`, `/mnt/skills`, and
`/mnt/acp-workspace`. Select any additional language/document dependencies in the
Sandbox0 template. Host bind mounts are unsupported.

`replicas` caps active environments; paused workspaces do not consume this
provider's active slots. The server's quotas still apply. `ttl` is the runtime
soft expiration, renewed by active tool I/O at most once per minute. An idle
Agent that makes no sandbox requests can still expire. `hard_ttl` bounds the durable workspace lifetime (default
seven days). A missing/expired bound workspace raises an error rather than
silently starting an empty one. `destroy(provider_id)` explicitly deletes the
remote workspace and local binding. Shutdown checkpoints workspaces and retains
bindings; it does not delete conversation data.

## Persistence and boundaries

- Preserve `state_dir` (default: `DEER_FLOW_HOME/sandbox0`). Its atomic JSON
  bindings contain IDs and ownership only. Losing this directory loses the
  mapping; it does not delete the remote workspaces.
- This first integration supports **one Gateway process per state directory**.
  An OS lock rejects a second process. It does not provide distributed ownership
  or automatic adoption across independent Gateway hosts.
- Pause preserves writable RootFS files, including installed dependencies.
  Processes, memory, shell variables and `/tmp` do not survive pause. Every bash
  call starts a fresh shell, even within one turn.
- Prepared skills are uploaded to `/mnt/skills` on acquire. Explicit Agent skill
  projections replace the entire managed skill tree before execution. Only this
  fixed skills root is supported.
- Host uploads and ACP inputs overwrite their guest input copies on acquire;
  keep editable working copies in `workspace`. Gateway upload APIs also
  use the standard binary file interface. ACP inputs are not a live shared mount.
- On release, `workspace` and `outputs` are copied back for existing artifact
  endpoints. This presentation copy does not prune deleted files. Transfers are
  bounded to 2,000 files, 20 MiB per file and 100 MiB total. A mirror failure is
  surfaced, but the remote workspace is still checkpointed. The durable source
  remains Sandbox0.
- Configure egress controls on the Sandbox0 template. DeerFlow's AIO-specific
  network approval hooks and host mounts are rejected rather than ignored.

## Real Agent demo

See [the demo](../../../../../examples/sandbox0/README.md). It runs two real
DeerFlow turns, checks tool coverage and artifacts, and resets the provider
between turns to verify persistent binding recovery and runtime-generation
advancement. A tool-calling model and a reachable Sandbox0 deployment are required.
