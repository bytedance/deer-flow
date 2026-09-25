# Tool-execution approval (human in the loop)

Read this guide before changing tool approval, its middleware ordering, or the
REST/stream surfaces that carry a pending approval. It is the depth for entry 37
of the
[middlewares guide](../packages/harness/deerflow/agents/middlewares/AGENTS.md),
which only names the middleware and links here: that chain sits 15 bytes under
`scripts/check_agent_guidance.py`'s hard limit and `app/gateway/AGENTS.md` 26
under its own, so neither has room for more than a pointer. Anything that would
have gone in those guides belongs here, and the middleware's own docstrings
carry the load-bearing invariants.

A `tools[]` entry may add `interrupt_on` to gate that tool behind a real
LangGraph `interrupt()`. The run parks in the checkpoint as a pending task and
resumes only on `Command(resume={"decisions": [...]})` — what
`DeerFlowClient.resume()` sends.

## Two human-in-the-loop paths

`ask_clarification` and tool approval are both "ask the human", and they are not
interchangeable:

| | `ask_clarification` | tool approval |
| --- | --- | --- |
| Initiated by | the model, as a tool call | the system, as a gate on a tool call |
| Mechanism | `Command(goto=END)` — the turn ends | `interrupt()` — the run parks mid-turn |
| Resumed by | an ordinary next `HumanMessage` | `Command(resume={"decisions": [...]})` |
| Checkpoint | no pending task | pending task until resumed |
| Non-interactive escape | `disable_clarification`, `non_interactive` | `disable_tool_approval`, `non_interactive` |

The resume contracts are incompatible, so a gated `ask_clarification` would be
unresumable by either path: `ToolConfig` rejects the combination at config load
and the middleware builder drops it defensively. Unifying the two mechanisms is
deliberately out of scope for the change that introduced approval.

## Which clients can answer a park

The middleware is registered on every lead-agent build, so `tools[].interrupt_on`
is always effective and `DeerFlowClient.resume()` is always reachable. What varies
is whether a given client *can* answer, and the ones that cannot opt out per run
with `disable_tool_approval` rather than by suppressing the registration —
suppressing it would make the configuration and the resume API inert for every
caller, including those that do implement the protocol.

| Client | Path | Approval surface | Behaviour |
| --- | --- | --- | --- |
| `DeerFlowClient` | embedded, bypasses Gateway | `resume()` | parks and waits |
| Web UI | Gateway HTTP | none — does not consume `__interrupt__` | auto-approves |
| TUI | embedded via `DeerFlowClient` | none yet | auto-approves |
| IM channels | Gateway, via `ChannelManager` | none | auto-approves |
| Scheduler / MCP notifications | internal | none, by design | auto-approves (`non_interactive`) |

Each downgrade is set at its own entry point, because the three paths do not share
one: `start_run` for Gateway HTTP (after `strip_internal_context_keys`, so a client
copy of this internal-only key cannot pre-empt it), `_apply_channel_policy` for IM,
and the TUI's own run sites (`tui/app.py::_stream_worker` for the interactive app,
`tui/cli.py` for the `--print` / `--json` one-shots). A new client that grows an
approval surface removes its own downgrade; a new client without one must add it.
Pinned by `tests/test_tool_approval_client_downgrade.py`.

### Never downgrade a resume

A downgrade must not be applied to a run that carries `Command(resume=...)`, and
this is a correctness rule rather than a tidiness one. Downgrading a resume does
**not** auto-approve it: `_approval_disabled` makes
`_last_reviewable_ai_message` return `None`, so `after_model` returns before
re-entering `interrupt()`. LangGraph then discards the posted resume value with
no error at all — the gated `tool_calls` stay on the original `AIMessage` with
nothing answering them, and the `model → tools` edge dispatches exactly those
unanswered calls with their pre-review args. A `reject` silently becomes an
execution.

