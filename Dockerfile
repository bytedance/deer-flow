# syntax=docker/dockerfile:1

FROM python:3.12-slim-bookworm AS builder

ARG DEER_FLOW_REPO=https://github.com/bytedance/deer-flow.git

# Clone only the source we need (not .git history)
WORKDIR /src
RUN apt-get update && apt-get install -y git \
    && git clone --depth=1 --filter=blob:none --sparse ${DEER_FLOW_REPO} . \
    && git sparse-checkout set backend frontend

# Build backend
WORKDIR /src/backend
RUN pip install uv && uv sync --no-dev

# Build frontend
WORKDIR /src/frontend
RUN corepack enable && corepack enable pnpm \
    && pnpm install && pnpm build

# ── Runner image ─────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS runner

# Install ALL runtime deps in one layer
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl nginx ca-certificates gnupg lsb-release sudo docker.io \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
      | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
      > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y nodejs \
    && apt-get autoremove \
    && rm -rf /var/lib/apt/lists/* \
    && dockerd --version

# Install uv
COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv

# Clone source into /app (no build context needed)
WORKDIR /app
RUN git clone --depth=1 ${DEER_FLOW_REPO} . \
    && git sparse-checkout init --cone \
    && git sparse-checkout set backend frontend

# Copy built artifacts from builder
COPY --from=builder /src/backend /app/backend
COPY --from=builder /src/frontend /app/frontend

# Deployment scripts
COPY start.sh /app/start.sh
COPY deploy.sh /app/deploy.sh
RUN chmod +x /app/start.sh /app/deploy.sh

ENV CI=true
ENV DEER_FLOW_HOME=/persist/.deer-flow
ENV DEER_FLOW_CONFIG_PATH=/app/config.yaml
ENV PYTHONPATH=/app/backend:$PYTHONPATH
ENV NODE_ENV=production
ENV PORT=8080

EXPOSE 8080

ENTRYPOINT ["/app/start.sh"]
