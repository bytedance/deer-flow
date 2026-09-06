# lark-cli broker image (Pattern B)

This image implements **Pattern B** (issue #4338): instead of mounting the
per-user Lark credential directories into the sandbox (Pattern A still does), a
long-running **sidecar** holds `lark-cli` + the credentials and serves only the
command surface over loopback. The sandbox gets a tiny `lark-cli` **shim** on
`PATH` that forwards argv/stdin to the sidecar.

Result: the raw `appSecret` / OAuth token files **never exist in the sandbox
filesystem**, so a compromised or prompt-injected agent can no longer
`cat`/exfiltrate them — while any authorized `lark-cli` subcommand still runs.

## Two modes, one image

Dispatched by the first CLI argument:

- `install-shim <dest>` — **init container**: writes the launcher + Python shim +
  `.deerflow-lark-cli-runtime.json` (`kind: "shim"`) into the shared `emptyDir`
  at `<dest>` (default `/mnt/integrations/lark-cli/runtime`), then exits `0`. The
  sandbox then finds `bin/lark-cli` exactly where
  `lark_cli_env_overlay(sandbox_paths=True)` points `PATH` — same layout the
  Pattern A init image produces.
- `serve` (default `CMD`) — **sidecar**: runs the broker HTTP server on
  `127.0.0.1:8788` with the real `lark-cli` and the credential env pointing at
  the sidecar-only `/var/lark/{config,data}` mounts.

The executable on `PATH` (`bin/lark-cli`) is a `/bin/sh` **launcher** that
resolves a Python 3 interpreter and execs the **shim body** (`bin/lark-cli-shim.py`)
beside it (by its baked-in absolute path, since `$0` is the bare command name
when run off `PATH`); both are written from the in-process
`LARK_CLI_BROKER_LAUNCHER_TEMPLATE` / `LARK_CLI_BROKER_SHIM_SCRIPT`
(`deerflow.integrations.lark_broker`), so the image's copies can never drift from
the Gateway's. Splitting the sh launcher from the Python body means broker mode
does **not** hard-depend on `python3` resolving via a `#!/usr/bin/env python3`
shebang: if no `python3`/`python` is on the sandbox `PATH`, the launcher exits
`127` with an actionable message (set `DEERFLOW_LARK_BROKER_PYTHON` to a known
interpreter path) instead of an opaque ENOEXEC. The stock `all-in-one-sandbox`
image ships Python 3, so the default path needs no configuration.

## Build

Build context is the **repo root** (the broker module lives under `backend/`):

```bash
docker build -t deer-flow/lark-cli-broker:v1.0.65 \
  --build-arg LARK_CLI_VERSION=v1.0.65 \
  -f docker/lark-cli-broker/Dockerfile .
```

The tag should encode the lark-cli version so it can be bumped independently of
the upstream `all-in-one-sandbox` image.

CI publishes multi-arch (`linux/amd64,linux/arm64`) images to
`ghcr.io/<owner>/deer-flow-lark-cli-broker:<lark-cli-version>` via
`.github/workflows/lark-cli-images.yaml` (run it with a `lark_cli_version` input,
or push a `lark-cli-v*` tag). This is decoupled from the DeerFlow `v*` release
because the image tracks the upstream `larksuite/cli` version.

## Wiring it into the provisioner

Broker mode is **opt-in** and off by default. Enable it by publishing this image
and pointing the provisioner at it:

- Set `LARK_CLI_BROKER_IMAGE` on the provisioner to the published tag. Empty ⇒
  broker off (Pattern A / legacy path, no behavior change).
- When set, and the Gateway sends `provision_lark_cli_broker` on sandbox create,
  the provisioner adds:
  - a `lark-cli-runtime` `emptyDir` shared by an init container and the sandbox;
  - a `lark-cli-shim-init` init container (`install-shim`) that stages the shim;
  - a `lark-cli-broker` **sidecar** (`serve`) with the per-user `config` (RO) /
    `data` (RW) credential mounts — **into the sidecar only**;
  - the sandbox container gets the runtime RO mount + `DEERFLOW_LARK_BROKER_URL`
    and **no** `config`/`data` mounts.
- Broker mode **supersedes** Pattern A when both are configured.
- The provisioner reports it via `GET /api/capabilities`
  (`{"lark_cli_broker_image": true|false}`), which the Gateway surfaces as the
  Lark integration sandbox-runtime readiness signal in
  `/api/integrations/lark/status` (`sandbox_runtime_mode: "broker"`).

> Opt-in note: broker mode stays off until `LARK_CLI_BROKER_IMAGE` is set on the
> provisioner, so an unpublished or unconfigured image is a no-op (Pattern A /
> legacy path, no behavior change).

## Broker HTTP contract (loopback)

- `POST /v1/exec` — body `{"args": [...], "stdin_b64": "..."}`; response
  `{"exit_code", "stdout_b64", "stderr_b64", "truncated"}`. `args` is run with
  `shell=False`, so a sandbox-supplied argument can never be shell-injected. The
  broker injects the credential env itself; the client cannot override it.
  Unexpected broker-side errors return a `500 {"error": ...}` so the shim always
  gets a structured response rather than an opaque transport failure.
- `GET /v1/health` — `{"ok": true}`.

Bound to loopback only. In K8s the sandbox and sidecar share the Pod network
namespace, so `127.0.0.1` reaches the sidecar and nothing outside the Pod can.

### No file I/O relative to the sandbox cwd

The broker runs `lark-cli` in the **sidecar's** working directory and cannot see
the sandbox filesystem, so the sandbox's cwd is intentionally **not** forwarded.
`lark-cli` subcommands that read or write files by a path relative to the
sandbox cwd (e.g. uploading a local file) are therefore unsupported in broker
mode — this is a command-surface-only bridge, not a filesystem bridge. Absolute
paths still refer to the sidecar's filesystem, not the sandbox's.

### Optional subcommand denylist (hardening)

The broker removes the credential *files* from the sandbox, but the full
`lark-cli` command surface stays reachable, so any subcommand that prints/exports
tokens could still exfiltrate them. Set `DEERFLOW_LARK_BROKER_DENY_SUBCOMMANDS`
on the sidecar to a comma-separated list of command prefixes the broker should
refuse (matched against the leading non-flag tokens), e.g.
`DEERFLOW_LARK_BROKER_DENY_SUBCOMMANDS="config show, auth token"`. Denied calls
return exit `126` with a `subcommand ... is disabled` message and never spawn the
binary. Empty by default (no behavior change); confirm the deployed `lark-cli`
version's subcommand surface has no trivial secret-dump command before enabling
broker mode in production.
