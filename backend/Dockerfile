# Backend Development Dockerfile
FROM python:3.12-slim

# Install system dependencies
RUN set -eux; \
    apt-get update -o Acquire::Retries=5; \
    for i in 1 2 3 4 5; do \
      apt-get install -y --no-install-recommends curl build-essential docker-cli && break; \
      if [ "$i" -eq 5 ]; then exit 1; fi; \
      apt-get update -o Acquire::Retries=5; \
      sleep 5; \
    done; \
    rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

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
