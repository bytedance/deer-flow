# DeerFlow extension example

This directory is a compact, standalone Python package showing all five DeerFlow
extension contribution kinds. It depends on the public
`deerflow-extension-api` contract and never imports `deerflow.*` or `app.*`.

The contract package intentionally has no framework dependencies. An extension
must therefore declare every framework it imports itself; this example explicitly
depends on FastAPI, LangChain, and LangGraph in `pyproject.toml`.

## What it demonstrates

| Contribution | Example behavior |
| --- | --- |
| Middleware | Counts tool calls through one `TOOL_VISIBLE` middleware for lead agents and subagents |
| Task lifecycle | Creates task-scoped stats on start and folds them into app scope on stop |
| System-model observer | Counts DeerFlow-owned model calls, including failures |
| Service | Binds `ExtensionRuntimeDeps` only while the Gateway is running |
| Router | Eagerly declares `GET /api/extension-example/stats` during `install()` |

The middleware reads task scope only through `task_store_from_runtime()`. It
passes through unchanged when no task store exists. The router and service use
the same `ExampleService` object: its FastAPI dependency returns `503` before
`start()`, after `stop()`, or when no app store was bound. This keeps the route
topology stable while runtime capabilities arrive later.

## Run the package tests

`deerflow-extension-api` is currently sourced from this checkout. Install it
first, then install this independent package:

```bash
cd examples/deerflow-extension-example
uv venv --python 3.12
uv pip install -e ../../backend/packages/extension-api
uv pip install -e ".[dev]"
uv run --no-project pytest -q
uv run --no-project ruff check .
uv run --no-project ruff format --check .
```

The tests use only the public contract plus this package's declared dependencies;
the DeerFlow harness and Gateway application are not imported.

## Load it in DeerFlow

Install the package into the backend environment:

```bash
cd backend
uv pip install -e ../examples/deerflow-extension-example
```

Then add it to the startup-only, repository-root `config.yaml`:

```yaml
plugins:
  - use: deerflow_extension_example:install
    config:
      enabled: true
```

Restart the Gateway after changing `plugins`. Installing a package alone never
activates it, and `enabled: false` deliberately registers nothing.

After one or more runs, request the extension route:

```bash
curl -s http://localhost:2026/api/extension-example/stats
```

The response contains aggregated task outcomes, tool-call counts, system-model
call counts, the app scope id, and a small projection of the host policy. The
route passes through the Gateway's normal authentication middleware; use an
authenticated browser session when authentication is enabled.

## Package layout

```text
deerflow_extension_example/
├── __init__.py  # version-stamped install() entry point
└── plugin.py    # state plus all five small contribution implementations
tests/
└── test_plugin.py
```
