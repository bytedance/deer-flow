### Python Extension System (Runtime and Distribution)

Third-party Python packages can expose an `install(registry, config)` function and be
loaded, in deterministic order, from the startup-only top-level `plugins:` list in
`config.yaml`. Keep this list out of `extensions_config.json`: the latter is writable
through Gateway APIs, while importing Python entry points is an operator-controlled code
execution boundary. A plugin marked `required: true` fails Gateway construction when it
cannot load; optional plugins fail open with attributed diagnostics.

Packaged extensions use one PEP 621 entry point in the
`deerflow.extensions` group, for example
`example = "deerflow_extension_example:install"`. The operator CLI is dispatched from
the existing `deerflow` console script to `extensions/cli.py` and exposes only these
surfaces: `install SOURCE [--yes]`, `list`, `enable NAME`, `disable NAME`, and
`remove NAME`. `NAME` resolves against the entry-point name, distribution name, or
`module:install` value. The root `make extension-*` targets are convenience wrappers;
because they execute from `backend/`, documentation should use absolute local source
paths with `SOURCE=` unless backend-relative behavior is intentional.

`ExtensionManager` owns the package/config transaction. Install runs a controlled
`uv add --project <backend> --group extensions --no-workspace --no-sync -- <source>`, updates the dedicated
`[dependency-groups].extensions` list and `uv.lock`, discovers exactly one packaging entry
point, and inserts or adopts one
managed `plugins:` record with `name`, `package`, `use`, `enabled`, `required`, and
private `config`. New records are written `required: false`, matching the loader default:
`required: true` turns any later load failure — a broken wheel, a missing native library, a
deleted snapshot — into a Gateway startup abort recoverable only through shell access, so
it is an explicit `install --required` opt-in rather than the managed default. Adoption of
an existing hand-written record preserves whatever `required` the operator already chose.
Enable/disable changes only the host-level `enabled` flag and preserves
private configuration. Remove runs `uv remove --group extensions`, removes the plugin
record, and deletes its managed source snapshot. Install validates the selected config
file before running any uv command, because `uv add`/`uv sync` execute the package's build
backend: a config this manager could never write to must fail before that code runs, not
afterwards through rollback.
Failed install/remove operations restore `pyproject.toml` and `uv.lock` and resynchronize
the restored environment; that second restore runs even when the recovery sync itself fails
(a recovery sync without `--locked` writes a lock while resolving), and a failing recovery
sync reports the original failure alongside it. The restore is deliberately not blanket:
when recovery detects a concurrent external edit to the dependency files or the config it
preserves that edit and raises instead, and `remove` leaves the plugin deactivated in that
case rather than reviving a record whose package declaration may already be gone. A
cancellation skips the recovery sync entirely — the declarations are already restored and
the next locked startup sync reconciles the environment, whereas blocking an interrupt on a
full dependency resolve invites a second interrupt that escapes the handler mid-transaction.
Package mutation is deferred from environment mutation: after `uv add/remove`
updates the declaration and lock, one `uv sync --locked --all-packages` preserves the same
config-/environment-detected optional extras as normal startup. All three uv calls pin the
backend project explicitly and discard UV environment overrides that could redirect the
project, working directory, sync mode, lock policy, or target environment — including
`UV_PYTHON`, which would swap the interpreter that then loads the extension entry point,
and `UV_INSECURE_HOST`, which would remove the TLS validation the HTTPS-only source rule
depends on; index, proxy, cache, and credential-provider settings remain available.
The `--no-workspace` boundary requires uv 0.8.0 or newer. The stock Docker paths pin uv
0.11.1, and the manager fails before mutation when the host uv is older.
All install/remove/enable/disable mutations for a checkout hold the cross-process
`.deer-flow/extension-manager.lock`; remove deactivates config before changing the package
declaration, and rollback preserves a concurrent external config edit instead of replacing
it. The MVP has no in-place upgrade: operators retain private config, remove the old
package, install the new source pin, and restore that config.

