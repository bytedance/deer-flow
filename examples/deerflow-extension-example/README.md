# deerflow-extension-example

A worked example of a DeerFlow extension. It is an **independent package**: its only
dependency is `deerflow-extension-api`, it lives outside `backend/`, it is not a
workspace member, and nothing in the host mentions it. You install it and list it under
`plugins:` — exactly as a third-party extension would be adopted.

What it does is deliberately trivial: it counts model calls, tool calls, tasks and the
host's own system model calls, and serves the counts on one route. The point is the
**shape** — where each contribution attaches, which scope owns which data, and when host
capabilities exist.

## What it demonstrates

| Contract surface | Where | Note |
| --- | --- | --- |
| `@extension(api=...)` | `__init__.py` | Version stamp; turns a skew into a startup diagnostic |
| `ExtensionInstall` | `__init__.py` | Entry-point signature, checked by the type checker |
| `ExtensionRegistry` — all five methods | `__init__.py` | `middlewares` / `task_lifecycle` / `system_model_observer` / `service` / `routers` |
| `MiddlewareContributor`, `AgentBuildContext` | `probes.py` | Reads `ctx.scope`, `ctx.model_name`, `ctx.policy` |
| `Placement` ×4, `AgentScope` | `probes.py` | Declared in pairs — see below |
| `task_store_from_runtime` | `probes.py` | The only way middleware reaches task scope |
| `TaskLifecycleContributor`, `TaskInfo`, `TaskOutcome` | `lifecycle.py` | One code path for lead and subagent |
| `SystemModelCallObserver` + request/result/kind | `lifecycle.py` | Counts the failure path too |
| `ExtensionService`, `ExtensionRuntimeDeps`, `HostPolicySnapshot` | `service.py` | Bind on `start()`, clear on `stop()` |
| `ExtensionData` — `get` / `set` / `get_or_init` / `remove` | everywhere | Two scopes, one flush |

Deliberately **not** used: `Placement.STANDARD` (reach for it only when you have no
before/after-processing requirement at all) and `deps.session_factory` for real storage
(extension persistence — a shared declarative `Base` and its migration chain — is a
separate concern from the observation contract; the route only reports whether it was
bound).

### Why the placements come in pairs

The pairs are what make the placement contract *visible in the output*:

- `MODEL_LOGICAL` vs `MODEL_PHYSICAL` — one logical decision may cost several physical
  provider calls. The gap in `/stats` is the host's retry behaviour, observed.
- `TOOL_RAW` vs `TOOL_VISIBLE` — the host truncates and sanitizes tool output before the
  model sees it. The gap in characters is that processing, measured from both ends of the
  same call.

That is also the shape of the tests: `test_probes.py` retries one decision and asserts
`logical == 1, physical == 2`. Misdeclare either placement and that assertion is what
fails.

**A trap worth knowing before you write your own tool probe.** The contract types a tool
result as `ToolMessage | Command`, and *which one you get depends on your placement*. The
host's `SandboxMiddleware` sits in the middle of the tool chain and rewraps a
`ToolMessage` into `Command(update={"sandbox": ..., "messages": [msg]})` so the sandbox id
reaches state — so anything outer of it, `TOOL_VISIBLE` included, receives a `Command`
carrying the real result inside. Treat that as "no content" and your outer probe reports
zero while the inner one reports the true size, which reads exactly like "the host
truncated everything". `_result_chars` unwraps it; `test_probes.py` pins the behaviour
with the production shape.

### Why the task record is flushed on stop

The host creates a task-scoped `ExtensionData` per agent execution and **drops it when
that execution returns**. So `on_task_stop` is the last moment anything a probe
accumulated can be saved, and it uses `remove()` rather than `get()`: the record is being
handed over, not shared.

## Run its tests

The tests need no DeerFlow host at all. `tests/conftest.py` builds a fake registry and
asserts `isinstance(fake, ExtensionRegistry)` — the contract Protocol is
`runtime_checkable`, which is what lets a third party prove conformance offline.

```bash
cd examples/deerflow-extension-example
uv venv --python 3.12
# `deerflow-extension-api` is not published to PyPI yet, so install it from this
# repo. Once it is published, this line becomes unnecessary.
uv pip install -e ../../backend/packages/extension-api
uv pip install -e ".[dev]"
uv run --no-project pytest
```

## Load it into a running DeerFlow

There is no CI test covering this path — the host side is exercised by
`backend/tests/test_extension_*.py`, and this walkthrough is what verifies that an
*independent* package still loads. Run it after changing the extension host.

**1. Install it into the backend environment**

```bash
cd backend
uv pip install -e ../examples/deerflow-extension-example
```

**2. List it in `config.yaml`** (repo root). `plugins:` is a top-level key, deliberately
separate from the `extensions:` block — this list causes code to be imported, so it stays
in the operator-controlled file and is never API-writable.

```yaml
plugins:
  - use: deerflow_extension_example:install
    config:
      enabled: true
      recent_task_limit: 20
```

**3. Start the stack and read the counters**

```bash
make dev
curl -s localhost:2026/api/extension-example/stats | python -m json.tool
```

Expect zeros, plus `host_policy` populated from the host's projection. Now send a message
in the UI and read it again: `model_calls`, `tool_calls`, `tasks` and `recent_tasks` move,
and `system_model_calls.title` appears after the first exchange is titled.

**Did it load at all?** The loader is silent on success — it logs only failures — so an
empty `gateway.log` is the *good* outcome, not evidence of a problem. For positive
confirmation, ask the OpenAPI schema, which is a public path and needs no session:

```bash
curl -s localhost:8001/openapi.json | python -c "import json,sys; print([p for p in json.load(sys.stdin)['paths'] if 'extension-example' in p])"
```

A non-empty result proves both that `install()` ran and that the router survived conflict
detection. Do **not** read `401` on the route itself as "not mounted": `AuthMiddleware`
runs before routing, so an unauthenticated request to a path that does not exist also
answers `401`, never `404`.

The route goes through nginx's `/api/*` passthrough, so no nginx change is needed. It is
also behind the Gateway's ordinary auth gate, like any other non-public `/api/*` path: a
bare `curl` answers `401 not_authenticated` whenever authentication is enabled. Easiest
fix is to open the URL in the browser tab where you are already signed in; plain `curl`
works only in auth-disabled mode. A contributed router gets no exemption from this, and
should not want one.

**4. Check the negative paths too**

- Set `config.enabled: false` → the package is still installed but registers nothing, and
  the path disappears from `/openapi.json` (the router was never contributed). Check it
  there rather than on the route, for the `401`-before-routing reason above.
- Set `recent_task_limit: "twenty"` → startup logs a diagnostic naming this extension and
  skips it. Add `required: true` to turn that into a startup failure instead.

## Files

```
deerflow_extension_example/
├── __init__.py     install() — the only entry point
├── stats.py        RunStats / TaskRecord — what gets counted; owns its own locks
├── probes.py       four middlewares + the build-time contributor
├── lifecycle.py    task lifecycle + system model call observer
└── service.py      ExtensionService + the eagerly built router
```
