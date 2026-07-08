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
# --fix-missing: tolerate occasional 5xx errors on individual packages
RUN apt-get update && apt-get install -y --no-install-recommends --fix-missing \
    curl \
    build-essential \
    # Common CLI / debugging tools (baked in for offline / LAN-restricted runs)
    ca-certificates \
    gnupg \
    git \
    tini \
    jq \
    yq \
    wget \
    curl \
    unzip \
    zip \
    xz-utils \
    p7zip-full \
    less \
    vim-tiny \
    nano \
    tree \
    file \
    xxd \
    procps \
    htop \
    lsof \
    psmisc \
    strace \
    iputils-ping \
    iproute2 \
    dnsutils \
    net-tools \
    traceroute \
    tcpdump \
    && rm -rf /var/lib/apt/lists/*
COPY --from=swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/node:22.19.0-bookworm /usr/local/bin/node /usr/local/bin/
COPY --from=swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/node:22.19.0-bookworm /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# Install uv (source image overridable via UV_IMAGE build arg)
COPY --from=uv-source /uv /uvx /usr/local/bin/

# Set working directory
WORKDIR /app

# Copy backend source code
COPY backend ./backend

# Install dependencies with cache mount
# `redis` is always installed because Docker Compose defaults the stream bridge
# to Redis (DEER_FLOW_STREAM_BRIDGE_REDIS_URL); it is an optional extra elsewhere
# so slim non-Docker installs do not pull it.
# When UV_EXTRAS is set (comma- or whitespace-separated), installs optional dependencies.
RUN --mount=type=cache,target=/root/.cache/uv \
    sh -c 'cd backend && \
    set -f; \
    extras_flags="--extra postgres"; \
    for extra in $(printf "%s" "$UV_EXTRAS" | tr "," " "); do \
        case "$extra" in \
            [!A-Za-z]* | *[!A-Za-z0-9_-]*) \
                echo "UV_EXTRAS entry $extra is invalid (must match [A-Za-z][A-Za-z0-9_-]*)" >&2; \
                exit 1; \
                ;; \
        esac; \
        extras_flags="$extras_flags --extra $extra"; \
    done; \
    UV_INDEX_URL=${UV_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/} uv sync --extra redis $extras_flags'

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

# ── Install Claude Code CLI (offline bundled) ──────────────────────────────
# 离线环境：把 bundle 脚本产出的整个 npm prefix (bin/ + lib/node_modules/ 全量)
# 一次性解压到 /usr/local。gateway 通过 claude_provider.py (import anthropic) 调
# Anthropic API，claude CLI 仅用于容器内 `claude login` 生成 OAuth 凭据。
# 产物路径：offline-claude/claude-code-bundled-${VERSION}-${PLATFORM}.tar.gz
# 由 scripts/bundle-claude-code.sh 在 Linux x86 runner 上生成。
# 切换到其它平台（如 linux-arm64、alpine/musl）只需改 CLAUDE_CODE_PLATFORM，
# 并把对应 tarball 放到 offline-claude/ 下，无需改 Dockerfile 其它部分。
ARG CLAUDE_CODE_VERSION=2.1.139
ARG CLAUDE_CODE_PLATFORM=linux-x64
COPY offline-claude/claude-code-bundled-${CLAUDE_CODE_VERSION}-${CLAUDE_CODE_PLATFORM}.tar.gz /tmp/claude-bundle.tar.gz
RUN tar -xzf /tmp/claude-bundle.tar.gz -C /usr/local --no-same-owner \
    && rm /tmp/claude-bundle.tar.gz \
    && claude --version

# ── Install Claude Agent ACP (offline bundled) ─────────────────────────────
# 离线环境：把 @agentclientprotocol/claude-agent-acp 整包 vendor 到镜像，
# 这样 acp_agents.claude_code 配的 `npx -y @agentclientprotocol/claude-agent-acp`
ARG CLAUDE_AGENT_ACP_VERSION=0.42.0
COPY offline-claude/claude-agent-acp-bundled-${CLAUDE_AGENT_ACP_VERSION}-linux-x64.tar.gz /tmp/acp-bundle.tar.gz
RUN tar -xzf /tmp/acp-bundle.tar.gz -C /usr/local --no-same-owner \
    && rm /tmp/acp-bundle.tar.gz \
    && test -x /usr/local/bin/claude-agent-acp \
    && node -e "console.log('claude-agent-acp', require('/usr/local/lib/node_modules/@agentclientprotocol/claude-agent-acp/package.json').version)"

# ── Install Pi Coding Agent + pi-acp (offline bundled, opt-in) ─────────────
# pi-acp 在 stdio 通信时 shell out 调 `pi --mode rpc`，所以 acp_agents.pi
# 需要两个 bundle 同时 vendor：
#   1. @earendil-works/pi-coding-agent  (pi 二进制本身)
#   2. pi-acp                           (DeerFlow 调起的 ACP 适配器)
# 启用：uncomment 下面 + 把对应 tarball 放到 offline-claude/。
# 关闭（默认）：保持 commented，不影响镜像构建。
#
# 产物路径：
#   offline-claude/bundle-pi-coding-agent.sh → offline-claude/pi-coding-agent-bundled-${VERSION}-linux-x64.tar.gz
#   offline-claude/bundle-pi-acp.sh   → offline-claude/pi-acp-bundled-${VERSION}-linux-x64.tar.gz
# 两者都在 Linux x86_64 runner 上执行。
# pi-web **不** vendor 进镜像，它是独立 Web UI，与 DeerFlow 无联动。
ARG PI_CODING_AGENT_VERSION=0.78.1
ARG PI_ACP_VERSION=0.0.27
COPY offline-claude/pi-coding-agent-bundled-${PI_CODING_AGENT_VERSION}-linux-x64.tar.gz /tmp/pi-agent-bundle.tar.gz
RUN tar -xzf /tmp/pi-agent-bundle.tar.gz -C /usr/local --no-same-owner \
    && rm /tmp/pi-agent-bundle.tar.gz \
    && pi --version \
    && fd --version \
    && rg --version

COPY offline-claude/pi-acp-bundled-${PI_ACP_VERSION}-linux-x64.tar.gz /tmp/pi-acp-bundle.tar.gz
RUN tar -xzf /tmp/pi-acp-bundle.tar.gz -C /usr/local --no-same-owner \
    && rm /tmp/pi-acp-bundle.tar.gz \
    && test -x /usr/local/bin/pi-acp

# 离线兜底：pi 运行时若发现新 helper 缺失，默认会去 GitHub Releases 拉。
# 强制 PI_OFFLINE=1 让它直接 fail-fast（见 dist/utils/tools-manager.js
# 的 isOfflineModeEnabled()），避免在没网时挂死。
ENV PI_OFFLINE=1

# Shell convenience aliases — visible to `docker exec ... bash` (interactive bash
# sources /root/.bashrc) and login sh/bash sessions (source /etc/profile.d/*.sh).
RUN echo 'alias ll="ls -al"' > /etc/profile.d/ll.sh \
    && echo 'alias ll="ls -al"' >> /root/.bashrc

EXPOSE 8001 2024

CMD ["sh", "-c", "cd backend && PYTHONPATH=. uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001"]

# ── Stage 3: Runtime ──────────────────────────────────────────────────────────
# Clean image without build-essential — reduces size (~200 MB) and attack surface.
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/python:3.12-slim-bookworm

ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONIOENCODING=utf-8

# Switch to Alibaba Cloud Debian mirror (mirrors.aliyun.com) to avoid
# flaky / blocked access to the default deb.debian.org host. This stage
# does not inherit the same sed from the builder stage, so the redirection
# must be repeated here.
RUN sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
    sed -i 's|https://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
    sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null || true; \
    sed -i 's|https://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null || true

# libpq5 required by asyncpg + psycopg[binary] (PostgreSQL C client library)
# transitively pulls in: libgssapi-krb5-2, libldap-2.5-0, libssl3
# --fix-missing: tolerate occasional 5xx errors on individual packages
RUN apt-get update && apt-get install -y --no-install-recommends --fix-missing \
    libpq5 \
    # Common CLI / debugging tools (baked in for offline / LAN-restricted runs)
    ca-certificates \
    gnupg \
    git \
    tini \
    jq \
    yq \
    wget \
    curl \
    unzip \
    zip \
    xz-utils \
    p7zip-full \
    less \
    vim-tiny \
    nano \
    tree \
    file \
    xxd \
    procps \
    htop \
    lsof \
    psmisc \
    strace \
    iputils-ping \
    iproute2 \
    dnsutils \
    net-tools \
    traceroute \
    tcpdump \
    && rm -rf /var/lib/apt/lists/*

# Copy Node.js runtime from builder (provides npx for MCP servers)
COPY --from=builder /usr/local/bin/node /usr/local/bin/node
COPY --from=builder /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/bin/npx

# Install Docker CLI (for DooD: allows starting sandbox containers via host Docker socket)
COPY --from=swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/docker:cli /usr/local/bin/docker /usr/local/bin/docker

# ── Install Claude Code CLI (offline bundled) ──────────────────────────────
# 离线环境：把 bundle 脚本产出的整个 npm prefix (bin/ + lib/node_modules/ 全量)
# 一次性解压到 /usr/local。gateway 通过 claude_provider.py (import anthropic) 调
# Anthropic API，claude CLI 仅用于容器内 `claude login` 生成 OAuth 凭据。
# 产物路径：offline-claude/claude-code-bundled-${VERSION}-${PLATFORM}.tar.gz
# 由 scripts/bundle-claude-code.sh 在 Linux x86 runner 上生成。
# 切换到其它平台（如 linux-arm64、alpine/musl）只需改 CLAUDE_CODE_PLATFORM，
# 并把对应 tarball 放到 offline-claude/ 下，无需改 Dockerfile 其它部分。
ARG CLAUDE_CODE_VERSION=2.1.139
ARG CLAUDE_CODE_PLATFORM=linux-x64
COPY offline-claude/claude-code-bundled-${CLAUDE_CODE_VERSION}-${CLAUDE_CODE_PLATFORM}.tar.gz /tmp/claude-bundle.tar.gz
RUN tar -xzf /tmp/claude-bundle.tar.gz -C /usr/local --no-same-owner \
    && rm /tmp/claude-bundle.tar.gz \
    && claude --version

# ── Install Claude Agent ACP (offline bundled) ─────────────────────────────
# 离线环境：把 @agentclientprotocol/claude-agent-acp 整包 vendor 到镜像，
# 这样 acp_agents.claude_code 配的 `npx -y @agentclientprotocol/claude-agent-acp`
ARG CLAUDE_AGENT_ACP_VERSION=0.42.0
COPY offline-claude/claude-agent-acp-bundled-${CLAUDE_AGENT_ACP_VERSION}-linux-x64.tar.gz /tmp/acp-bundle.tar.gz
RUN tar -xzf /tmp/acp-bundle.tar.gz -C /usr/local --no-same-owner \
    && rm /tmp/acp-bundle.tar.gz \
    && test -x /usr/local/bin/claude-agent-acp \
    && node -e "console.log('claude-agent-acp', require('/usr/local/lib/node_modules/@agentclientprotocol/claude-agent-acp/package.json').version)"

# ── Install Pi Coding Agent + pi-acp (offline bundled, opt-in) ─────────────
# pi-acp 在 stdio 通信时 shell out 调 `pi --mode rpc`，所以 acp_agents.pi
# 需要两个 bundle 同时 vendor：
#   1. @earendil-works/pi-coding-agent  (pi 二进制本身)
#   2. pi-acp                           (DeerFlow 调起的 ACP 适配器)
# 启用：uncomment 下面 + 把对应 tarball 放到 offline-claude/。
# 关闭（默认）：保持 commented，不影响镜像构建。
#
# 产物路径：
#   offline-claude/bundle-pi-coding-agent.sh → offline-claude/pi-coding-agent-bundled-${VERSION}-linux-x64.tar.gz
#   offline-claude/bundle-pi-acp.sh   → offline-claude/pi-acp-bundled-${VERSION}-linux-x64.tar.gz
# 两者都在 Linux x86_64 runner 上执行。
# pi-web **不** vendor 进镜像，它是独立 Web UI，与 DeerFlow 无联动。
ARG PI_CODING_AGENT_VERSION=0.78.1
ARG PI_ACP_VERSION=0.0.27
COPY offline-claude/pi-coding-agent-bundled-${PI_CODING_AGENT_VERSION}-linux-x64.tar.gz /tmp/pi-agent-bundle.tar.gz
RUN tar -xzf /tmp/pi-agent-bundle.tar.gz -C /usr/local --no-same-owner \
    && rm /tmp/pi-agent-bundle.tar.gz \
    && pi --version \
    && fd --version \
    && rg --version

COPY offline-claude/pi-acp-bundled-${PI_ACP_VERSION}-linux-x64.tar.gz /tmp/pi-acp-bundle.tar.gz
RUN tar -xzf /tmp/pi-acp-bundle.tar.gz -C /usr/local --no-same-owner \
    && rm /tmp/pi-acp-bundle.tar.gz \
    && test -x /usr/local/bin/pi-acp

# 离线兜底：pi 运行时若发现新 helper 缺失，默认会去 GitHub Releases 拉。
# 强制 PI_OFFLINE=1 让它直接 fail-fast（见 dist/utils/tools-manager.js
# 的 isOfflineModeEnabled()），避免在没网时挂死。
ENV PI_OFFLINE=1

# Shell convenience aliases — visible to `docker exec ... bash` (interactive bash
# sources /root/.bashrc) and login sh/bash sessions (source /etc/profile.d/*.sh).
RUN echo 'alias ll="ls -al"' > /etc/profile.d/ll.sh \
    && echo 'alias ll="ls -al"' >> /root/.bashrc

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