Local-directory installs are snapshots, not editable links. The manager validates the
source, derives the destination from the normalized distribution name, and copies it to
`backend/extensions/sources/<distribution>/`. It ignores Git metadata, virtual
environments, Python caches, and bytecode; rejects symbolic links, path-escaping
distribution names, and likely credential files; and the root `.dockerignore` explicitly
re-includes the entire managed tree so package READMEs, native modules, and assets reach
the backend builder. These checks prevent common packaging accidents, not malicious
code. Both Python build hooks and imported extension code execute with Gateway
privileges, so the CLI requires confirmation (or explicit `--yes`) and accepts only
trusted operator sources; source URLs containing embedded credentials are rejected.
Remote direct references are limited to HTTPS, and remote Git sources must use public
Git-over-HTTPS (with loopback HTTP accepted for local tooling). SSH Git URLs are rejected
because the stock Docker builder does not forward host SSH credentials; relative paths and
local wheels must use the managed directory snapshot path instead. Git's SCP-like shorthand
(`git@host:org/repo.git`) carries no URL scheme, so it is detected before the scheme rules
and reported with the same public-HTTPS correction rather than the local-path message.
Local wheel and `file://` sources are rejected because they cannot be reproduced inside the
Docker build context; local code must enter through the directory-snapshot path. Stock
production builds support public package indexes and public HTTPS Git sources reachable by
the builder; authenticated source configuration must not be embedded in the recorded URL.
Source validation alone cannot catch environment-driven resolution (for example a
`UV_FIND_LINKS` wheelhouse turning a plain package requirement into a local wheel
reference), so after every `uv add/remove` the manager audits the new lock before syncing
or enabling anything. Any local reference that the stock backend image build cannot
reproduce — absolute paths, `file:` URLs, or relative paths outside the project root, its
exact workspace members, and the managed `extensions/sources/` snapshots — fails the whole
transaction and rolls back the dependency files, config, snapshot, and environment. A
loopback URL recorded in the lock is warned about rather than rolled back: `127.0.0.1`
inside the image builder is a different machine, so the reference is just as
non-reproducible, but unlike an environment-driven wheelhouse resolution it is a source the
operator typed deliberately. A private-network index is left alone entirely — a builder on
that network can reach it. A
config with duplicate top-level `plugins:` keys is rejected outright rather than managed
against one block while the Gateway reads another.

The managed `plugins:` block is rewritten in place, and both of its boundaries come from
the YAML parser rather than a key-shaped pattern. `AppConfig` allows extra top-level keys,
so a neighbouring section may be named anything YAML accepts (`my.key`, `2fa`, `$schema`, a
non-ASCII word); a pattern that fails to recognize the next key does not fail loudly, it
reports "no next section" and the rewrite replaces that neighbour and its whole subtree.
Trailing comments below a file-final block are preserved for the same reason — the manager
appends `plugins:` at end of file, so that is the steady-state shape.

Dependency synchronization has one lock authority: the manager's `uv add/remove` calls
are the only extension workflow allowed to update `backend/uv.lock`, and each mutation is
followed by the local-source audit described above. The `extensions`
group is included in `[tool.uv].default-groups` alongside `dev`. Root/backend install
targets use `uv sync --locked`; direct backend `make dev`/`make gateway` use
`uv run --locked`; the local full-stack launcher and Docker-dev entrypoint perform one
locked sync and then launch with `uv run --no-sync`; the production Docker builder syncs
the same copied backend project and lock, and both image runtime commands use
`--no-sync`. Thus production may download locked remote artifacts while building an
image, but production container startup never resolves or installs an extension from the
network. Local and Docker-dev pre-start syncs may fetch missing locked artifacts.
`docker/dev-entrypoint.sh` retries a failed sync once after recreating `.venv`, but keeps
`--locked` on the retry: that repairs a broken virtualenv, not a stale lock. A second
failure aborts with recovery instructions instead of starting uvicorn against an
environment that does not match the lock, because startup must never silently resolve
dependencies.
That discipline assumes the uv writing the lock and the uv reading it stay compatible, so
uv is pinned rather than floating: `backend/Dockerfile`'s `UV_IMAGE` is the single source of
truth, both compose defaults repeat it, and every `astral-sh/setup-uv` step pins the same
version so CI exercises the manager against the binary production actually runs. Otherwise a
newer uv can bump `uv.lock`'s `revision` (or make `uv lock --check` disagree with a lock
generated elsewhere) while CI stays green, and the pinned uv in the production image then
fails on the committed lock. `backend/tests/test_ci_uv_version_pin.py` keeps the four
locations in step, which makes a uv upgrade one deliberate, reviewable change.
Rebuild the Gateway image after changing the managed set. Every install, enable, disable,
remove, or config mutation also requires a Gateway restart because plugin loading is
startup-only.
The root management wrappers bootstrap the checkout environment without the extension group
via `uv run --frozen --no-group extensions`, so a broken or disappeared extension source cannot
trigger project validation before the operator can list, disable, or remove it, while a
fresh checkout can still install the non-extension environment from the existing lock. After CLI
entry, the manager owns the controlled locked sync.

