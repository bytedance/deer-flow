# Frontend Development Dockerfile
FROM node:22-alpine

# Accept build argument for pnpm store path
ARG PNPM_STORE_PATH=/root/.local/share/pnpm/store

# Install pnpm at specific version (matching package.json)
RUN corepack enable && corepack install -g pnpm@10.26.2

RUN pnpm config set store-dir ${PNPM_STORE_PATH}

# Set working directory
WORKDIR /app

# Copy frontend source code
COPY frontend ./frontend

# Install dependencies
RUN sh -c "cd /app/frontend && pnpm install --frozen-lockfile"

# Expose Next.js dev server port
EXPOSE 3000
