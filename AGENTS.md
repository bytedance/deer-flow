# AGENTS.md

Guidance source; `CLAUDE.md` imports `@AGENTS.md`.
Module guides:

- **[backend/AGENTS.md](backend/AGENTS.md)** — backend depth: harness/app split, agent &
  middleware chain, sandbox, MCP, skills, memory, IM channels, persistence/migrations,
  config system, test layout.
- **[frontend/AGENTS.md](frontend/AGENTS.md)** — frontend depth: Next.js App Router layout,
  thread/streaming data flow, code style, commands.

Subsystem rules live in the `AGENTS.md` nearest to the code. Before you edit a
directory, read every `AGENTS.md` from that directory up to the repo root; not every
coding agent loads the nested ones automatically. Root-level scopes:
[docker/](docker/AGENTS.md) (nginx, Compose, provisioner, production start),
[skills/](skills/AGENTS.md) (skill review, skill tests, text encoding),
[scripts/](scripts/AGENTS.md) (orchestration scripts, `scripts/pnpm.py`),
`examples/*/AGENTS.md` (extension examples).

## What is DeerFlow

DeerFlow combines LangGraph and Next.js with thread-isolated sandbox execution,
memory, subagents and extensible tools. IM channels connect through the Gateway.

## Service Topology

A single `make dev` / Docker stack runs four cooperating services:

| Service | Port | Role |
| --- | --- | --- |
| **Nginx** | `2026` | Unified reverse-proxy entry point — open this in the browser |
| **Gateway API** | `8001` | FastAPI REST API + embedded LangGraph-compatible agent runtime |
| **Frontend** | `3000` | Next.js web interface |
| **Provisioner** | `8002` | Optional — only when sandbox is configured for provisioner/K8s mode |

Nginx serves the frontend and proxies `/api/*` to Gateway, rewriting
`/api/langgraph/*` to native routes. See [backend/AGENTS.md](backend/AGENTS.md).
It compresses HTML and configured text assets. SSE, fonts, images, audio, and
video stay uncompressed. Route order, bind addresses and provisioner volumes:
[docker/AGENTS.md](docker/AGENTS.md).

## Repository Map

```
deer-flow/
├── Makefile  # Root orchestration: drives the full stack (dev/start/stop, docker, setup)
├── config.example.yaml  # Template → copy to config.yaml (gitignored) at repo root
├── extensions_config.example.json  # Template → copy to extensions_config.json (gitignored): MCP servers + skills
├── backend/  # Python backend — see backend/AGENTS.md
│   ├── Makefile  # Per-module backend commands (dev, gateway, test, lint, migrate-rev)
│   ├── extensions/sources/  # Deployable snapshots of locally installed Python extensions
│   ├── packages/extension-api/  # deerflow-extension-api package (import: deerflow_extension_api.*) — public extension contract
│   ├── packages/harness/  # deerflow-harness package (import: deerflow.*) — agent framework
│   └── app/  # FastAPI Gateway + IM channels (import: app.*)
├── frontend/  # Next.js frontend (pnpm) — see frontend/AGENTS.md
├── docker/  # docker-compose files, nginx config, provisioner
├── skills/  # Agent skills: public/ (committed), custom/ (gitignored)
│  # Managed integration skill packs are global at .deer-flow/integrations/skills/{provider}/
│  # Integration credentials and enabled state remain per-user
├── contracts/  # Cross-component JSON contracts (e.g. subagent status, skill review)
├── examples/  # Extension examples: deerflow-extension-{example,bookmarks,agent-teams}
├── scripts/  # Root orchestration scripts invoked by the Makefile (check, configure, doctor, support_bundle, serve, nginx, docker, deploy, setup_wizard)
├── tests/  # Root-level tests (currently tests/skills/ — public skill tests)
└── docs/  # Cross-cutting docs, plans, and design notes
```

Third-party extensions load from operator-controlled `config.yaml -> plugins:`.
This imports code, so the list stays outside API-writable `extensions_config.json`.
Extensions contribute middleware, lifecycle observers, Gateway services, FastAPI
routers, and experimental full-stack plugins. Use
`deerflow extensions install/upgrade/list/enable/disable/remove` or root
`make extension-*` wrappers. Restart Gateway after every mutation. Build hooks
and extension code run with Gateway privileges; use only trusted operator sources.
Transactions, accepted source forms, locking, and contribution contracts:
[extensions guide](backend/packages/harness/deerflow/extensions/AGENTS.md).
User manual: `frontend/src/content/{en,zh}/harness/extensions/`.

**Extension-first evaluation** — before implementing a feature by editing core code,
evaluate whether it can ship as a packaged extension through the contribution points
above. Stay in core for bug fixes and for changes to the agent loop, memory, context
compaction, or authentication. If existing hooks cannot express the feature, add a
generic hook to the extension contract plus an extension that uses it — do not
hard-code business logic into core. Working examples:
`examples/deerflow-extension-{example,bookmarks,agent-teams}`.
[Workflow guide](examples/deerflow-extension-workflows/AGENTS.md): public
AgentRuns; POSIX, one process/store; approval and session-authorized recovery; uncertain admissions need reconciliation;
no multi-Gateway failover or hard currency budget.

Knowledge management/space policy: `examples/deerflow-extension-knowledge-{management,platform}/`
(scoped `AGENTS.md`, `CONTRACT.md`). Use existing plugin/router/principal contracts;
retrieval stays independent. Space policy intersects administrator/resource/operation
and upstream grants, never grants chat access. SQLite holds plugin-owned space policy.
Provider stages are not completion evidence; reconcile uncertain writes, never retry.

