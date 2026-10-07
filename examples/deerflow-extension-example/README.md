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
| Middleware | Counts synchronous and asynchronous tool calls, outcomes, and elapsed time at `TOOL_VISIBLE` for lead agents and subagents |
| Task lifecycle | Creates task-scoped stats on start and folds them into app scope on stop |
| System-model observer | Counts DeerFlow-owned model calls, including failures |
| Service | Binds `ExtensionRuntimeDeps` only while the Gateway is running |
| Router | Eagerly declares `GET /api/extension-example/stats` during `install()` |

The middleware reads task scope only through `task_store_from_runtime()`. It
passes through unchanged when no task store exists. The router and service use
the same `ExampleService` object: its FastAPI dependency returns `503` before
`start()`, after `stop()`, or when no app store was bound. This keeps the route
topology stable while runtime capabilities arrive later.

### Tool statistics

The existing `tool_calls` field counts calls entering the wrapper. The stats
response also includes these fields (this is illustrative output, not a benchmark):

```json
{
  "tool_calls": 3,
  "tool_outcomes": {"returned": 1, "raised": 1, "cancelled": 1},
  "tool_duration_samples": 3,
  "tool_duration_total_ms": 60.0
}
```

- `returned` means the downstream handler returned normally, including an error
  `ToolMessage`. It does **not** measure business success. A tool exception
  converted into a normal return downstream of `TOOL_VISIBLE` counts here too.
- `cancelled` counts `asyncio.CancelledError` escaping the handler, including
  actual task cancellation. `raised` counts other escaping exceptions, including
  LangGraph `GraphBubbleUp` control-flow signals such as graph interrupts.
  Results and exceptions propagate unchanged; each wrapper calls its handler once.
- Each completed observation adds one duration sample, including zero-duration
  calls. Elapsed time uses a monotonic clock and includes downstream middleware
  processing. Durations of overlapping lead/subagent calls are summed, so this
  total is **not** elapsed run time or exclusive tool execution time.

Outcome counters, duration samples, and elapsed totals are updated together under
a lock. Task stats are copied and merged into app scope on task stop, after the
task's tool calls have settled. The first stop consumes the task stats; duplicate
stops (or a stop without a matching start) add neither tasks nor tool statistics.
If a host stops a task while calls are still running, only the snapshot at that
stop is merged; later completions are not published. Active tasks are not included
in the app's tool totals. The system-model observer retains its existing behavior.

The new fields contain only fixed counters and timing totals, with no tool names,
arguments, outputs, exception text, or identifying labels. Stats are process-local
and reset on restart; they are not persisted or shared across workers.

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

## Install and load it in DeerFlow

From the DeerFlow checkout root, install this directory through the extension
manager. Use an absolute path because the Make wrapper invokes the manager from
`backend/`:

```bash
make extension-install SOURCE="$PWD/examples/deerflow-extension-example"
make extension-list
```

After the trust prompt is accepted, the manager:

- copies a deployable snapshot to
  `backend/extensions/sources/deerflow-extension-example/`;
- adds that snapshot to `backend/pyproject.toml`'s `extensions` dependency
  group and updates `backend/uv.lock`;
- installs the locked environment; and
- adds and enables this startup-only entry in the selected `config.yaml`.

```yaml
plugins:
  - name: example
    package: deerflow-extension-example
    use: deerflow_extension_example:install
    enabled: true
    required: false
    config: {}
```

Start or restart DeerFlow after installation:

```bash
make dev
```

The Gateway imports extensions only while constructing the application. Install,
enable, disable, remove, and manual `plugins:` changes therefore take effect only
after a restart. These commands manage the example afterward:

```bash
make extension-disable NAME=example
make extension-enable NAME=example
make extension-remove NAME=example
```

The manager can also install a PyPI requirement or a pinned public HTTPS Git
URL. SSH Git URLs are rejected because the stock Docker builder does not
forward host SSH credentials. The direct CLI surface, run from `backend/`, is:

```text
uv run --frozen --no-group extensions deerflow extensions install <source> [--yes] [--required]
uv run --frozen --no-group extensions deerflow extensions list
uv run --frozen --no-group extensions deerflow extensions enable <name>
uv run --frozen --no-group extensions deerflow extensions disable <name>
uv run --frozen --no-group extensions deerflow extensions remove <name>
```

`--yes` is intended only for automation that has already reviewed and trusted
the source: extension build hooks and runtime code execute with Gateway
privileges. `--required` records `required: true`, which turns any later load
failure into a Gateway startup abort; leave it off unless the application is
wrong without this extension.

The local snapshot is included in Docker builds. Local `make dev`, Docker dev,
and the production Gateway image all consume the same `backend/uv.lock`.
Development launchers may download missing locked artifacts before handing off
to the Gateway; a built production container does not. Rebuild the production
image with `make up` after changing the installed set.

After one or more runs, request the extension route:

```bash
curl -s http://localhost:2026/api/extension-example/stats
```

The response contains aggregated task outcomes, tool-call counts, outcomes and timing, system-model
call counts, the app scope id, and a small projection of the host policy. The
route passes through the Gateway's normal authentication middleware; use an
authenticated browser session when authentication is enabled.

## Packaging entry point

Managed packages expose exactly one standard PEP 621 entry point in the
`deerflow.extensions` group. This example declares:

```toml
[project.entry-points."deerflow.extensions"]
example = "deerflow_extension_example:install"
```

The entry-point name (`example`) is the stable operator-facing name accepted by
`enable`, `disable`, and `remove`; those commands also accept the distribution
name or the `module:install` value.

## Package layout

```text
deerflow_extension_example/
├── __init__.py  # version-stamped install() entry point
└── plugin.py    # state plus all five small contribution implementations
tests/
├── test_entry_point.py
├── test_plugin.py
└── test_tool_stats.py
```
