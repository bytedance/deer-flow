# Backend Dockerfile — multi-stage build
# Stage 1 (builder): compiles native Python extensions with build-essential
# Stage 2 (dev):     retains toolchain for dev containers (uv sync at startup)
# Stage 3 (runtime): clean image without compiler toolchain for production

# UV source image (override for restricted networks that cannot reach ghcr.io)
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.7.20
FROM ${UV_IMAGE} AS uv-source

# ── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/python:3.12-slim-bookworm AS builder

ARG NODE_MAJOR=22
ARG APT_MIRROR
ARG UV_INDEX_URL
# Optional extras to install (e.g. "postgres" for PostgreSQL support)
# Usage: docker build --build-arg UV_EXTRAS=postgres ...
ARG UV_EXTRAS

# Alibaba Cloud Debian mirror for restricted networks
RUN sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
    sed -i 's|https://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true

# Install build tools + Node.js from mirror
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY --from=swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/node:22-slim /usr/local/bin/node /usr/local/bin/
COPY --from=swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/node:22-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# Install uv (source image overridable via UV_IMAGE build arg)
COPY --from=uv-source /uv /uvx /usr/local/bin/

# Set working directory
WORKDIR /app

# Copy backend source code
COPY backend ./backend

# Install dependencies (no cache mount — all packages must be baked into image for offline use)
# When UV_EXTRAS is set (e.g. "postgres"), installs optional dependencies.
# --frozen: do not update lock file (requires uv.lock to exist)
# UV_LINK_MODE=copy: copy packages into venv instead of linking from cache
RUN --mount=type=cache,target=/root/.cache/uv,uid=0 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    sh -c "cd backend && UV_INDEX_URL=${UV_INDEX_URL:-https://pypi.org/simple} uv sync --all-packages ${UV_EXTRAS:+--extra $UV_EXTRAS}"

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
COPY --from=swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/docker:cli /usr/local/bin/docker /usr/local/bin/docker

EXPOSE 8001 2024

CMD ["sh", "-c", "cd backend && PYTHONPATH=. uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001"]

# ── Stage 3: Runtime ──────────────────────────────────────────────────────────
# Clean image without build-essential — reduces size (~200 MB) and attack surface.
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/python:3.12-slim-bookworm

ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONIOENCODING=utf-8

# Copy Node.js runtime from builder (provides npx for MCP servers)
COPY --from=builder /usr/local/bin/node /usr/local/bin/node
COPY --from=builder /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/bin/npx

# Install Docker CLI (for DooD: allows starting sandbox containers via host Docker socket)
COPY --from=swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/docker:cli /usr/local/bin/docker /usr/local/bin/docker

# Install uv (source image overridable via UV_IMAGE build arg)
COPY --from=uv-source /uv /uvx /usr/local/bin/

# Set working directory
WORKDIR /app

# Copy backend with pre-built virtualenv from builder
COPY --from=builder /app/backend ./backend

# Expose ports (gateway: 8001, langgraph: 2024)
EXPOSE 8001 2024

# Default command (can be overridden in docker-compose)
CMD ["sh", "-c", "cd backend && PYTHONPATH=. uv run --no-sync uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001"]
