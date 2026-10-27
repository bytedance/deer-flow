# syntax=docker/dockerfile:1
#
# DeerFlow "lark-cli init" image (Pattern A).
#
# Purpose: provide the sandbox `lark-cli` runtime binary to a Kubernetes sandbox
# Pod via an init container + shared `emptyDir`, instead of downloading Linux
# binaries from GitHub at install time and mounting them via hostPath/PVC.
#
# At BUILD time (network available) this image downloads and SHA-256-verifies the
# official `larksuite/cli` Linux release binaries and stages the runtime layout:
#
#   /opt/lark-cli/bin/lark-cli            # arch-dispatch launcher (uname -m)
#   /opt/lark-cli/linux-amd64/lark-cli
#   /opt/lark-cli/linux-arm64/lark-cli
#   /opt/lark-cli/.deerflow-lark-cli-runtime.json   # {"version": "vX.Y.Z"}
#
# This layout is byte-identical to what the Gateway writer
# (`_write_lark_cli_sandbox_launcher`) produces and what
# `_validate_lark_cli_sandbox_runtime` enforces, so the sandbox PATH contract
# (`/mnt/integrations/lark-cli/runtime/bin/lark-cli`) is unchanged.
#
# At RUN time the default command copies `/opt/lark-cli/.` into the shared
# emptyDir mounted at `/mnt/integrations/lark-cli/runtime` and exits.
#
# The image tag should encode the lark-cli version so it can be bumped
# independently of the upstream `all-in-one-sandbox` image.
#
# Build (defaults to the pinned version below):
#   docker build -t deer-flow/lark-cli-init:v1.0.65 \
#     --build-arg LARK_CLI_VERSION=v1.0.65 docker/lark-cli-init

FROM debian:bookworm-slim AS builder

ARG APT_MIRROR
# Version tag on the larksuite/cli GitHub releases (with or without leading "v").
ARG LARK_CLI_VERSION=v1.0.65

RUN if [ -n "${APT_MIRROR}" ]; then \
      sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
      sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list 2>/dev/null || true; \
    fi

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY build-runtime.sh /usr/local/bin/build-runtime.sh
RUN chmod +x /usr/local/bin/build-runtime.sh \
    && LARK_CLI_VERSION="${LARK_CLI_VERSION}" /usr/local/bin/build-runtime.sh /opt/lark-cli

# ── Final image: minimal, just the staged runtime + a copy entrypoint ────────
FROM debian:bookworm-slim

COPY --from=builder /opt/lark-cli /opt/lark-cli
COPY entrypoint.sh /usr/local/bin/lark-cli-init
RUN chmod +x /usr/local/bin/lark-cli-init

# Destination is the emptyDir the provisioner mounts into both this init
# container and the main sandbox container.
ENV LARK_CLI_RUNTIME_DEST=/mnt/integrations/lark-cli/runtime

ENTRYPOINT ["/usr/local/bin/lark-cli-init"]