The public package is `packages/extension-api/` and must never import `deerflow` or carry
framework dependencies. Extensions declare any FastAPI, LangChain, or LangGraph imports
themselves. Its registry contract exposes five contribution kinds: middleware
contributors, task-lifecycle contributors, system-model-call observers, Gateway-lifetime
services, and eager routers. Middleware contributions declare lead/subagent scope, stable
order, and a semantic placement (`MODEL_LOGICAL`, `MODEL_PHYSICAL`, `TOOL_VISIBLE`,
`TOOL_RAW`, or `STANDARD`) rather than a fragile list index. `extensions/stack.py` is the
single final composition point; do not inject inside
the shared base builder because the lead builder appends more middleware afterward.
`extensions/ordering.py` owns host ordering invariants and validates the final composed
stack. Nothing under `extensions/` may import `agents.middlewares` at module scope: the
middleware layer calls into this one, so a module-scope reference points the dependency
backwards and closes a cycle as soon as any middleware imports something under
`extensions/` at module level. Both tables that need middleware classes therefore resolve
on first use — `ordering.py::core_ordering_constraints()` and `stack.py::_anchors()` —
which is `assert_ordering` / composition time, already inside the middleware builder.
Defer by deferring the *call*; do not fake a resolved value with a lazy container
subclass, which reports one answer when iterated and another when measured.

Contributed middlewares are wrapped by `IsolatedMiddleware`: extension failures emit
diagnostics and fail open without repeating a downstream model/tool side effect. The
wrapper mirrors lifecycle hooks, tools, transformers, and state schema implemented by
the inner middleware. LangChain treats each sync/async model or tool wrapper pair as one
capability, so a single-sided wrapper receives a pass-through counterpart; implement
both sides when the extension must observe both synchronous and asynchronous execution
paths.

Lead runs and subagents allocate an `ExtensionData` task store only when middleware,
task-lifecycle, or system-model observation is registered; services and routers are
app-scoped and do not allocate one. Middleware and system-call sites recover the
live store through `EXTENSION_TASK_STORE_KEY` / `task_store_from_runtime()`; lifecycle
contributors receive that same store directly. Each task resolves the immutable
loaded-extension snapshot once and binds that same object through task-store allocation,
hooks, and synchronous agent construction, so a concurrent singleton replacement cannot
mix two extension generations without changing the LangGraph graph-factory ABI. The
graph-build binding is a ContextVar scoped to synchronous construction, so it has already
exited by the time the lead agent delegates; the run worker therefore also publishes the
snapshot on runtime context under the host-internal `EXTENSION_SNAPSHOT_CONTEXT_KEY`,
`task_tool` reads it back through `resolve_run_extensions()` (type-checked — runtime
context is caller-mergeable), and `SubagentExecutor` binds it at construction. That key is
written after the caller merge and popped when the run has none, so a caller-supplied value
is never authoritative. Absent the key — embedded `DeerFlowClient`, standalone LangGraph
Server — the executor keeps its `get_loaded_extensions()` fallback.

The lead worker awaits `on_task_start` after the run has started and awaits `on_task_stop`
after completion persistence/hooks but before clearing any active finalizing barrier or
publishing the stream end. A subagent with a parent `run_id` wraps its execution with the
same start/stop pair. Outcomes are conservative (`completed`, `aborted`, or `failed`),
contributors run in registration order within one bounded budget, and notification failures
are logged and fail open.

Fail-open is decided by the *origin* of a failure, not by its base class, because
`CancelledError` reaches a contributor's `except` for two unrelated reasons. Only a genuine
cancellation of the host task increments `asyncio.Task.cancelling()`, so `_notify_each`
propagates on that and contains everything else: a contributor that lets a `CancelledError`
escape — an extension implementing an internal timeout with cancellation, say — must not
skip its successors, and must not reach the worker's deferred-interrupt path, which would
end an otherwise successful run as cancelled. `KeyboardInterrupt` / `SystemExit` still
propagate.

System-model-call observers cover DeerFlow-owned model invocations that do not pass
through middleware model-call wrappers: goal evaluation, memory extraction, title
generation, and summarization. They receive a request/result snapshot, duration, and the
active task store when one exists; detached system work receives an isolated store. All
three terminal paths are reported without changing the exception the host observes:
success and failure are awaited inline, while cancellation — routine, since
interrupt/rollback admission and shutdown both cancel the run task, with the provider
tokens already spent — is submitted to the notify loop instead of awaited, because a
repeated cancel would interrupt that await before any observer ran. A deployment with no
registered notify loop drops the cancellation observation, exactly as the synchronous
memory bridge does. `SystemModelRequest.messages` normalizes to a tuple at construction: goal and
memory pass a message list while title and summarization pass one prompt string, and a
bare `str` is already a `Sequence`, so without normalization an observer iterating it
would walk characters. Normalizing also copies a live list, which is what makes the frozen
snapshot immutable in fact rather than only by declaration. Gateway registers one canonical extension-notification loop. Awaited lifecycle
hooks and async system observations are dispatched to that loop even when the caller is a
subagent's isolated loop, while synchronous system callbacks submit fire-and-forget work
there. Shutdown stops accepting detached observations before the memory shutdown flush and
resets the loop only after in-flight run/subagent drain ordering is complete.