Root runtime configs: copy `config.example.yaml` → `config.yaml` and
`extensions_config.example.json` → `extensions_config.json` (MCP/skills).
Both are gitignored and Gateway-editable; schema/resolution:
[backend/AGENTS.md](backend/AGENTS.md).

## Commands: Root vs. Module

**Root stack commands** (from repo root):

```bash
make setup       # Interactive setup wizard (recommended for new users)
make doctor      # Check configuration and system requirements
make support-bundle  # Generate redacted troubleshooting summary, AI issue draft, and optional zip
make config      # Generate local config files from the examples
make check       # Check that required tools are installed
make install     # Install all dependencies (frontend + backend + pre-commit hooks)
make extension-install SOURCE=...  # Install and enable a trusted Python extension
make extension-upgrade SOURCE=...  # Replace an installed extension and keep its config
make extension-list                # List configured Python extensions
make extension-enable NAME=...     # Enable an installed extension (restart required)
make extension-disable NAME=...    # Disable without uninstalling (restart required)
make extension-remove NAME=...     # Remove package and config entry (restart required)
make dev         # Start all services with hot-reload (Gateway + Frontend + Nginx)
make start       # Start all services in production mode (local, optimized); SKIP_FRONTEND_BUILD=1 reuses the last frontend build
make stop        # Stop all running services
make up / down   # Build/stop the production Docker stack (browser at localhost:2026)
make docker-start / docker-stop / docker-logs   # Docker development environment
```

Full list: `make help`.

**Module commands** (from each module):

```bash
# Backend (see backend/AGENTS.md for the full set)
cd backend && make dev        # Gateway API with reload (port 8001)
cd backend && make test       # Four parallel shards; excludes live and blocking-I/O tests
cd backend && make test-blocking-io  # Strict blocking-I/O suite
cd backend && make lint       # ruff check
cd backend && make format     # ruff format

# Frontend (see frontend/AGENTS.md for the full set)
cd frontend && pnpm dev       # Dev server: Webpack by default (override with DEER_FLOW_DEV_BUNDLER=turbo)
cd frontend && pnpm check     # Lint + type check (run before committing)
cd frontend && pnpm test      # Unit tests
```

Host pnpm calls use `scripts/pnpm.py`: native Windows tries `pnpm.cmd` before
`pnpm`; POSIX reverses the order. Its Corepack fallback applies the same ordering
to `corepack.cmd` and `corepack`. The runner operates from `frontend/` so
Corepack honors its pinned package-manager version.

### Prerequisites before `make dev`

Run `make config`, then `make install`, then `make dev` on first setup.
`make dev` requires existing config; both runtime configs are API-editable and
gitignored. Never commit them.

### Run a single test

```bash
# Backend (pytest); run one file or one test function
cd backend && python -m pytest tests/test_compose_default_bind_host.py -q
cd backend && python -m pytest tests/path/to/test.py::test_func -q

# Frontend (rstest)
cd frontend && pnpm rstest run <pattern>     # e.g. pnpm rstest run my-component
```

### Logs

- Docker stack: `make docker-logs` (or `docker compose -f docker/... logs -f <svc>`).
- Local `make dev`: Gateway and frontend output goes to
  `logs/gateway.log` and `logs/frontend.log` in the repository root.
  Run `tail -f logs/gateway.log logs/frontend.log` there to follow both.

## References

- Backend work → **[backend/AGENTS.md](backend/AGENTS.md)**
- Frontend work → **[frontend/AGENTS.md](frontend/AGENTS.md)**
- Setup & install → **[Install.md](Install.md)**, **[CONTRIBUTING.md](CONTRIBUTING.md)**
- Project overview → **[README.md](README.md)** (translations: `README_zh.md`,
  `README_ja.md`, `README_fr.md`, `README_ru.md`, `README_pt.md`, `README_ko.md`)
- User guides by topic → **[docs/guide/](docs/guide/)**
- Security policy → **[SECURITY.md](SECURITY.md)**
- Changes → **[CHANGELOG.md](CHANGELOG.md)**
- Cutting a release → **[RELEASING.md](RELEASING.md)**

## Cross-Cutting Conventions

Repo-wide conventions:

- **Docs live next to their topic** — document user-facing behavior in the matching
  guide under `docs/guide/` (or `backend/docs/`), in the same change set. `README.md`
  is an index: change it only to add or re-point a link, never to describe behavior
  (`make check-agent-guidance` enforces its size). Add to an `AGENTS.md` only what an
  agent cannot find by reading the code or running a command.
- **Test-driven development** — features and bug fixes ship with tests. Backend tests live
  in `backend/tests/` (TDD is mandatory there; see [backend/AGENTS.md](backend/AGENTS.md));
  frontend tests live in `frontend/tests/`.
- **Before pushing** — backend `make format`, frontend `pnpm check`.
  Backend CI enforces `ruff format --check`.
- **Version lockstep** — keep `backend/pyproject.toml`,
  `backend/packages/harness/pyproject.toml`, `frontend/package.json`, and
  `deploy/helm/deer-flow/Chart.yaml` (`version`/`appVersion`) identical.
  `backend/uv.lock` must match both `deer-flow` and `deerflow-harness` in PEP 440 form.
  Run `scripts/bump_version.sh <ver>` (requires `uv` on `PATH`) to update all five
  fields and the lock, then `scripts/verify_versions.sh <ver>`. `v*` tag CI blocks
  all publishing on drift. See [RELEASING.md](RELEASING.md).
- **Don't edit `CLAUDE.md`** — it only contains `@AGENTS.md`. All agent guidance changes
  belong here in `AGENTS.md`; `CLAUDE.md` is a thin import shim.
