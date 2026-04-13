# Contributing to DeerFlow

Thank you for your interest in contributing to DeerFlow! This guide will help you set up your development environment and understand our development workflow.

## Development Environment Setup

We offer two development environments. **Docker is recommended** for the most consistent and hassle-free experience.

### Option 1: Docker Development (Recommended)

Docker provides a consistent, isolated environment with all dependencies pre-configured. No need to install Node.js or Python on your local machine.

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
   - LangGraph server supports hot-reload

4. **Access the application**:
   - Web Interface: http://localhost:2026
   - API Gateway: http://localhost:2026/api/*
   - LangGraph: http://localhost:2026/api/langgraph/*

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
unable to get image 'deer-flow-dev-langgraph': permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock
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
  ├→ gateway (host port 2026 → container 8001) ← Gateway API + reverse proxy (replaces nginx)
  ├→ frontend (port 3000) ← Frontend with hot-reload (internal only)
  ├→ langgraph (port 2024) ← LangGraph server with hot-reload (internal only)
  └→ provisioner (optional, port 8002) ← Started only in provisioner/K8s sandbox mode
```

**Benefits of Docker Development**:
- ✅ Consistent environment across different machines
- ✅ No need to install Node.js or Python locally
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

#### Setup Steps

1. **Configure the application** (same as Docker setup above)

2. **Install dependencies**:
   ```bash
   make install
   ```

3. **Run development server** (starts LangGraph + Frontend + Gateway):
   ```bash
   make dev
   ```

4. **Access the application**:
   - Web Interface: http://localhost:2026
   - All API requests are served by — and proxied through — the gateway

#### Manual Service Control

If you need to start services individually:

1. **Start backend services**:
   ```bash
   # Terminal 1: Start LangGraph Server (port 2024)
   cd backend
   make dev

   # Terminal 2: Start Gateway API (port 8001 by default; bypasses the
   # supervised mode that binds it to 2026)
   cd backend
   make gateway

   # Terminal 3: Start Frontend (port 3000)
   cd frontend
   pnpm dev
   ```

2. **Access the application**:
   - Frontend (direct):     http://localhost:3000
   - Gateway API (direct):  http://localhost:8001/api/...
   - LangGraph (direct):    http://localhost:2024

   In this mode there is no unified entry point on 2026 because each service
   is reachable on its own port. Use `make dev` from the repo root to get the
   gateway-as-proxy entry point on http://localhost:2026.

#### Gateway Reverse-Proxy Configuration

The gateway's `proxy` router (`backend/app/gateway/routers/proxy.py`) provides:
- Unified entry point on port 2026
- Routes `/api/langgraph/*` to LangGraph Server (2024)
- Serves other `/api/*` endpoints natively via FastAPI routers
- Routes non-API requests to Frontend (3000)
- Centralized CORS handling via `fastapi.middleware.cors.CORSMiddleware`
- SSE/streaming support via `httpx.AsyncClient.stream()` + `StreamingResponse`
- 600s timeouts for long-running operations
- WebSocket forwarding for Next.js HMR

## Project Structure

```
deer-flow/
├── config.example.yaml      # Configuration template
├── extensions_config.example.json  # MCP and Skills configuration template
├── Makefile                 # Build and development commands
├── scripts/
│   └── docker.sh           # Docker management script
├── docker/
│   └── docker-compose-dev.yaml  # Docker Compose configuration
├── backend/                 # Backend application
│   ├── src/
│   │   ├── gateway/        # Gateway API (port 8001)
│   │   ├── agents/         # LangGraph agents (port 2024)
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
Gateway API (port 2026) ← Unified entry point + REST API + reverse proxy
  ├→ FastAPI routers (in-process) ← /api/models, /api/mcp, /api/skills, /api/threads/*/artifacts
  ├→ Frontend (port 3000)        ← /  (non-API requests, via httpx)
  └→ LangGraph Server (port 2024) ← /api/langgraph/* (via httpx, with SSE streaming)
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

# Frontend tests
cd frontend
make test
```

### PR Regression Checks

Every pull request triggers the following CI workflows:

- **Backend unit tests** — [.github/workflows/backend-unit-tests.yml](.github/workflows/backend-unit-tests.yml)
- **Frontend unit tests** — [.github/workflows/frontend-unit-tests.yml](.github/workflows/frontend-unit-tests.yml)

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
