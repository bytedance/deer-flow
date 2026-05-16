# Contributing to DeerFlow

Thank you for your interest in contributing to DeerFlow! This guide will help you set up your development environment and understand our development workflow.

## Development Environment Setup

We offer two development environments. **Docker is recommended** for the most consistent and hassle-free experience.

### Option 1: Docker Development (Recommended)

Docker provides a consistent, isolated environment with all dependencies pre-configured. No need to install Node.js, Python, or nginx on your local machine.

#### Prerequisites

- Docker Desktop or Docker Engine
- pnpm (for caching optimization)

#### Setup Steps

1. **Configure the application**:
   ```bash
   # Copy example configuration
   cp config.example.yaml config.yaml

   # Set your API keys
   export OPENAI_API_KEY="your-key-here"
   # or edit config.yaml directly
   ```

2. **Initialize Docker environment** (first time only):
   ```bash
   make docker-init
   ```
   This will:
   - Build Docker images
   - Install frontend dependencies (pnpm)
   - Install backend dependencies (uv)
   - Share pnpm cache with host for faster builds

3. **Start development services**:
   ```bash
   make docker-start
   ```
   `make docker-start` reads `config.yaml` and starts `provisioner` only for provisioner/Kubernetes sandbox mode.

   All services will start with hot-reload enabled:
   - Frontend changes are automatically reloaded
   - Backend changes trigger automatic restart
   - Gateway-hosted LangGraph-compatible runtime supports hot-reload

4. **Access the application**:
   - Web Interface: http://localhost:2026
   - API Gateway: http://localhost:2026/api/*
   - LangGraph-compatible API: http://localhost:2026/api/langgraph/*

#### Docker Commands

```bash
# Build the custom k3s image (with pre-cached sandbox image)
make docker-init
# Start Docker services (mode-aware, localhost:2026)
make docker-start
# Stop Docker development services
make docker-stop
# View Docker development logs
make docker-logs
# View Docker frontend logs
make docker-logs-frontend
# View Docker gateway logs
make docker-logs-gateway
```

If Docker builds are slow in your network, you can override the default package registries before running `make docker-init` or `make docker-start`:

```bash
export UV_INDEX_URL=https://pypi.org/simple
export NPM_REGISTRY=https://registry.npmjs.org
```

#### Recommended host resources

Use these as practical starting points for development and review environments:

| Scenario | Starting point | Recommended | Notes |
|---------|-----------|------------|-------|
| `make dev` on one machine | 4 vCPU, 8 GB RAM | 8 vCPU, 16 GB RAM | Best when DeerFlow uses hosted model APIs. |
| `make docker-start` review environment | 4 vCPU, 8 GB RAM | 8 vCPU, 16 GB RAM | Docker image builds and sandbox containers need extra headroom. |
| Shared Linux test server | 8 vCPU, 16 GB RAM | 16 vCPU, 32 GB RAM | Prefer this for heavier multi-agent runs or multiple reviewers. |

`2 vCPU / 4 GB` environments often fail to start reliably or become unresponsive under normal DeerFlow workloads.

#### Linux: Docker daemon permission denied

If `make docker-init`, `make docker-start`, or `make docker-stop` fails on Linux with an error like below, your current user likely does not have permission to access the Docker daemon socket:

```text
unable to get image 'deer-flow-gateway': permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock
```

Recommended fix: add your current user to the `docker` group so Docker commands work without `sudo`.

1. Confirm the `docker` group exists:
   ```bash
   getent group docker
   ```
2. Add your current user to the `docker` group:
   ```bash
   sudo usermod -aG docker $USER
   ```
3. Apply the new group membership. The most reliable option is to log out completely and then log back in. If you want to refresh the current shell session instead, run:
   ```bash
   newgrp docker
   ```
4. Verify Docker access:
   ```bash
   docker ps
   ```
5. Retry the DeerFlow command:
   ```bash
   make docker-stop
   make docker-start
   ```

If `docker ps` still reports a permission error after `usermod`, fully log out and log back in before retrying.

#### Docker Architecture

```
Host Machine
  ↓
Docker Compose (deer-flow-dev)
  ├→ nginx (port 2026) ← Reverse proxy
  ├→ web (port 3000) ← Frontend with hot-reload
  ├→ gateway (port 8001) ← Gateway API + LangGraph-compatible runtime with hot-reload
  └→ provisioner (optional, port 8002) ← Started only in provisioner/K8s sandbox mode
```

**Benefits of Docker Development**:
- ✅ Consistent environment across different machines
- ✅ No need to install Node.js, Python, or nginx locally
- ✅ Isolated dependencies and services
- ✅ Easy cleanup and reset
- ✅ Hot-reload for all services
- ✅ Production-like environment

### Option 2: Local Development

If you prefer to run services directly on your machine:

#### Prerequisites

Check that you have all required tools installed:

```bash
make check
```

Required tools:
- Node.js 22+
- pnpm
- uv (Python package manager)
- nginx

#### Setup Steps

