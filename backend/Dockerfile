# Backend Dockerfile — multi-stage build
# Stage 1 (builder): compiles native Python extensions with build-essential
# Stage 2 (dev):     retains toolchain for dev containers (uv sync at startup)
# Stage 3 (runtime): clean image without compiler toolchain for production

# UV source image (override for restricted networks that cannot reach ghcr.io)
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11.1
ARG PYTHON_IMAGE=python:3.12-slim-bookworm
ARG DOCKER_CLI_IMAGE=docker:cli
FROM ${UV_IMAGE} AS uv-source

# ── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM ${DOCKER_CLI_IMAGE} AS docker-cli-source

FROM ${PYTHON_IMAGE} AS builder

ARG NODE_MAJOR=22
ARG APT_MIRROR
ARG UV_INDEX_URL
ARG NPM_REGISTRY
ARG LARK_CLI_NPM_VERSION=1.0.65
# Optional extras to install (e.g. "postgres" for PostgreSQL support)
# Usage: docker build --build-arg UV_EXTRAS=postgres,discord ...
ARG UV_EXTRAS

# Prefer authenticated HTTPS package indexes, including for cached base images.
RUN sed -i "s|http://deb.debian.org|https://deb.debian.org|g" /etc/apt/sources.list.d/debian.sources

# Optionally override apt mirror for restricted networks (e.g. APT_MIRROR=mirrors.aliyun.com)
RUN if [ -n "${APT_MIRROR}" ]; then \
      sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
      sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list 2>/dev/null || true; \
    fi

# Install build tools + Node.js (build-essential needed for native Python extensions)
RUN apt-get update && apt-get install -y \
    curl \
    git \
    build-essential \
    gnupg \
    ca-certificates \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install the official Lark/Feishu CLI used by the managed Lark integration.
RUN if [ -n "${NPM_REGISTRY}" ]; then npm config set registry "${NPM_REGISTRY}"; fi \
    && npm install -g @larksuite/cli@${LARK_CLI_NPM_VERSION} \
    && lark-cli --version

# Install uv (source image overridable via UV_IMAGE build arg)
COPY --from=uv-source /uv /uvx /usr/local/bin/

# Set working directory
WORKDIR /app

# Copy backend source code
COPY backend ./backend

# Bound public dependency transport without changing locked artifacts.
ARG UV_CONCURRENT_DOWNLOADS=4
ARG UV_HTTP_TIMEOUT=30
ARG UV_BUILD_LOG
ARG UV_ARTIFACT_MIRROR

