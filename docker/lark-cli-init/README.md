# lark-cli init image (Pattern A)

This image provisions the sandbox `lark-cli` runtime binary into a Kubernetes
sandbox Pod via an **init container + shared `emptyDir`**, instead of the Gateway
downloading Linux binaries from GitHub at install time and mounting them via
hostPath/PVC.

See the design at
[`docs/superpowers/specs/2026-07-21-lark-sandbox-init-container-design.md`](../../docs/superpowers/specs/2026-07-21-lark-sandbox-init-container-design.md).

## What it does

- **Build time** (network available): downloads and SHA-256-verifies the official
  `larksuite/cli` Linux release binaries and stages the runtime layout under
  `/opt/lark-cli`:

  ```
  /opt/lark-cli/bin/lark-cli            # arch-dispatch launcher (uname -m)
  /opt/lark-cli/linux-amd64/lark-cli
  /opt/lark-cli/linux-arm64/lark-cli
  /opt/lark-cli/.deerflow-lark-cli-runtime.json   # {"version": "vX.Y.Z"}
  ```

  This is byte-identical to what the Gateway writer
  (`_write_lark_cli_sandbox_launcher`) produces and what
  `_validate_lark_cli_sandbox_runtime` enforces, so the sandbox PATH contract
  (`/mnt/integrations/lark-cli/runtime/bin/lark-cli`) is unchanged.

- **Run time**: copies `/opt/lark-cli/.` into the emptyDir mounted at
  `${LARK_CLI_RUNTIME_DEST}` (default `/mnt/integrations/lark-cli/runtime`) and
  exits `0`.

## Build

```bash
docker build -t deer-flow/lark-cli-init:v1.0.65 \
  --build-arg LARK_CLI_VERSION=v1.0.65 \
  docker/lark-cli-init
```

The tag should encode the lark-cli version so it can be bumped independently of
the upstream `all-in-one-sandbox` sandbox image.

## Wiring it into the provisioner

The init-container runtime path is **opt-in** and off by default. Enable it by
publishing this image and pointing the provisioner at it:

- Set `LARK_CLI_INIT_IMAGE` on the provisioner service to the published tag
  (e.g. `deer-flow/lark-cli-init:v1.0.65`). Empty ⇒ legacy hostPath / Gateway
  download path (no behavior change).
- When set, the provisioner adds a `lark-cli-runtime` `emptyDir` volume, an
  `lark-cli-init` init container, and a read-only runtime mount on the sandbox
  container — and ignores any `/mnt/integrations/lark-cli/runtime` hostPath/PVC
  extra mount (the init container supersedes it). The per-user `config` / `data`
  credential mounts are unchanged.
- The provisioner reports whether it is configured via `GET /api/capabilities`
  (`{"lark_cli_init_image": true|false}`), which the Gateway surfaces as the
  Lark integration sandbox-runtime readiness signal in `/api/integrations/lark/status`.

> Publishing note: this repository currently ships only backend/frontend images.
> Publishing a `lark-cli-init` tag is a fast-follow; until then the feature stays
> behind the empty-default `LARK_CLI_INIT_IMAGE`.
