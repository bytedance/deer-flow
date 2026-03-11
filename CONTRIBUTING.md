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

#### Docker Architecture

```
Host Machine
  ↓
Docker Compose (deer-flow-dev)
  ├→ nginx (port 2026) ← Reverse proxy
  ├→ web (port 3000) ← Frontend with hot-reload
  ├→ api (port 8001) ← Gateway API with hot-reload
   ├→ langgraph (port 2024) ← LangGraph server with hot-reload
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

2. **Install dependencies**:
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

1. **Start backend services**:
   ```bash
   # Terminal 1: Start LangGraph Server (port 2024)
   cd backend
   make dev

   # Terminal 2: Start Gateway API (port 8001)
   cd backend
   make gateway

   # Terminal 3: Start Frontend (port 3000)
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
- Routes `/api/langgraph/*` to LangGraph Server (2024)
- Routes other `/api/*` endpoints to Gateway API (8001)
- Routes non-API requests to Frontend (3000)
- Centralized CORS handling
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
Nginx (port 2026) ← Unified entry point
  ├→ Frontend (port 3000) ← / (non-API requests)
  ├→ Gateway API (port 8001) ← /api/models, /api/mcp, /api/skills, /api/threads/*/artifacts
  └→ LangGraph Server (port 2024) ← /api/langgraph/* (agent interactions)
```

## Development Workflow

### Git Repository Structure

This project uses a fork-based workflow:
- **Upstream**: `origin` → `git@github.com:bytedance/deer-flow.git` (read-only for most contributors)
- **Your fork**: `fork` → `git@github.com:YOUR_USERNAME/deer-flow.git` (your working copy)

Check your remotes:
```bash
git remote -v
# Should show both 'origin' and 'fork'
```

### Creating a Pull Request

1. **Create a feature branch** with proper naming:
   ```bash
   # Format: <type>/<description-in-kebab-case>
   git checkout -b fix/sqlite-checkpointer-default
   git checkout -b feat/add-memory-system
   git checkout -b docs/update-readme

   # ❌ Avoid: issue numbers, dates, or unclear names
   # git checkout -b 20260309-issue
   # git checkout -b fix/issue-1066-sqlite-checkpointer
   ```

2. **Make your changes** with hot-reload enabled

3. **Test your changes** thoroughly:
   ```bash
   cd backend && make test
   ```

4. **Commit your changes** following conventional commits:
   ```bash
   git add <files>
   git commit -m "fix: default to SqliteSaver for persistent conversation history

   Changes the default checkpointer from InMemorySaver to SqliteSaver when
   no checkpointer is configured in config.yaml.

   Fixes #1066"
   ```

   **Important**:
   - ❌ Never add `Co-Authored-By: Claude` or AI attribution
   - ✅ Use conventional commit types: `fix`, `feat`, `docs`, `refactor`, `test`, `chore`
   - ✅ Reference issue numbers with `Fixes #<number>` or `Closes #<number>`

5. **Push to your fork** (not upstream):
   ```bash
   # ✅ Correct: Push to your fork
   git push fork fix/sqlite-checkpointer-default

   # ❌ Wrong: Pushing to upstream will fail with permission denied
   # git push origin fix/sqlite-checkpointer-default
   ```

6. **Create a Pull Request**:
   ```bash
   # Option 1: Using gh CLI (recommended)
   gh pr create --draft \
     --repo bytedance/deer-flow \
     --head YOUR_USERNAME:fix/sqlite-checkpointer-default \
     --title "fix: default to SqliteSaver for persistent conversation history" \
     --body "Description of your changes"

   # Option 2: Via GitHub web interface
   # Visit: https://github.com/bytedance/deer-flow/compare
   # Select: base: main <- compare: YOUR_USERNAME:fix/sqlite-checkpointer-default
   ```

### Common Pitfalls

#### ❌ Wrong: Pushing to upstream directly
```bash
git push origin my-branch
# Error: Permission to bytedance/deer-flow.git denied
```

#### ✅ Correct: Push to your fork
```bash
git push fork my-branch
```

#### ❌ Wrong: Creating PR without pushing first
```bash
gh pr create --draft
# Error: you must first push the current branch to a remote
```

#### ✅ Correct: Push first, then create PR with --head
```bash
git push fork my-branch
gh pr create --draft --head YOUR_USERNAME:my-branch
```

## Testing

```bash
# Backend tests
cd backend
uv run pytest

# Frontend tests
cd frontend
pnpm test
```

### PR Regression Checks

Every pull request runs the backend regression workflow at [.github/workflows/backend-unit-tests.yml](.github/workflows/backend-unit-tests.yml), including:

- `tests/test_provisioner_kubeconfig.py`
- `tests/test_docker_sandbox_mode_detection.py`

## Code Style

- **Backend (Python)**: We use `ruff` for linting and formatting
- **Frontend (TypeScript)**: We use ESLint and Prettier

## Documentation

- [Configuration Guide](backend/docs/CONFIGURATION.md) - Setup and configuration
- [Architecture Overview](backend/CLAUDE.md) - Technical architecture
- [MCP Setup Guide](MCP_SETUP.md) - Model Context Protocol configuration

## Need Help?

- Check existing [Issues](https://github.com/bytedance/deer-flow/issues)
- Read the [Documentation](backend/docs/)
- Ask questions in [Discussions](https://github.com/bytedance/deer-flow/discussions)

## License

By contributing to DeerFlow, you agree that your contributions will be licensed under the [MIT License](./LICENSE).
