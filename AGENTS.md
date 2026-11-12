# DeerFlow

DeerFlow is an agent harness: a LangGraph-based backend with thread-isolated
sandboxes, memory, subagents, skills and MCP tools, and a Next.js frontend. IM
channels connect through the Gateway. `CLAUDE.md` imports this file; edit
guidance here, not in the shim.

## How guidance is organized

Rules live in the `AGENTS.md` nearest to the code. Before you edit a directory,
read every `AGENTS.md` from that directory up to this file. Some coding agents do
not load the nested files on their own.

| Area | Guide |
| --- | --- |
| Backend: harness, Gateway, channels, tests | [backend/AGENTS.md](backend/AGENTS.md) |
| Frontend | [frontend/AGENTS.md](frontend/AGENTS.md) |
| nginx, Compose, provisioner | [docker/AGENTS.md](docker/AGENTS.md) |
| Orchestration scripts, `scripts/pnpm.py` | [scripts/AGENTS.md](scripts/AGENTS.md) |
| Skill review, skill tests | [skills/AGENTS.md](skills/AGENTS.md) |
| Extension examples | `examples/*/AGENTS.md` |

Humans start at [README.md](README.md), [CONTRIBUTING.md](CONTRIBUTING.md) and
[docs/guide/](docs/guide/).

## Service topology

| Service | Port | Role |
| --- | --- | --- |
| Nginx | 2026 | The single entry point; open this in the browser |
| Gateway | 8001 | FastAPI REST API and the embedded agent runtime |
| Frontend | 3000 | Next.js web interface |
| Provisioner | 8002 | Optional; only for provisioner or Kubernetes sandboxes |


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
├── examples/  # Extension examples: deerflow-extension-{example,bookmarks,agent-teams}; standalone helper: deerflow-storage-adapters
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
The [storage adapter example](examples/deerflow-storage-adapters/README.md) is an
independently installable library for extension-owned data, not a Gateway plugin.
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

Skill quality review note:
- `skills/public/skill-reviewer/` is the built-in read-only reviewer (harness tool
  `review_skill_package`, contracts in `contracts/skill_review/`). Model-visible review
  data is tag-neutralized; raw payloads stay in tool artifacts. See
  [backend/AGENTS.md](backend/AGENTS.md) for the ownership boundaries.
- CI waivers live in `.github/skill-review-waivers.v1.json`, enforced by
  `scripts/review_changed_public_skills.py`. Only the manifest from the trusted base
  revision can suppress a run, and blocker findings can never be waived.

Scheduled-task note:
- `scheduler.tool_enabled` (default off) offers owner-bound schedule tools only
  through Gateway capability admission. Interactive turns create/manage their
  schedules; scheduled turns can request stopping only their own schedule.
  Per-occurrence goal success does not end a recurring schedule.
- The scheduled-task MVP adds a workspace page at `/workspace/scheduled-tasks` plus a
  background scheduler gated by `config.yaml -> scheduler.enabled`.
- Scheduled runs are non-interactive: `ask_clarification` is excluded. `non_interactive`,
  `disable_clarification`, and `github_token` are honored only for internally-authenticated
  callers; client-supplied copies are dropped.
