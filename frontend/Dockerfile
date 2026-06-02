# Frontend Dockerfile
# Supports two targets:
#   --target dev   — install deps only, src mounted via volume at runtime
#   --target prod  — full build baked in, run `pnpm start` at container start (default if no --target is specified)

ARG PNPM_STORE_PATH=/root/.local/share/pnpm/store
ARG NPM_REGISTRY

# ── Base: shared setup ────────────────────────────────────────────────────────
FROM node:22-alpine AS base
ARG PNPM_STORE_PATH
ARG NPM_REGISTRY
# Configure corepack registry before installing pnpm so the download itself
# succeeds in restricted networks (COREPACK_NPM_REGISTRY controls where
# corepack fetches package managers from).
RUN if [ -n "${NPM_REGISTRY}" ]; then \
      export COREPACK_NPM_REGISTRY="${NPM_REGISTRY}"; \
    fi && \
    corepack enable && corepack install -g pnpm@10.26.2
RUN pnpm config set store-dir ${PNPM_STORE_PATH}
# Optionally override npm registry for restricted networks (e.g. NPM_REGISTRY=https://registry.npmmirror.com)
RUN if [ -n "${NPM_REGISTRY}" ]; then pnpm config set registry "${NPM_REGISTRY}"; fi
WORKDIR /app

# ── Deps: install only when package.json / lockfile change ────────────────────
# By COPYing only the dependency manifests + config files before RUN install,
# Docker's layer cache keeps this step cached as long as these files are
# unchanged. Source code (src/) is mounted via volume at runtime, not baked in.
FROM base AS deps
# Config files (rarely change — good cache candidates)
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./frontend/
COPY frontend/postcss.config.js frontend/components.json ./frontend/
COPY frontend/next.config.js frontend/tsconfig.json ./frontend/
# Install dependencies. BuildKit cache mount persists pnpm store across builds —
# even when package.json changes, already-downloaded packages skip re-download.
# The store path must match what pnpm config set store-dir configured above.
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    cd /app/frontend && pnpm install --frozen-lockfile

# ── Dev: inherit deps, source is mounted via volume at runtime ────────────────
FROM deps AS dev
EXPOSE 3000

# ── Builder: install + copy full source + compile Next.js ─────────────────────
FROM deps AS builder
COPY frontend ./frontend
# Skip env validation — runtime vars are injected by nginx/container
RUN cd /app/frontend && SKIP_ENV_VALIDATION=1 pnpm build

# ── Prod: minimal runtime with pre-built output ───────────────────────────────
FROM node:22-alpine AS prod
ARG PNPM_STORE_PATH
ARG NPM_REGISTRY
RUN if [ -n "${NPM_REGISTRY}" ]; then \
      export COREPACK_NPM_REGISTRY="${NPM_REGISTRY}"; \
    fi && \
    corepack enable && corepack install -g pnpm@10.26.2
RUN pnpm config set store-dir ${PNPM_STORE_PATH}
RUN if [ -n "${NPM_REGISTRY}" ]; then pnpm config set registry "${NPM_REGISTRY}"; fi
WORKDIR /app
COPY --from=builder /app/frontend ./frontend
EXPOSE 3000
CMD ["sh", "-c", "cd /app/frontend && pnpm start"]