1. **Configure the application** (same as Docker setup above)

2. **Install dependencies** (this also sets up pre-commit hooks):
   ```bash
   make install
   ```

3. **Run development server** (starts all services with nginx):
   ```bash
   make dev
   ```

4. **Access the application**:
   - Web Interface: http://localhost:2026
   - All API requests are automatically proxied through nginx

#### Manual Service Control

If you need to start services individually:

1. **Start backend service**:
   ```bash
   # Terminal 1: Start Gateway API + embedded agent runtime (port 8001)
   cd backend
   make dev

   # Terminal 2: Start Frontend (port 3000)
   cd frontend
   pnpm dev
   ```

2. **Start nginx**:
   ```bash
   make nginx
   # or directly: nginx -c $(pwd)/docker/nginx/nginx.local.conf -g 'daemon off;'
   ```

3. **Access the application**:
   - Web Interface: http://localhost:2026

#### Nginx Configuration

The nginx configuration provides:
- Unified entry point on port 2026
- Rewrites `/api/langgraph/*` to Gateway's LangGraph-compatible API (8001)
- Routes other `/api/*` endpoints to Gateway API (8001)
- Routes non-API requests to Frontend (3000)
- Same-origin API routing; split-origin or port-forwarded browser clients should use the Gateway `GATEWAY_CORS_ORIGINS` allowlist
- SSE/streaming support for real-time agent responses
- Optimized timeouts for long-running operations

## Project Structure

```
deer-flow/
├── config.example.yaml      # Configuration template
├── extensions_config.example.json  # MCP and Skills configuration template
├── Makefile                 # Build and development commands
├── scripts/
│   └── docker.sh           # Docker management script
├── docker/
│   ├── docker-compose-dev.yaml  # Docker Compose configuration
│   └── nginx/
│       ├── nginx.conf      # Nginx config for Docker
│       └── nginx.local.conf # Nginx config for local dev
├── backend/                 # Backend application
│   ├── src/
│   │   ├── gateway/        # Gateway API and LangGraph-compatible runtime (port 8001)
│   │   ├── agents/         # LangGraph agent runtime used by Gateway
│   │   ├── mcp/            # Model Context Protocol integration
│   │   ├── skills/         # Skills system
│   │   └── sandbox/        # Sandbox execution
│   ├── docs/               # Backend documentation
│   └── Makefile            # Backend commands
├── frontend/               # Frontend application
│   └── Makefile            # Frontend commands
└── skills/                 # Agent skills
    ├── public/             # Public skills
    └── custom/             # Custom skills
```

## Architecture

```
Browser
  ↓
Nginx (port 2026) ← Unified entry point
  ├→ Frontend (port 3000) ← / (non-API requests)
  └→ Gateway API (port 8001) ← /api/* and /api/langgraph/* (LangGraph-compatible agent interactions)
```

## Development Workflow

1. **Create a feature branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** with hot-reload enabled

3. **Format and lint your code** (CI will reject unformatted code):
   ```bash
   # Backend
   cd backend
   make format   # ruff check --fix + ruff format

   # Frontend
   cd frontend
   pnpm format:write   # Prettier
   ```

4. **Test your changes** thoroughly

5. **Commit your changes**:
   ```bash
   git add .
   git commit -m "feat: description of your changes"
   ```

6. **Push and create a Pull Request**:
   ```bash
   git push origin feature/your-feature-name
   ```

## Testing

```bash
# Backend tests
cd backend
make test

# Frontend unit tests
cd frontend
make test

# Frontend E2E tests (requires Chromium; builds and auto-starts the Next.js production server)
cd frontend
make test-e2e
```

### PR Regression Checks

Every pull request triggers the following CI workflows:

- **Backend unit tests** — [.github/workflows/backend-unit-tests.yml](.github/workflows/backend-unit-tests.yml)
- **Frontend unit tests** — [.github/workflows/frontend-unit-tests.yml](.github/workflows/frontend-unit-tests.yml)
- **Frontend E2E tests** — [.github/workflows/e2e-tests.yml](.github/workflows/e2e-tests.yml) (triggered only when `frontend/` files change)

## Code Style

- **Backend (Python)**: We use `ruff` for linting and formatting. Run `make format` before committing.
- **Frontend (TypeScript)**: We use ESLint and Prettier. Run `pnpm format:write` before committing.
- CI enforces formatting — PRs with unformatted code will fail the lint check.

## Documentation

- [Configuration Guide](backend/docs/CONFIGURATION.md) - Setup and configuration
- [Architecture Overview](backend/CLAUDE.md) - Technical architecture
- [MCP Setup Guide](backend/docs/MCP_SERVER.md) - Model Context Protocol configuration

## Need Help?

- Check existing [Issues](https://github.com/bytedance/deer-flow/issues)
- Read the [Documentation](backend/docs/)
- Ask questions in [Discussions](https://github.com/bytedance/deer-flow/discussions)

## License

By contributing to DeerFlow, you agree that your contributions will be licensed under the [MIT License](./LICENSE).