`start_run` therefore skips its assignment when the resolved `graph_input` is a
`Command`, keyed off the graph input rather than the presence of a `command`
field (`command: {"resume": null}` is an ordinary run). A caller posting
decisions is by definition the human this downgrade exists to protect. The path
is reachable: a thread parked by an embedded `DeerFlowClient` on a shared
checkpointer is visible over HTTP, and `GET /threads/{id}.interrupts` plus
`docs/API.md` tell clients to resume it this way. Pinned by
`test_a_resume_is_not_downgraded` and its two siblings.

## Middleware placement

`DeerFlowHumanInTheLoopMiddleware` subclasses LangChain's
`HumanInTheLoopMiddleware` and is appended **before** `ClarificationMiddleware`
precisely so it *dispatches after* it — LangChain runs `after_model` in reverse
registration order. Clarification drops the sibling tool calls of a
clarification request, and reviewing them first would ask the human about calls
that are about to be discarded. Pinned by
`tests/test_hitl_middleware_order.py`. It is applied to the lead agent only;
subagents are not gated.

New `build_middlewares` call sites must forward `tools=final_tools`, or `edit`
loses its args schema and falls back to raw-JSON edits.

## Replay safety across park/resume

LangGraph replays a node's function from the top on every resume — it does not
resume mid-function. Only `interrupt()`'s own return value and the return value
of `@task`-wrapped calls are cached against a per-node-task call index; anything
else `after_model` computes reruns fresh on the resume trip, reading that trip's
actual `state` and `runtime.context`.

This matters because a client may bundle a changed `tool_approval_omit` (e.g.
"approve, and don't ask again") into the very same `Command(resume=...)` call
that answers the batch it is changing. If which calls needed review were
recomputed at resume time, the recomputed batch could shrink or grow, desyncing
it against the `decisions` list the client sent for the *park*-time batch —
either a spurious count-mismatch `ValueError`, or worse, a call that was
pending review silently running unreviewed. `_review_batch_future` wraps
`_build_review_batch` in `langgraph.func.task` for exactly this reason: it
makes the review-batch decision once, at park time, and replays that exact
result on resume instead of recomputing it. Pinned by
`tests/test_human_in_the_loop_middleware.py::TestReplaySafeAcrossContextChange`,
which drives a real compiled `StateGraph` + checkpointer through a park/resume
cycle with a changed context, rather than only the direct-call unit-test style
used elsewhere in that file (which never replays and so cannot exercise this).

`task()` needs a running graph config; outside one (a direct unit-test call to
`after_model()` with no checkpointer) it raises `RuntimeError` immediately, so
`_review_batch_future` returns `None` and the caller computes
`_build_review_batch` directly — this keeps that call style working unchanged.

### The sync/async future split

`task()` hands back a `SyncAsyncFuture` whose completion is driven by whichever
pregel runner is executing, and the two are **not** interchangeable:

| Runner | `CONFIG_KEY_CALL` binds to | Resolve with |
| --- | --- | --- |
| sync (`compiled.stream`) | `_call` — submits to an executor, returns a `concurrent.futures.Future` | `future.result()` |
| async (`compiled.astream`, i.e. **every Gateway run**) | `_acall` — returns an `asyncio.Future` completed by the pregel tick loop | `await future` |

Upstream's `HumanInTheLoopMiddleware.aafter_model` merely calls
`self.after_model(...)` synchronously, which is fine for a pure body but not for
one that schedules a `@task`: `.result()` on an `_acall` future raises
`asyncio.InvalidStateError: Result is not set` on every real async run. So
`DeerFlowHumanInTheLoopMiddleware` overrides `aafter_model` and `await`s the
future there, while `after_model` keeps `.result()`. The two hooks share
`_last_reviewable_ai_message` (preconditions) and `_gate_on_review_batch`
(parking plus decision folding) so they can only ever differ in how the future
is resolved.