- Busy occurrences persist as `queued`; `scheduler.queue_timeout_seconds` bounds the wait.
  Do not reintroduce skip-on-overlap.

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
make extension-remove NAME=...     # Remove package and config entry (restart required)
make dev         # Start all services with hot-reload (Gateway + Frontend + Nginx)
make start       # Start all services in production mode (local, optimized); SKIP_FRONTEND_BUILD=1 reuses the last frontend build
make stop        # Stop all running services
make up / down   # Build/stop the production Docker stack (browser at localhost:2026)
make docker-start / docker-stop / docker-logs   # Docker development environment
```

Nginx serves the frontend, proxies `/api/*` to the Gateway and rewrites
`/api/langgraph/*` to the Gateway's native routes.


Before changing ingress, port bindings or provisioner mounts, read
[service topology details](docs/agent-service-topology.md).

## Repository map

| Path | Content |
| --- | --- |
| `backend/packages/harness/` | `deerflow-harness`, import `deerflow.*`: the agent framework |
| `backend/packages/extension-api/` | `deerflow-extension-api`: the public extension contract |
| `backend/app/` | The Gateway and the IM channels, import `app.*` |
| `frontend/` | The Next.js app (pnpm) |
| `docker/`, `deploy/helm/` | Compose files, nginx config, provisioner, Helm chart |
| `skills/public/`, `skills/custom/` | Committed skills and local, gitignored skills |
| `contracts/` | JSON contracts shared across components |
| `examples/` | Installable extension examples |
| `scripts/`, `tests/` | Root orchestration scripts, and tests for public skills |

`config.yaml` and `extensions_config.json` are copied from the example files at
the repository root. Both are gitignored and the Gateway can write them. Do not
commit them.

## Commands

`make help` lists the root targets. First setup is `make config`, then
`make install`, then `make dev`, which serves the stack on `localhost:2026` and
writes `logs/gateway.log` and `logs/frontend.log`.

```bash
cd backend && make test && make test-blocking-io   # offline suites
cd backend && make format                          # CI runs ruff format --check
cd backend && python -m pytest tests/path/test_x.py::test_name -q
cd frontend && pnpm check && pnpm test
cd frontend && pnpm rstest run <pattern>
make check-agent-guidance                          # size budget of these guides
```

## Rules for every change

- **Evaluate an extension first.** Before you add a feature to core code, check
  whether it can ship as a packaged extension. Core is the place for bug fixes
  and for changes to the agent loop, memory, context compaction and
  authentication. When the existing hooks cannot express a feature, add a
  generic hook to the extension contract and an extension that uses it; business
  logic is not hard-coded into core. Contract and examples:
  [extensions guide](backend/packages/harness/deerflow/extensions/AGENTS.md),
  `examples/`.
- **Extensions are operator-controlled code.** They load from `plugins:` in
  `config.yaml`. The list stays out of the API-writable `extensions_config.json`,
  because loading an extension imports code with Gateway privileges. Install
  from trusted sources only, and restart the Gateway after every extension
  change.
- **Ship tests with every feature and bug fix.**
- **Document behavior next to its topic, in the same change**: user-facing
  behavior in `docs/guide/` or `backend/docs/`. `README.md` is an index; change
  it only to add or re-point a link.
- **Keep the version fields identical**: `backend/pyproject.toml`,
  `backend/packages/harness/pyproject.toml`, `frontend/package.json`, and
  `version` and `appVersion` in `deploy/helm/deer-flow/Chart.yaml`.
  `scripts/bump_version.sh <ver>` updates them and `backend/uv.lock`, and
  `scripts/verify_versions.sh <ver>` checks the result. Tag CI blocks publishing
  on drift. See [RELEASING.md](RELEASING.md).

## What belongs in an `AGENTS.md`

An agent reads these files on every task, so each line costs attention. A guide
holds four kinds of content:

1. Scope: what the directory owns, in one or two sentences.
2. Verification: the exact commands.
3. Traps: where the code misleads, or where a plausible change breaks something
   that a local test run does not show.
4. Decisions and their reasons that the code cannot state, and links to docs.

Values, defaults, field lists, function inventories, test names, issue numbers
and history stay in the code, the tests and git. Write full sentences in the
positive form and give the reason. `make check-agent-guidance` enforces the size
budget.

### Office preview example

`examples/deerflow-extension-office-preview/` packages Office readers through the
optional `artifactPreviews` browser contract. Keep parser dependencies and resources
in the extension; rebuild its manifest and static module graph after UI changes.
Test packaged assets with the Office E2E fixtures; rendering must preserve original
downloads and state its search limits.
