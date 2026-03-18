# 🦌 DeerFlow — Local Development Guide (Windows)

> **Who is this for?** Windows developers who want to run, test, and iterate on DeerFlow locally — covering every software you need to install, why you need it, and how to get from zero to a running full-stack environment as fast as possible.

---

## Table of Contents

1. [Architecture at a Glance](#1-architecture-at-a-glance)
2. [Prerequisites — Install Once](#2-prerequisites--install-once)
   - [Git](#21-git)
   - [Python 3.12 via uv](#22-python-312-via-uv)
   - [Node.js 22+](#23-nodejs-22)
   - [pnpm](#24-pnpm)
   - [Nginx for Windows](#25-nginx-for-windows)
   - [(Optional) Docker Desktop](#26-optional-docker-desktop)
3. [Clone the Repository](#3-clone-the-repository)
4. [First-Time Configuration](#4-first-time-configuration)
   - [Generate config files](#41-generate-config-files)
   - [Configure an LLM model](#42-configure-an-llm-model)
   - [Set API keys](#43-set-api-keys)
5. [Install All Dependencies](#5-install-all-dependencies)
6. [Running the Full Stack Locally (Fast Dev Mode)](#6-running-the-full-stack-locally-fast-dev-mode)
   - [Option A — One command (all services)](#option-a--one-command-all-services-easiest)
   - [Option B — Services in separate terminals (recommended for development)](#option-b--services-in-separate-terminals-recommended-for-development)
7. [Development Workflows](#7-development-workflows)
   - [Frontend-only changes](#71-frontend-only-changes)
   - [Backend-only changes](#72-backend-only-changes-langgraph-agent)
   - [Gateway API changes](#73-gateway-api-changes)
   - [Running backend tests](#74-running-backend-tests)
   - [Linting and formatting](#75-linting-and-formatting)
8. [Understanding the Service Ports](#8-understanding-the-service-ports)
9. [Key Config Files](#9-key-config-files)
10. [Windows-Specific Notes & Troubleshooting](#10-windows-specific-notes--troubleshooting)

---

## 1. Architecture at a Glance

```
Browser → http://localhost:2026
               │
          [Nginx :2026]  ← reverse proxy / unified entry point
          /           \
   /api/langgraph/*   /api/*            / (everything else)
         │                │                     │
  LangGraph :2024    Gateway API :8001     Next.js :3000
  (AI agent engine)  (REST: models,        (UI / frontend)
                      skills, memory,
                      uploads, etc.)
```

| Service | Port | What it does |
|---|---|---|
| **Nginx** | `2026` | Unified entry point — routes requests to the right service |
| **LangGraph Server** | `2024` | Runs the AI lead agent, manages threads, streams results |
| **Gateway API** | `8001` | FastAPI endpoints for models, skills, memory, file uploads |
| **Frontend (Next.js)** | `3000` | React web UI |

You only ever open `http://localhost:2026` in your browser; Nginx handles the routing.

---

## 2. Prerequisites — Install Once

### 2.1 Git

**Why:** Required to clone the repository and manage source code.

Download and install from [git-scm.com/download/win](https://git-scm.com/download/win).  
Accept all default options during installation.

Verify in a new PowerShell or CMD window:
```powershell
git --version
```

---

### 2.2 Python 3.12 via `uv`

**Why:** The backend is written in Python 3.12 and uses [`uv`](https://docs.astral.sh/uv/) as its package/environment manager (replaces pip + virtualenv). `uv` is extremely fast and handles the Python version automatically.

**Install `uv`** (this also installs the correct Python version for you):
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Restart your terminal, then verify:
```powershell
uv --version
```

> `uv` will automatically download Python 3.12 the first time you run `uv sync` inside the project, because the `backend/.python-version` file pins it to `3.12`. You do **not** need to install Python separately.

---

### 2.3 Node.js 22+

**Why:** The frontend is a Next.js application. Node.js is its runtime. Node 22 is required (as enforced by `make check`).

Download the **LTS (v22.x)** installer from [nodejs.org](https://nodejs.org/en/download).  
Run the `.msi` installer and accept defaults.

Verify:
```powershell
node -v   # Should show v22.x.x or higher
```

---

### 2.4 pnpm

**Why:** The frontend uses `pnpm` (not npm or yarn) as its package manager. It is faster and uses a shared content-addressable cache to save disk space.

Install after Node.js is set up:
```powershell
npm install -g pnpm
```

Verify:
```powershell
pnpm -v
```

---

### 2.5 Nginx for Windows

**Why:** Nginx acts as the reverse proxy that glues all three backend services (LangGraph, Gateway, Frontend) behind a single port (`2026`). Without it, you'd need to hit three different ports manually, and CORS would break.

**Install steps:**

1. Download the stable Windows ZIP from [nginx.org/en/download.html](https://nginx.org/en/download.html) (e.g., `nginx-1.xx.x.zip`).
2. Extract it to a simple path like `C:\nginx\`.
3. Add `C:\nginx\` to your **system PATH**:
   - Open **Start → Search "Environment Variables"**
   - Click **"Edit the system environment variables"** → **Environment Variables**
   - Under **System variables**, select `Path` → **Edit** → **New** → add `C:\nginx\`
   - Click OK on all dialogs
4. Open a **new** PowerShell and verify:
   ```powershell
   nginx -v
   ```

> **Note:** The `make dev` command (from project root) starts nginx automatically using the config at `docker/nginx/nginx.local.conf`. You do not need to start it manually.

---

### 2.6 (Optional) Docker Desktop

**Why:** Only needed if you want to use the container-based (Docker) sandbox mode, which gives the AI agent a fully isolated execution environment. For basic local development and testing, the simpler **local sandbox** (direct execution on your machine) is sufficient.

Download from [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/).  
After install, ensure Docker Desktop is running before using any Docker-related commands.

---

## 3. Clone the Repository

Open PowerShell and run:

```powershell
git clone https://github.com/bytedance/deer-flow.git
cd deer-flow
```

All subsequent commands are run from this `deer-flow/` root directory unless stated otherwise.

---

## 4. First-Time Configuration

### 4.1 Generate config files

**Why:** The project ships with example config templates. You run this once to create your own local copies that won't be accidentally committed to Git.

```powershell
python .\scripts\configure.py
```

This creates:
- `config.yaml` (copied from `config.example.yaml`) — main app config
- `.env` (copied from `.env.example`) — API keys
- `frontend/.env` (copied from `frontend/.env.example`) — frontend environment variables

Then manually copy the MCP/skills config:
```powershell
Copy-Item extensions_config.example.json extensions_config.json
```

This creates `extensions_config.json` — controls which MCP servers and skills are enabled. The script does not generate this file automatically.

---

### 4.2 Configure an LLM model

**Why:** DeerFlow is model-agnostic but needs at least one LLM configured to work. Open `config.yaml` and uncomment one of the model examples.

The simplest example using **OpenAI GPT-4**:

```yaml
models:
  - name: gpt-4
    display_name: GPT-4
    use: langchain_openai:ChatOpenAI
    model: gpt-4
    api_key: $OPENAI_API_KEY
    max_tokens: 4096
    temperature: 0.7
    supports_vision: true
```

> For other providers (Anthropic, Google Gemini, DeepSeek, OpenRouter, etc.), see the commented examples already in `config.yaml`.

---

### 4.3 Set API keys

**Why:** The LLM and web-search tools need API keys to authenticate with external services.

Open the `.env` file in the project root and fill in your keys:

```env
# Required: at minimum one LLM provider key
OPENAI_API_KEY=sk-...

# Required for web search (free tier available at tavily.com)
TAVILY_API_KEY=tvly-...

# Optional web fetch
JINA_API_KEY=jina_...
```

> All keys prefixed with `$` in `config.yaml` are automatically read from this `.env` file at startup.

---

## 5. Install All Dependencies

**Why:** This installs all Python packages (backend) and all Node.js packages (frontend) into local environments.

```powershell
# Install backend Python dependencies via uv
cd backend
uv sync
cd ..

# Install frontend Node.js dependencies via pnpm
cd frontend
pnpm install
cd ..
```

Or equivalently (from the project root, if `make` is available in WSL or Git Bash):
```bash
make install
```

> `uv sync` reads `backend/pyproject.toml` and `backend/uv.lock`, creating a `.venv` inside `backend/`. `pnpm install` reads `frontend/package.json`.

---

## 6. Running the Full Stack Locally (Fast Dev Mode)

### Option A — One command (all services, easiest)

If you have `make` available (via Git Bash or WSL):
```bash
make dev
```

This starts all four services (LangGraph server, Gateway API, Next.js, Nginx) in one go with hot-reload for all of them.

**On native PowerShell** (without make), use Option B below.

---

### Option B — Services in separate terminals (recommended for development)

Open **4 separate PowerShell terminals**, all from the project root directory:

#### Terminal 1 — LangGraph Agent Server (port 2024)

```powershell
cd backend
uv run langgraph dev --no-browser --allow-blocking --no-reload
```

**Why:** This is the AI agent engine. It runs the `lead_agent` LangGraph workflow that processes chat messages and streams results. Changes here require manual restart.

---

#### Terminal 2 — Gateway API (port 8001)

```powershell
cd backend
$env:PYTHONPATH = "."
uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001 --reload
```

**Why:** This is the FastAPI REST server that handles models listing, skill management, memory, file uploads, and more. The `--reload` flag gives hot-reload on file changes — great for iterating on API endpoints quickly.

---

#### Terminal 3 — Frontend (port 3000)

```powershell
cd frontend
pnpm dev
```

**Why:** This starts the Next.js frontend with Turbopack (`--turbo` flag is set in `package.json`), which gives extremely fast hot-module replacement. Any `.tsx`/`.ts` file change is reflected in the browser in under 1 second.

---

#### Terminal 4 — Nginx Reverse Proxy (port 2026)

Before starting nginx for the first time, create the directories it needs:
```powershell
New-Item -ItemType Directory -Force -Path "logs", "temp\client_body_temp", "temp\proxy_temp", "temp\fastcgi_temp", "temp\uwsgi_temp", "temp\scgi_temp"
```

Then start nginx:
```powershell
nginx -c "$PWD\docker\nginx\nginx.local.conf" -p "$PWD"
```

**Why:** Nginx glues all services together. Without it, the frontend's API calls would fail due to cross-origin issues. It also provides SSE (streaming) support for real-time agent responses.

> **⚠️ The terminal will appear "frozen" with no output after running this command — that is correct.** Nginx runs as a foreground process and keeps the terminal occupied while it is alive. Leave this terminal open and open a new one for other commands.

> **Access the app at:** [http://localhost:2026](http://localhost:2026)

To stop Nginx cleanly, open a **new** terminal in the project root and run:
```powershell
nginx -c "$PWD\docker\nginx\nginx.local.conf" -p "$PWD" -s quit
```

Or press **Ctrl+C** in the nginx terminal (less graceful but works).

---

## 7. Development Workflows

### 7.1 Frontend-only changes

**Files to edit:** `frontend/src/`

The Next.js dev server (`pnpm dev`) watches all files under `frontend/src/`. Any `.tsx`, `.ts`, or `.css` change hot-reloads the browser automatically. **No restart needed.**

Key directories:
| Path | Purpose |
|---|---|
| `frontend/src/app/` | Next.js pages (App Router) |
| `frontend/src/components/` | React components |
| `frontend/src/core/api/` | API client — where backend calls are made |
| `frontend/src/core/threads/` | Thread state management |

---

### 7.2 Backend-only changes (LangGraph agent)

**Files to edit:** `backend/packages/harness/deerflow/`

The LangGraph server does **not** auto-reload (it's started with `--no-reload`). After editing agent code, restart Terminal 1:

```powershell
# In Terminal 1 (Ctrl+C first, then):
uv run langgraph dev --no-browser --allow-blocking --no-reload
```

Key directories:
| Path | Purpose |
|---|---|
| `backend/packages/harness/deerflow/agents/lead_agent/` | Main agent logic |
| `backend/packages/harness/deerflow/agents/middlewares/` | 10 middleware components (titles, memory, sandbox, etc.) |
| `backend/packages/harness/deerflow/tools/` | Tool loading system |
| `backend/packages/harness/deerflow/sandbox/` | Sandbox execution |
| `backend/packages/harness/deerflow/models/` | LLM model factory |
| `backend/packages/harness/deerflow/skills/` | Skills discovery and loading |

> **Tip:** Use the LangGraph Studio UI at `http://localhost:2024` to visualize agent runs and inspect state step-by-step during debugging.

---

### 7.3 Gateway API changes

**Files to edit:** `backend/app/gateway/`

The Gateway is started with `--reload` in Terminal 2, so **file changes are picked up automatically**. No restart needed for most changes.

Key directories:
| Path | Purpose |
|---|---|
| `backend/app/gateway/app.py` | FastAPI application entry point |
| `backend/app/gateway/routers/` | 6 route modules (models, mcp, skills, memory, uploads, artifacts) |
| `backend/app/channels/` | IM platform integrations (Slack, Telegram, Feishu) |

Test an endpoint quickly with curl:
```powershell
curl http://localhost:8001/health
curl http://localhost:8001/api/models
```

---

### 7.4 Running backend tests

**Why:** The project enforces Test-Driven Development. Run tests frequently as you develop.

```powershell
cd backend

# Run all tests
$env:PYTHONPATH = "."
uv run pytest tests/ -v

# Run a specific test file
$env:PYTHONPATH = "."
uv run pytest tests/test_client.py -v

# Run a specific test function
$env:PYTHONPATH = "."
uv run pytest tests/test_client.py::TestGatewayConformance -v
```

Important test files:
| File | What it covers |
|---|---|
| `tests/test_client.py` | Unit + Gateway conformance tests for embedded client |
| `tests/test_harness_boundary.py` | Enforces that harness never imports from `app.*` |
| `tests/test_docker_sandbox_mode_detection.py` | Docker sandbox config detection |
| `tests/test_provisioner_kubeconfig.py` | Provisioner kubeconfig handling |

---

### 7.5 Linting and formatting

```powershell
# From backend/ directory:

# Check lint errors
uv run -- uvx ruff check .

# Auto-fix lint + format
uv run -- uvx ruff check . --fix
uv run -- uvx ruff format .
```

```powershell
# From frontend/ directory:
pnpm lint
pnpm lint:fix
```

---

## 8. Understanding the Service Ports

| URL | What you get |
|---|---|
| `http://localhost:2026` | **Main entry point** — use this in the browser |
| `http://localhost:2026/api/models` | Gateway: list configured LLM models |
| `http://localhost:2026/api/skills` | Gateway: list loaded skills |
| `http://localhost:2026/api/memory` | Gateway: view agent memory |
| `http://localhost:2026/api/langgraph/` | LangGraph API (proxied) |
| `http://localhost:2024` | LangGraph Server (direct, includes Studio UI) |
| `http://localhost:8001/health` | Gateway API health check (direct) |
| `http://localhost:3000` | Next.js frontend (direct, bypasses nginx) |

---

## 9. Key Config Files

| File | Purpose | Edit when… |
|---|---|---|
| `config.yaml` | Main app config: LLM models, tools, sandbox, memory | Adding a new model, changing sandbox mode, tuning memory |
| `.env` | API keys for LLMs and search tools | Adding/changing API keys |
| `extensions_config.json` | MCP servers and skills enable/disable state | Adding MCP tools or toggling skills |
| `backend/langgraph.json` | LangGraph server entrypoint config | Registering new agents |
| `docker/nginx/nginx.local.conf` | Nginx routing rules for local dev | Adding new routes or services |

---

## 10. Windows-Specific Notes & Troubleshooting

### `make` command not found

`make` is a Linux/macOS tool. On Windows, use one of:
- **Git Bash** (included with Git for Windows) — supports `make` if you install it via `pacman -S make` inside Git Bash
- **Chocolatey:** `choco install make`
- **WSL (Windows Subsystem for Linux):** Run everything under WSL Ubuntu for the closest Linux experience

Alternatively, just run each service manually in separate PowerShell terminals as shown in [Option B](#option-b--services-in-separate-terminals-recommended-for-development).

---

### Nginx path issues on Windows

The `nginx.local.conf` uses Unix-style paths internally. If nginx fails to start, try running it from within **Git Bash** instead of PowerShell:

```bash
nginx -c "$(pwd)/docker/nginx/nginx.local.conf" -p "$(pwd)"
```

---

### `PYTHONPATH` in PowerShell

When running `pytest` or `uvicorn` directly, set `PYTHONPATH` for the current session:
```powershell
$env:PYTHONPATH = "."
```

---

### Port already in use

If a service fails to start because its port is occupied:
```powershell
# Find what's using port 2024 (any port)
netstat -ano | findstr :2024

# Kill by PID
taskkill /PID <PID> /F
```

---

### uv not found after installation

Close and reopen your terminal, or manually add uv to the PATH:
```powershell
$env:PATH += ";$env:USERPROFILE\.local\bin"
```

Add the same line to your PowerShell profile (`$PROFILE`) to make it permanent.

---

### Config version warning on startup

If you see a warning like `config_version mismatch`, run:
```bash
# In Git Bash or WSL
make config-upgrade
```
Or manually copy new fields from `config.example.yaml` to your `config.yaml`.

---

*Happy hacking! 🦌 When in doubt, check `backend/CLAUDE.md` for deep architecture notes and `CONTRIBUTING.md` for workflow guidelines.*
