# Sandbox (`deerflow/sandbox/`)

The `Sandbox` and `SandboxProvider` interfaces, the local provider, the sandbox
tools (`bash`, `ls`, `glob`, `grep`, `read_file`, `write_file`, `str_replace`) and
the pieces every provider shares: identity, leases, environment policy and bounded
downloads. Remote providers live in `deerflow/community/<provider>/` and have
their own guides.

## Verify

```bash
cd backend
python -m pytest tests -q -k "sandbox or local_grep or env_policy"
make test-blocking-io     # provider lookups run on the event loop
```

A change to shell quoting, encodings or path mapping also needs a run on native
Windows. The portable string assertions do not replace it.

## Paths

- The agent sees `/mnt/user-data/{workspace,uploads,outputs}` and `/mnt/skills`.
  The provider's mount table is the only place that maps them to host paths. Tool
  code resolves `/mnt/user-data/...` only and leaves skills, ACP workspaces and
  custom mounts virtual, so that there is one source of truth per acquire.
- A virtual parent that has no host directory (the default skills root) is searched
  through its mounts only. Falling back to the host parent would expose unrelated
  host files.
- Error messages translate host paths back to virtual paths at the sandbox
  boundary. The model must not see host paths.
- Both `local` and `local:<user>:<thread>` are local sandbox IDs. Use
  `is_local_sandbox()`.

## Identity, leases and shutdown

- **Sandbox identity is `(user_id, thread_id)`.** Remote IDs come from
  `derive_sandbox_scope_token`. Changing its output orphans every running
  container. A lookup miss acquires by user and thread, never by checkpoint ID.
- **Authorization comes first.** Every sandbox-backed tool call passes the
  `sandbox:execute` gate before it reuses a persisted sandbox ID or acquires a new
  one. A restored ID is not proof of permission.
- **Two kinds of lease.** The cross-instance ownership lease decides which Gateway
  may reap a container. The process-local `SandboxLeaseManager` counts the users of
  one client (lead agent, subagents, Gateway requests, channel uploads). Release a
  container only when the local count is zero.
- **`get()` and `get_scoped()` never block.** They run on the event loop and read
  process memory only. Store and network calls belong in the acquire path.
- **Shutdown can be retried.** A provider whose shutdown failed stays registered so
  that the next attempt can finish. Hosts that drain runs first (the Gateway
  lifespan) take shutdown ownership before any provider exists; providers created
  after that skip their own SIGTERM and SIGINT handlers.
- **Cancellation.** Signal the managed shell before you drain a cancelled command,
  and stop only the processes that belong to the lease owner.

## Security

- **Environment.** `build_sandbox_env()` removes inherited credential variables.
  Values from `sandbox.environment` and per-request secrets are added after the
  scrub. Route every new subprocess launch through it.
- **Network approval** needs a human. Runs with no interactive responder
  (scheduled, webhook, autonomous, subagent) deny automatically. Never show an
  approval card that nobody can answer.
- **Downloads are bounded while reading.** Use `sandbox/download.py`; the smaller
  of the caller limit and the provider limit applies. A size check after the read
  is too late.
- **Agent skill policy.** A thread with an explicit Agent policy gets its own
  skills projection. Subagents reuse the lead's filesystem view and never rebuild
  it.

## Tools

- Tool execution depends on operational arguments only. The `description`
  argument is a progress label and may be empty.
- Local writes publish a new file revision atomically and keep symlink targets and
  file metadata. Check write access without truncating the file.
- Line endings are data. Full reads return the stored endings, and `str_replace`
  matches the endings of the file. Remote providers split with `split_file_lines`,
  because `splitlines()` also splits on other Unicode separators.
- A failed or incomplete directory traversal is an error. Returning a partial
  listing makes the model believe that files do not exist.
- Same-path write serialization is scoped to `(sandbox.id, path)`. Two isolated
  sandboxes use the same virtual paths and must not contend.

## Adding a provider

Reuse the shared pieces: `derive_sandbox_scope_token`, `AcquireSerializer`,
`WarmPoolLifecycleMixin` and the ownership store in
[aio_sandbox](../community/aio_sandbox/AGENTS.md). Scoped command hooks default to
pass-through, so a provider without server-side sessions needs no change.
