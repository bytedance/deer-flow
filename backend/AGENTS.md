# Backend (`backend/`)

The Python backend: the publishable harness in `packages/harness/deerflow/`, the
public extension contract in `packages/extension-api/`, and the unpublished
Gateway and IM channels in `app/`. In every deployment the agent runtime runs
inside the Gateway. Design docs are in [docs/](docs/); start with
[ARCHITECTURE.md](docs/ARCHITECTURE.md) and [API.md](docs/API.md).

## Guides by area

Read the guide for an area before you change it.

| Area | Guide |
| --- | --- |
| Run streaming, checkpoints, run ownership | [runtime](packages/harness/deerflow/runtime/AGENTS.md) |
| Repositories, leases, scheduled tasks, schema changes | [persistence](packages/harness/deerflow/persistence/AGENTS.md), [migrations](packages/harness/deerflow/persistence/migrations/AGENTS.md) |
| Scheduler failure isolation | [design conventions](app/scheduler/guide/failure-isolation.md) |
| `config.yaml`, `extensions_config.json` | [config](packages/harness/deerflow/config/AGENTS.md) |
| Lead agent, prompt, thread state, middleware chain | [agents](packages/harness/deerflow/agents/AGENTS.md), [middlewares](packages/harness/deerflow/agents/middlewares/AGENTS.md) |
| Memory, subagents, skills, tools | [memory](packages/harness/deerflow/agents/memory/AGENTS.md), [subagents](packages/harness/deerflow/subagents/AGENTS.md), [skills](packages/harness/deerflow/skills/AGENTS.md), [tools](packages/harness/deerflow/tools/AGENTS.md) |
| Sandbox, uploads, MCP, models, extensions | [sandbox](packages/harness/deerflow/sandbox/AGENTS.md), [uploads](packages/harness/deerflow/uploads/AGENTS.md), [mcp](packages/harness/deerflow/mcp/AGENTS.md), [models](packages/harness/deerflow/models/AGENTS.md), [extensions](packages/harness/deerflow/extensions/AGENTS.md) |
| Trace ID, embedded client, other root modules | [harness package](packages/harness/deerflow/AGENTS.md) |
| Search, fetch and sandbox providers | [community](packages/harness/deerflow/community/AGENTS.md), then the provider's own guide |
| Gateway, routers, IM channels | [gateway](app/gateway/AGENTS.md), [routers](app/gateway/routers/AGENTS.md), [channels](app/channels/AGENTS.md) |
| Tests, benchmarks | [tests](tests/AGENTS.md), [benchmarks](scripts/benchmark/AGENTS.md) |

## Verify

```bash
make test               # offline suite in parallel shards
make test-blocking-io   # strict blocking-I/O suite
make test-bundled-extensions  # behavior suites of bundled examples (not in make test)
make lint
make format
make test-live          # calls real APIs; needs DEER_FLOW_RUN_LIVE_TESTS=1
```

Run `make test` and `make test-blocking-io` before and after a change. Every
feature and bug fix ships with a test in `tests/`. Live tests stay opt-in, so the
default suite needs no network and no API key.

## Rules

- **The harness never imports `app`.** `app.*` imports `deerflow.*`, and not the
  reverse, because the harness is published on its own.
  `tests/test_harness_boundary.py` enforces this in CI.
- **Start the Gateway with `make dev` or `make gateway`.** `make dev` excludes
  `DEER_FLOW_HOME` and `backend/sandbox` from the reload watcher. A bare
  `uvicorn --reload` restarts the Gateway during a run, because agent tasks write
  Python files below `DEER_FLOW_HOME`.
- **From the repository root, run backend tools with
  `uv run --no-sync --project backend`.** `--project` keeps the caller's working
  directory, so relative config paths still resolve. `--no-sync` keeps installed
  extras such as the PostgreSQL drivers.
- **Run Python through `uv run` inside `backend/`**, without `--no-sync`, so the
  environment matches the lock.
- **Guard POSIX-only test markers with `os.name`.** Windows collects the same
  files.
- **Tool approvals need addressable calls.** Strip missing, empty and duplicate
  tool-call IDs before creating a pause or a tool result. See the
  [run interaction policy](docs/RUN_INTERACTION_POLICY.md#hitl-tool-approval).
- **Add a schema change with `make migrate-rev MSG="..."`** and follow the
  migrations guide.
