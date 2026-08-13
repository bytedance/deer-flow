### Python Extension System (Runtime Slice)

Third-party Python packages can expose an `install(registry, config)` function and be
loaded, in deterministic order, from the startup-only top-level `plugins:` list in
`config.yaml`. Keep this list out of `extensions_config.json`: the latter is writable
through Gateway APIs, while importing Python entry points is an operator-controlled code
execution boundary. A plugin marked `required: true` fails Gateway construction when it
cannot load; optional plugins fail open with attributed diagnostics.

The public package is `packages/extension-api/` and must never import `deerflow`. Its
registry contract exposes exactly three contribution kinds: middleware contributors,
task-lifecycle contributors, and system-model-call observers. Middleware contributions
declare lead/subagent scope, stable order, and a semantic placement (`MODEL_LOGICAL`,
`MODEL_PHYSICAL`, `TOOL_VISIBLE`, `TOOL_RAW`, or `STANDARD`) rather than a fragile list
index. `extensions/stack.py` is the single final composition point; do not inject inside
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

Lead runs and subagents allocate an `ExtensionData` task store only when at least one of
the three contribution kinds is registered. Middleware and system-call sites recover the
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
and in the process-wide singleton, and installs one canonical live diagnostics list.
Changing `plugins` requires a restart. Any future contribution kind must be added to the
public contract and host runtime in the same slice; never accept a registration method
that the current host silently ignores.
