# OpenSandbox backend

Runs DeerFlow sandboxes on [OpenSandbox](https://github.com/opensandbox-group/OpenSandbox),
using the synchronous Python SDK behind DeerFlow's `Sandbox` and
`SandboxProvider` contracts.

## Installation and configuration

Install the optional SDK, then select the provider:

```bash
pip install "deerflow-harness[opensandbox]"
```

```yaml
sandbox:
  use: deerflow.community.opensandbox:OpenSandboxProvider
  image: python:3.11
  # api_key: $OPEN_SANDBOX_API_KEY
  # domain: localhost:8080
  # protocol: http
  # request_timeout: 30
  # ready_timeout: 30
  # use_server_proxy: false
  # sandbox_timeout: 14400  # remote lifetime; 0 means explicit cleanup only
  # bash_command_timeout: 600  # default command timeout
  # replicas: 3             # active + warm sandboxes per gateway process
  # idle_timeout: 600       # warm seconds before destroy; 0 disables reaping
  # environment:
  #   PYTHONUNBUFFERED: "1"
```

`api_key` and `domain` may be omitted when `OPEN_SANDBOX_API_KEY` and
`OPEN_SANDBOX_DOMAIN` are set. `use_server_proxy` is useful when DeerFlow can
reach the OpenSandbox management service but cannot directly reach sandbox
`execd` endpoints.

Values in `sandbox.environment` that start with `$` are resolved from the
Gateway process environment when the provider starts. Missing variables resolve
to an empty string, matching the E2B provider.

## Lifecycle and contract

The provider derives a stable local ID from `(user_id, thread_id)`. A released
sandbox enters an in-process warm pool and only the same scope may reclaim it.
Create returns only after the SDK readiness check and DeerFlow's
`/mnt/user-data/{workspace,uploads,outputs}` bootstrap succeed. A bootstrap
failure explicitly destroys the newly created remote sandbox.
Each remote has an independent SDK connection transport. Before an operation,
the adapter renews `sandbox_timeout`; commands use `bash_command_timeout` when
the caller supplies no timeout and extend the renewal horizon when necessary.
Operations are serialized per remote so a shorter renewal cannot overwrite the
horizon of an in-flight long command.
Setting `sandbox_timeout: 0` selects explicit-cleanup mode and disables renewal.

The full DeerFlow surface is implemented:

- `execute_command` forwards per-call environment variables and positive
  wall-clock timeouts through `RunCommandOpts`, preserving stdout, stderr, and
  non-zero exit information in DeerFlow's string result.
- Text and binary file operations use OpenSandbox's native filesystem API.
  Append is serialized as a read-modify-write because SDK 0.1.x has no append
  primitive.
- `list_dir`, `glob`, and `grep` use portable `find`/`grep` commands and the
  shared DeerFlow result parsers.
- All paths must be absolute and traversal-free. Artifact downloads are further
  restricted to `/mnt/user-data`.
- Command-path HTTP 404, HTTP 410, unhealthy-session errors, and broken
  transports evict the dead client so the next acquire cold-starts a
  replacement. A file-path 404 remains an ordinary missing-file error.

`reset()` parks active clients for later cleanup; `shutdown()` destroys active
and warm remotes. Cross-process discovery and ownership coordination are not
implemented yet, so each Gateway process has its own warm pool and capacity
accounting.
