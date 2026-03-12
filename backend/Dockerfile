# Backend Development Dockerfile
FROM python:3.12-slim

ARG NODE_MAJOR=22

# Install system dependencies + Node.js (provides npx for MCP servers)
RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    gnupg \
    ca-certificates \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Docker CLI (for DooD: allows starting sandbox containers via host Docker socket)
COPY --from=docker:cli /usr/local/bin/docker /usr/local/bin/docker

# Install uv from a pinned versioned image (avoids curl|sh from untrusted remote)
COPY --from=ghcr.io/astral-sh/uv:0.7.20 /uv /uvx /usr/local/bin/

# Set working directory
WORKDIR /app

# Copy frontend source code
COPY backend ./backend

# Install dependencies with cache mount
RUN --mount=type=cache,target=/root/.cache/uv \
    sh -c "cd backend && uv sync"

# Expose ports (gateway: 8001, langgraph: 2024)
EXPOSE 8001 2024

# Default command (can be overridden in docker-compose)
CMD ["sh", "-c", "uv run uvicorn src.gateway.app:app --host 0.0.0.0 --port 8001"]