Gateway services start in registration order after the persistence engine and session
factory are ready. Each receives the same `ExtensionRuntimeDeps` snapshot containing the
app store, projected host policy, and session factory. Start failures are attributed and
fail open. The runtime captures `app.state.extensions` once, registers cleanup before the
start batch, and stops the attempted service prefix in reverse order after run/subagent
drain but before store, checkpointer, and engine teardown. Each stop has an independent
bounded timeout; failures do not starve later cleanup. A service-originated
`CancelledError` fails open, while a new cancellation of the host task still propagates
through the exit stack. Runtime diagnostics must be appended through
`record_runtime_diagnostics()` so `app.state.extension_diagnostics` remains the canonical
live list.

Routers are constructed eagerly during `install()` and mounted only after all host routes,
so host handlers always win. The Gateway rejects a contributed router atomically when an
earlier host or extension route provably covers one of its paths for the same HTTP method.
The conservative matcher proves common shadows through normalized parameter names,
static-vs-dynamic matching, known built-in-converter containment, supported compound
segments, full-segment `path` catch-alls, and `Mount` descendants reducible to those same
rules. Relationships requiring general regex-language inclusion are allowed rather than
guessed. Host WebSocket routes do not collide with contributed HTTP routes, but contributed
WebSocket routes are rejected until the host can supply authentication and Origin checks.
Because `include_router()` recompiles contributed routes, preflight projects the converter
registry at include time. Nonstandard converters fail closed against reserved security
paths but otherwise prove a shadow only when their normalized matchers are identical.
Host authentication- and CSRF-exempt paths are reserved, and contributed Mounts, unsupported
route items, startup/shutdown hooks, and custom router lifespans are rejected; lifetime
resources must use `ExtensionService`. Auth and CSRF classify
`get_request_route_path(request)`, the same root-path-adjusted ASGI path Starlette routes
match; do not switch those security predicates back to reconstructed `request.url.path`.
That helper delegates to the private `starlette._utils.get_route_path` on purpose. Its
requirement is not "strip `root_path` correctly" but "return exactly what the router is
matching on", so importing the dispatcher's own implementation keeps the two in lockstep by
construction. Do not vendor a local copy: a private import that disappears fails loudly at
startup, while a stale copy diverges silently at a security boundary. `starlette` is
therefore a declared, bounded direct dependency so the bump is visible in review, and
`tests/test_gateway_request_path.py` pins the agreement independently of the mechanism.
Any preflight, conflict, or include failure rolls back the whole router without preventing
later routers from mounting. Do not introduce a framework-bound `RouterContributor`
contract: the public registry accepts `Sequence[Any]`
to keep extension-api dependency-free.

The memory kind reaches those observers through a different shape, and the difference is
deliberate rather than an oversight to be "aligned" away. DeerMem must stay vendorable and
cannot import the extension API, so it reports through the `MemoryCallbacks.on_memory_llm_result`
host hook, which the DeerFlow-side callbacks translate into an observation and submit
without awaiting. It also guards its provider call with `BaseException` rather than
`Exception`, which is safe precisely because that whole path runs on a worker thread — the
debounce timer, or the executor `update_memory` offloads to — where cancelling the awaiting
side never interrupts the running thread, so `CancelledError` cannot arrive there at all.
The host hook wrapper around the callback stays at `Exception`: only the hook's own failures
are non-fatal, and an observability path must not swallow `SystemExit` / `KeyboardInterrupt`.

Gateway `create_app()` loads plugins once, stores the immutable registry on `app.state`
and in the process-wide singleton, mounts contributed routers last, and installs one
canonical live diagnostics list.
Changing `plugins` requires a restart. Any future contribution kind must be added to the
public contract and host runtime in the same slice; never accept a registration method
that the current host silently ignores.

### Extension Manager Test Repositories

`test_extension_manager.py` creates temporary Git repositories for local extension sources.
Temporary commits use an empty repository-local hook directory. They must not run developer or CI Git hooks.
Tests for hook behavior must create and invoke their own hook fixtures.