# Install dependencies with cache mount
# `redis` is always installed because Docker Compose defaults the stream bridge
# to Redis (DEER_FLOW_STREAM_BRIDGE_REDIS_URL); it is an optional extra elsewhere
# so slim non-Docker installs do not pull it.
# When UV_EXTRAS is set (comma- or whitespace-separated), installs optional dependencies.
RUN --mount=type=cache,target=/root/.cache/uv \
    sh -c 'cd backend && \
    set -f; \
    if [ -n "$UV_BUILD_LOG" ]; then export RUST_LOG="$UV_BUILD_LOG"; fi; \
    if [ -n "$UV_ARTIFACT_MIRROR" ]; then \
        lock_backup=$(mktemp); \
        cp uv.lock "$lock_backup" || exit 1; \
        lock_sha=$(sha256sum uv.lock); \
        trap '\''status=$?; trap - 0; cp "$lock_backup" uv.lock && test "$(sha256sum uv.lock)" = "$lock_sha" || exit 1; rm -f "$lock_backup"; exit "$status"'\'' 0; \
        trap "exit 129" 1; trap "exit 130" 2; trap "exit 143" 15; \
        python scripts/uv_artifact_mirror.py || exit 1; \
    fi; \
    extras_flags=""; \
    for extra in $(printf "%s" "$UV_EXTRAS" | tr "," " "); do \
        case "$extra" in \
            [!A-Za-z]* | *[!A-Za-z0-9_-]*) \
                echo "UV_EXTRAS entry $extra is invalid (must match [A-Za-z][A-Za-z0-9_-]*)" >&2; \
                exit 1; \
                ;; \
        esac; \
        extras_flags="$extras_flags --extra $extra"; \
    done; \
    UV_CONCURRENT_DOWNLOADS="$UV_CONCURRENT_DOWNLOADS" UV_HTTP_TIMEOUT="$UV_HTTP_TIMEOUT" UV_INDEX_URL=${UV_INDEX_URL:-https://pypi.org/simple} uv sync --locked --extra redis $extras_flags'

# UTF-8 locale prevents UnicodeEncodeError on Chinese/emoji content in minimal
# containers where locale configuration may be missing and the default encoding is not UTF-8.
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONIOENCODING=utf-8

# ── Stage 2: Dev ──────────────────────────────────────────────────────────────
# Retains compiler toolchain from builder so startup-time `uv sync` can build
# source distributions in development containers.
FROM builder AS dev

# Install Docker CLI (for DooD: allows starting sandbox containers via host Docker socket)
COPY --from=docker-cli-source /usr/local/bin/docker /usr/local/bin/docker

EXPOSE 8001

CMD ["sh", "-c", "cd backend && PYTHONPATH=. uv run --no-sync uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001"]

# ── Stage 3: Runtime ──────────────────────────────────────────────────────────
# Clean image without build-essential — reduces size (~200 MB) and attack surface.
FROM ${PYTHON_IMAGE} AS runtime

# Artifact MIME classification requires the standard table on slim runtime images.
RUN sed -i "s|http://deb.debian.org|https://deb.debian.org|g" /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends media-types \
    && rm -rf /var/lib/apt/lists/*

ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONIOENCODING=utf-8

# Copy Node.js runtime from builder (provides npx for MCP servers)
COPY --from=builder /usr/bin/node /usr/bin/node
COPY --from=builder /usr/lib/node_modules /usr/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/bin/npx \
    && LARK_CLI_BIN="$(node -p 'const bin=require("/usr/lib/node_modules/@larksuite/cli/package.json").bin; typeof bin === "string" ? bin : (bin["lark-cli"] || Object.values(bin)[0])')" \
    && ln -s "../lib/node_modules/@larksuite/cli/${LARK_CLI_BIN#./}" /usr/bin/lark-cli \
    && lark-cli --version

# Install Docker CLI (for DooD: allows starting sandbox containers via host Docker socket)
COPY --from=docker-cli-source /usr/local/bin/docker /usr/local/bin/docker

# Install uv (source image overridable via UV_IMAGE build arg)
COPY --from=uv-source /uv /uvx /usr/local/bin/

# Set working directory
WORKDIR /app

# Copy backend with pre-built virtualenv from builder
COPY --from=builder /app/backend ./backend

# Expose Gateway API port.
EXPOSE 8001

# Default command (can be overridden in docker-compose)
CMD ["sh", "-c", "cd backend && PYTHONPATH=. uv run --no-sync uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001"]

# One immutable role image is reused by central Gateway, B MCP and resident worker.
# Build with UV_EXTRAS=postgres,browser; startup runs the locked installed venv.
FROM runtime AS native-core
LABEL org.deerflow.native.executor_revision="e0001_execution_ledger" org.deerflow.native.native_revision="0035_native_fork_compatibility"
ENV PATH="/app/backend/.venv/bin:$PATH" \
    PYTHONPATH="/app/backend:/app/backend/packages/ecs-executor" \
    PLAYWRIGHT_BROWSERS_PATH=/opt/deerflow-browsers \
    UV_NO_SYNC=1
WORKDIR /app/backend
CMD ["python", "-m", "ecs_executor.resident"]

# Full role retains the native browser capability; core is only a main-path interim.
FROM native-core AS native-role
COPY --from=builder /etc/apt/sources.list.d/debian.sources /etc/apt/sources.list.d/debian.sources
RUN /app/backend/.venv/bin/python -m playwright install --with-deps chromium

# Preserve existing production Compose builds that do not specify a target.
FROM runtime AS production-default
