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
Gateway process environment once, when `config.yaml` loads; a missing variable
fails the load. The provider injects the resolved values unchanged, so a secret
that itself starts with `$` reaches the sandbox intact.

## Lifecycle and contract

The provider derives a stable local ID from `(user_id, thread_id)`. A released
sandbox enters an in-process warm pool and only the same scope may reclaim it.
Before parking a user/thread-scoped sandbox, the provider copies regular files
from `/mnt/user-data/outputs` to that owner's local thread outputs directory.
This makes generated artifacts available to Gateway previews and downloads after
the turn finishes. Nested paths and binary content are preserved; uploads and
workspace files are not mirrored. The same scope waits for this copy before its
next acquire.

Output synchronization is best effort: failures log a warning and preserve any
previous complete local copy. Each pass processes at most 2,000 files, a 512 KiB
listing and 512 MiB of downloaded content, with a 100 MiB per-file limit. An
oversized listing skips the pass; a failed or oversized download stops the pass
because a partial stream cannot be charged accurately to the remaining budget.
A 120-second
cooperative deadline is checked between files and download chunks; an active SDK
read is bounded by `request_timeout`, so this is not a hard wall-clock limit.
The listing requires `find`, `head`, `base64` and `mktemp` in the remote image.
If `find` reports a traversal error, complete NUL-framed records are still
mirrored with a warning; oversized or incomplete listings and failed pipeline
stages skip the pass.
Remote links are not followed and linked local destinations are rejected.
Mirrored names must also be portable host paths: traversal, backslashes, colons,
Windows reserved components and components ending in a space or dot are skipped
with a warning, including when the Gateway runs on Unix.
The entire accepted listing is checked before any download for names that differ
only by case or Unicode normalization, including directory components and records
beyond the file limit. All outputs under an ambiguous component are skipped, on
every host, so one remote report cannot overwrite another on a case-insensitive
volume. A path that aliases a differently spelled existing local file or directory
is also skipped; previous complete copies are preserved. Unambiguous outputs
continue to be mirrored.
Files deleted remotely are not removed from the local outputs directory.
Non-UTF-8 filename records are skipped individually with a warning and still
count against the file limit. Each release revisits retained outputs, including
unchanged files; equal file size does not prove equal content. Large accumulated
output directories may reach the pass limits before all files are mirrored.

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
  non-zero exit information in DeerFlow's string result. An explicit
  `CommandExecError` with value `context deadline exceeded` and no numeric
  exit code ends with `Error: command timed out` and `Exit Code: 124`, keeping
  any partial output. Transport exceptions and other missing-code errors keep
  their existing error reporting. Numeric exits, including signal termination
  (`-1`), keep their own code: a signal-only event does not identify whether a
  command deadline or another kill caused it. Servers that expose only that
  signal status need additional deadline information before it can safely be
  normalized to 124.
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
