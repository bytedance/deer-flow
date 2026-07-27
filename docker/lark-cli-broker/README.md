# lark-cli broker image (Pattern B)

This image implements **Pattern B** (issue #4338): instead of mounting the
per-user Lark credential directories into the sandbox (Pattern A still does), a
long-running **sidecar** holds `lark-cli` + the credentials and serves only the
command surface over loopback. The sandbox gets a tiny `lark-cli` **shim** on
`PATH` that forwards argv/stdin to the sidecar.

Result: the raw `appSecret` / OAuth token files **never exist in the sandbox
filesystem**, so a compromised or prompt-injected agent can no longer
`cat`/exfiltrate them — while any authorized `lark-cli` subcommand still runs.

See the design at
[`docs/superpowers/specs/2026-07-27-lark-sandbox-credential-broker-design.md`](../../docs/superpowers/specs/2026-07-27-lark-sandbox-credential-broker-design.md).

## Two modes, one image

Dispatched by the first CLI argument:

- `install-shim <dest>` — **init container**: writes the Python shim +
  `.deerflow-lark-cli-runtime.json` (`kind: "shim"`) into the shared `emptyDir`
  at `<dest>` (default `/mnt/integrations/lark-cli/runtime`), then exits `0`. The
  sandbox then finds `bin/lark-cli` exactly where
  `lark_cli_env_overlay(sandbox_paths=True)` points `PATH` — same layout the
  Pattern A init image produces.
- `serve` (default `CMD`) — **sidecar**: runs the broker HTTP server on
  `127.0.0.1:8788` with the real `lark-cli` and the credential env pointing at
  the sidecar-only `/var/lark/{config,data}` mounts.

The shim is written from the in-process constant `LARK_CLI_BROKER_SHIM_SCRIPT`
(`deerflow.integrations.lark_broker`), so the image's shim can never drift from
the Gateway's copy.

## Build

Build context is the **repo root** (the broker module lives under `backend/`):

```bash
docker build -t deer-flow/lark-cli-broker:v1.0.65 \
  --build-arg LARK_CLI_VERSION=v1.0.65 \
  -f docker/lark-cli-broker/Dockerfile .
```

The tag should encode the lark-cli version so it can be bumped independently of
the upstream `all-in-one-sandbox` image.

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

> Publishing note: this repository currently ships only backend/frontend images.
> Publishing a `lark-cli-broker` tag is a fast-follow; until then the feature
> stays behind the empty-default `LARK_CLI_BROKER_IMAGE`.

## Broker HTTP contract (loopback)

- `POST /v1/exec` — body `{"args": [...], "stdin_b64": "...", "cwd": "..."}`;
  response `{"exit_code", "stdout_b64", "stderr_b64", "truncated"}`. `args` is run
  with `shell=False`, so a sandbox-supplied argument can never be shell-injected.
  The broker injects the credential env itself; the client cannot override it.
- `GET /v1/health` — `{"ok": true}`.

Bound to loopback only. In K8s the sandbox and sidecar share the Pod network
namespace, so `127.0.0.1` reaches the sidecar and nothing outside the Pod can.
