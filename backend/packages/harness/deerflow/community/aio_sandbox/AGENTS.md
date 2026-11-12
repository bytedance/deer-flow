# AIO sandbox provider (`deerflow/community/aio_sandbox/`)

The container sandbox provider: local Docker and Apple Container, and remote Pods
through the provisioner. It creates, reuses, quarantines and destroys sandboxes,
and runs commands in them. General sandbox rules are in the
[sandbox guide](../../sandbox/AGENTS.md).

## Verify

```bash
cd backend
python -m pytest tests -q -k "aio_sandbox or sandbox_quarantine or remote_sandbox or provisioner or lark_broker"
make test-blocking-io
```

## Ownership across Gateways

- **The ownership lease answers "who reaps this sandbox", not "who may use it".**
  Authorization is a separate check.
- **The store fails closed in both directions.** An unreadable owner is not
  adopted, and an unconfirmed release is not treated as released.
- **A delete marker is held for the whole stop**, so that a peer cannot adopt a
  sandbox that is being destroyed. Adoption is a promotion of an existing record,
  and a sandbox is active or warm, never both.
- **The lease excludes peers, not this process.** Exclusion inside one process
  comes from the local teardown reservation and the acquire epoch. Check again
  after every round trip to the store.
- **Renewal does not depend on `idle_timeout`.** A lapsed lease and a lost lease
  are different results of `renew()`; keep them apart.
- **The `memory` store is for a single instance.** Gateways that share containers
  share the store and `DEER_FLOW_HOME`, which holds the quarantine records.
- **`get()` never performs storage I/O.** It runs on hot paths.

## Absence, quarantine and reuse

- **Only a confirmed absence retires a record.** An accepted DELETE, a discovery
  that returns nothing, a stopped container or a failed probe proves nothing. A
  probe failure raises. The remote proof inspects the Pod, because the status
  route returns 404 when only the Service is missing.
- **An unknown generation is fenced.** A quarantine record is bound to the
  container ID or Pod UID, and a failed stop, a lease expiry or a Gateway restart
  never clears it.
- **An implicit-shell fence lasts for the container's lifetime**, also after a
  successful recovery session. The container is recycled once no execution
  holds it.
- **A port reservation is returned only when creation definitely did not
  happen.** In restricted mode the proxy can already own the port, so a failed
  sandbox CLI call does not prove that. Compare the reservation token before you
  release, so a late failure cannot free a successor's port.
- **A broker capability failure is unknown, not a negative.** Cache successful
  observations only. An attested mode of a running Pod outranks a failed
  deployment-level probe, and a policy change never stops a live peer's Pod.
- **Locks never cover network I/O or slow cleanup.**

## Commands

- **The two transports have different stdin.** The persistent shell is a PTY. A
  fresh `bash` call is a pipe that stays open, so it is prefixed with
  `exec < /dev/null` to give the command an immediate EOF. Do not wrap the command
  in a brace group or `eval`: that changes top-level parsing, `PIPESTATUS` and
  `ERR` traps.
- **Execution is never retried.** A command may have had effects. Missing command
  state or a missing cleanup receipt quarantines the sandbox.
- **Cleanup markers support cooperative cleanup.** They do not isolate hostile
  code.
- **Broker logs carry argument count, exit code and duration**, never argument
  values.
- **`read_file` returns content or an `Error: ...` string and never raises.** A
  missing file is expected when a write probes first, and is logged at debug.

## Restricted network mode

- **The sandbox stays on an internal network**, and a per-sandbox sidecar handles
  egress. Reject a host that the policy denies before any DNS lookup.
- **An approval never replays a tool call.** Subagent and non-interactive runs
  deny without asking.
- **Discovery and enumeration are read-only**, also when the policy or network
  mode does not match. Only the provider replaces a sandbox, under the teardown
  reservation and the cross-instance lease. The sandbox, its sidecar and both
  networks are destroyed together.

## Shutdown

- **`shutdown()` closes admission first and never reopens it**, also when a failed
  teardown leaves it retryable. A refused create rolls back its container.
- **Under the Gateway the provider installs no SIGTERM or SIGINT handler.** The
  handler would destroy every sandbox on the event-loop thread before the run
  drain. The lifespan hook shuts the provider down after the drain. The signal
  handlers remain for hosts without a lifespan, such as the embedded client.
- **Build the readiness client off the event loop**, and close a client that
  arrives after the caller was cancelled.
