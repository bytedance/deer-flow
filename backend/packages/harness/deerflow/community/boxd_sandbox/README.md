# boxd sandbox provider

Runs DeerFlow sandboxes on [boxd](https://boxd.sh?ref=deer-flow) machines through
the `boxd` Python SDK. Each user/thread scope gets an isolated Ubuntu microVM.
The machine lives while the thread is active and while it waits in the warm
pool; after `idle_timeout` it is deleted, and a later turn gets a new machine
with the thread's files restored (see below). Anything the agent left outside
`/mnt/user-data` is gone at that point.

## Installation and configuration

Install the optional SDK, then select the provider:

```bash
pip install "deerflow-harness[boxd]"
export BOXD_API_KEY=...   # an API key from the boxd console
```

```yaml
sandbox:
  use: deerflow.community.boxd_sandbox:BoxdSandboxProvider
  # boxd_api_key: $BOXD_API_KEY # falls back to the BOXD_API_KEY env var
  # org: my-org                  # optional; the key's own org when omitted
  # region: fra                  # optional; fra or nyc
  # vcpu: 2                      # optional; 1, 2, 4 or 8 (memory 4G, 8G, 16G or 32G follows)
  # memory: 8G                   # optional; give either vcpu or memory, or a matching pair
  # from_snapshot: my-snapshot   # optional; start machines from a prepared snapshot
  # auto_suspend_timeout: 300    # optional; idle seconds before a machine goes to standby
  # ready_timeout: 120           # seconds to wait for a new machine to boot
  # name_prefix: deer-flow-      # machine names are <prefix><scope>-<random suffix>
  # labels:                      # extra labels on every machine
  #   team: research
  # replicas: 3                  # active + warm machines per gateway process
  # idle_timeout: 600            # warm seconds before the machine is deleted; 0 disables
  # environment:                 # merged into every command's environment
  #   PYTHONUNBUFFERED: "1"
```

Invalid values (an unknown region, a size boxd does not offer, a malformed
environment name) fail at provider startup, before any machine is created.

`from_snapshot` is the way to give every sandbox extra tools: prepare one
machine, save it as a snapshot in the boxd console or with the CLI, and name the
snapshot here. New machines start from it.

## Lifecycle and contract

- **One machine per scope.** The local sandbox id comes from
  `derive_sandbox_scope_token(user_id, thread_id)`. Every SDK call addresses the
  machine by the id that `create` returned.
- **Isolated.** Machines are created with `isolated: true`: no private network,
  no boxd credentials inside the machine. The API key stays in the Gateway, and
  per-call secrets travel as exec environment, not in the command string.
- **Bootstrap.** `/mnt/user-data/{workspace,uploads,outputs}` and the skills root
  are created as directories owned by the machine user, so the paths the agent
  sees are the real paths.
- **Thread files and skills.** A new machine receives the thread's uploads,
  workspace and outputs files (in that order) and the skills projection, each
  as one archive of at most 5,000 files and 128 MiB. Files past that limit are
  skipped with a warning. A failed transfer deletes the machine. An Agent with
  a skill policy gets its own projection through `sync_agent_skills`, which
  replaces the managed skill categories; the machine sees only what was
  uploaded.
- **Release.** Output files are copied back to the thread's output directory
  (at most 2,000 files, 512 MiB and 120 seconds per release), then the machine is
  parked in the warm pool. Names that differ only by case or Unicode
  normalization, unsafe names and linked destinations are skipped. A copy
  failure keeps the previous copy. Listing and downloads share the remaining
  120-second budget. A stopped machine's copy is skipped, and recovery waits
  for the next normal sandbox call.
- **Reuse.** Only the same scope can reclaim a warm machine, after a health
  check. A failed check deletes the machine and creates a new one.
- **Stopped machines** are started on the next call. A file call then runs
  once more; a command does not, and returns an error that asks to run it
  again, so a command never runs twice. Machines in standby or hibernation
  wake on the call.
- **Commands** run through `bash -lc` with a deadline: the caller's timeout,
  else `bash_command_timeout`. The deadline ends the command inside the machine
  with exit code 124 and keeps its partial output.
- **Reads** run as a bounded `head -c` with a deadline, so a large or stalled
  file cannot hold a Gateway thread or its memory.
- **Cleanup.** The idle reaper deletes warm machines after `idle_timeout`;
  shutdown deletes every tracked machine. A failed delete is kept and retried
  by the reaper (when `idle_timeout` is above 0) and by the next shutdown. If
  `create` raises after the server made the machine, the provider finds it by a
  per-create label and tracks it until deletion succeeds. When every caller
  that acquired a machine was cancelled, the machine is released to the warm pool.
- **Leftovers.** Machines carry the labels `deer-flow: sandbox` and
  `deer-flow-scope: <scope id>`. A Gateway that crashes cannot delete its
  machines; find them by these labels in the boxd console or with the CLI.

## Tests

```bash
cd backend
python -m pytest tests -q -k "boxd"
DEER_FLOW_RUN_LIVE_TESTS=1 BOXD_API_KEY=... PYTHONPATH=. uv run pytest tests/test_boxd_sandbox_live.py -v -s
```

The live test creates one machine, runs the checks against it and deletes it
at the end.