Do not "simplify" this back into a single hook: a sync-driven graph and a direct
`after_model()` unit call both stay green while 100% of production runs crash.
The async path is pinned by
`tests/test_human_in_the_loop_middleware.py::TestAsyncRunnerResolvesTheReviewBatch`,
which drives a real park/resume cycle through `compiled.astream`.

**Gotcha for anyone extending this middleware:** LangGraph's `RunnableCallable`
(which is what actually runs a `@task`-wrapped function) reserves the parameter
name `runtime` as an auto-injection point on *any* callable it invokes,
regardless of type annotation — it unconditionally injects its own `Runtime`
object into a parameter literally named `runtime`. `_build_review_batch`'s
third parameter is named `mw_runtime`, not `runtime`, because naming it
`runtime` collides with that injection and raises `TypeError: got multiple
values for argument 'runtime'` the moment it runs inside a real graph (a
direct-call unit test never goes through `RunnableCallable`, so it would not
catch this). Never name a `@task`-wrapped function's parameter `runtime`.

## Deviations from upstream

1. **Two downgrade switches**, either of which auto-approves everything, so no
   caller without a human on the other end can park a thread nobody can resume.
   `disable_tool_approval` is the tool-approval counterpart of
   `disable_clarification`, set by `channels/manager.py` for **all** channels
   before the empty-by-default `CHANNEL_RUN_POLICY` lookup.
   `non_interactive` is the pre-existing marker already set by the scheduler and
   the MCP task-notification launcher, and already used to strip
   `ask_clarification` from the toolset; reading it here means a non-interactive
   entrypoint does not have to opt in twice, and mirrors how
   `sandbox/middleware.py` treats the pair as one signal. Honouring only the
   newer key is what left scheduled runs parking unresumably.
2. **`tool_approval_omit`** carries tool names the human stopped wanting to be
   asked about ("don't ask again"), scoped to one caller's session rather than
   persisted to config. It is the one runtime-only key a client legitimately
   supplies, so the Gateway normalizes its shape and caps its length
   (`MAX_TOOL_APPROVAL_OMIT_ENTRIES`) rather than forwarding it verbatim. It
   must be on `_CONTEXT_RUNTIME_ONLY_KEYS` to reach `runtime.context` at all:
   `merge_run_context_overrides` forwards whitelisted keys only, and omitting it
   is what first shipped the browser's button inert while the TUI's — a direct
   `DeerFlowClient` caller that never crosses the Gateway — worked. Its shape is
   sanitized twice, not once: `merge_run_context_overrides` normalizes the copy
   it merges in from `body.context`, but `build_run_config` copies a client's
   `body.config['context']` largely verbatim, so a client naming the key there
   instead bypasses that normalization entirely. `start_run` also calls
   `sanitize_tool_approval_omit_in_config` after config assembly so both paths
   land on the same shape (or the key is dropped) regardless of which one the
   client used — the middleware itself only ever stringifies whatever it is
   handed, so unsanitized input reaching it would surface as tool names that
   can never match rather than an error.
3. **The configured `args_schema` is forwarded into the `ReviewConfig`**
   (upstream builds it without one) because the `edit` decision has nothing to
   render otherwise. Batch-mode `ToolCallRequest`s are constructed with
   `tool=None` and no `runtime.tools`, so that schema is captured at assembly
   time from `final_tools`, not at execution time.

   That capture reads `BaseTool.tool_call_schema`, **not**
   `get_input_jsonschema()`. Every sandbox tool takes a framework-injected
   `runtime: ToolRuntime` argument, and `get_input_jsonschema()` describes
   injected parameters too — `ToolRuntime` holds callables, so pydantic raises
   `PydanticInvalidForJsonSchema: Cannot generate a JsonSchema for
   core_schema.CallableSchema` and the capture degraded to a warning, leaving
   `bash` (the tool most likely to be gated) with no edit form.
   `tool_call_schema` excludes injected args by design, which is also the right
   contract here: a reviewer edits what the model filled, never injected values.
   It returns a dict when the tool declared a raw JSON `args_schema` and a
   pydantic model class otherwise, so both forms are handled.

   A stub tool written for a test typically has no injected args and so cannot
   catch a regression here; `test_captures_args_schema_for_a_tool_with_an_injected_runtime`
   pins it against the real `deerflow.sandbox.tools:bash_tool`.

## Decision semantics

Decisions follow upstream semantics: `approve` runs the call, `edit` rewrites
its args keeping the id, and `reject`/`respond` **keep** the call while pairing
it with a synthetic `ToolMessage` — the `model → tools` edge dispatches only
calls with no matching result, so answering is what prevents execution.

The revised turn is a `clone_ai_message_with_tool_calls` clone rather than
upstream's in-place `last_ai_msg.tool_calls = ...`, so the instance already
streamed to clients is not rewritten under them and
`additional_kwargs["tool_calls"]` stays in sync.

An `edit` needs one step more than that clone. It keeps the call id and changes
only the args, while the clone reconciles surfaces *by id* — so the pre-review
payload would survive on every surface except `tool_calls`: the raw provider
copy in `additional_kwargs["tool_calls"]`, and the content tool-call blocks
(Anthropic `tool_use`, OpenAI Responses `function_call` keyed by `call_id`,
LangChain v1 `tool_call` with its `extras.arguments`). Provider adapters do not
all read the same surface, so the tool node would run the edited args while the
next model request could be serialized from a stale one — telling the model
`rm` ran where the human approved `ls`. `_gate_on_review_batch` therefore runs
`rewrite_tool_call_args` (the shared helper documented in
`middlewares/tool_call_args.py`) over the edited ids *before* cloning, leaving
the clone only calls to drop. `approve`, `reject` and `respond` change no args
and rewrite nothing. Pinned by
`tests/test_human_in_the_loop_middleware.py::TestEditRewritesEveryProviderSurface`,
which asserts each surface separately — a test that checks only `tool_calls`
cannot catch this.

## Wire format

A parked run keeps its payload on `snapshot.tasks` only. LangGraph records
`__interrupt__` as a pending write, so the checkpoint's channel values never
carry it and no REST reader can find it in `values`; `Interrupt` also uses
`__slots__`, so it is not dict-like and must be projected field by field.

One helper pair in `deerflow.runtime` — `serialize_interrupts` and
`serialize_tasks_for_api` — is the single source of truth for that projection,
shared by every surface so a client reconciling a resumed stream against a
refetched snapshot sees one shape:

| Surface | Where the payload appears |
| --- | --- |
| `DeerFlowClient` stream | an `interrupt` event, projected from the `values` snapshot's `__interrupt__` (no extra stream mode needed) |
| browser chat stream | an `updates` frame's top-level `__interrupt__` |
| `GET /threads/{id}` | `interrupts`, the SDK's task-id -> interrupts mapping |
| `GET`/`POST /threads/{id}/state` | `tasks[].interrupts` |
| `POST /threads/{id}/history` | `tasks[].interrupts` |

The browser row is the one surface that is not a projection of `snapshot.tasks`.
LangGraph's `output_writes` emits the pending interrupt on the `updates` mode as
well as on `values`, each gated on that mode being requested — and the web chat
stream requests `messages-tuple`/`updates`/`custom` while deliberately dropping
`values`, so `updates` is its only in-stream witness to a park. `serialize()`
routes that frame through `serialize_lc_object`, whose `Interrupt` branch gives
it the same `{value, id}` shape as every other surface. Anything that changes the
chat stream's mode set, or that starts rewriting non-`values` frames, has to keep
that frame intact or the browser loses its approval card until the client's
post-stream history refetch. The consuming side is documented under "Detecting a
park" in `frontend/src/AGENTS.md`.

`interrupts` is added to a task only when one is pending, so an ordinary
in-flight task keeps the `{id, name}` shape older clients already parse.
`POST /threads/search` keeps `interrupts` empty on purpose: it serves thread
metadata, and filling it would cost one checkpoint load per listed row.
