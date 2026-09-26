# Tool-execution approval (human in the loop)

Read this guide before changing tool approval, its middleware ordering, or the
REST/stream surfaces that carry a pending approval. It is the depth for entry 37
of the
[middlewares guide](../packages/harness/deerflow/agents/middlewares/AGENTS.md),
which only names the middleware and links here. Neither guide has room for more
than a pointer, against two different `scripts/check_agent_guidance.py` limits:
that middleware chain runs close to the hard *chain* budget of 98304 bytes
(inherited from four ancestors — adding entry 37 is what pushed it over, and
entry 38's depth had to move to [Clarification](CLARIFICATION.md) to make room),
and `app/gateway/AGENTS.md` sits 26 bytes under the hard *per-file* one (49126
of 49152). Anything that would
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
`tests/test_tool_approval_client_downgrade.py::test_a_resume_is_not_downgraded`
and `::test_a_resume_with_no_decisions_is_still_not_downgraded`, with
`::test_an_empty_command_still_downgrades` holding the other side.

`DeerFlowClient._stream_turn` applies the same exclusion, and it is the entry
point where the trap is easiest to fall into: `resume()` forwards `**kwargs`
verbatim and its docstring advertises them as "same overrides as `stream()`", so
a caller holding `disable_tool_approval` for its session would downgrade the one
call that must not be. The embedded client is precisely the caller expected to
park and answer — and the TUI passes that switch at every call site today, so it
would hit this the moment it grows a resume submission, in the very change meant
to remove the downgrade. Pinned by
`tests/test_client_tool_approval.py::TestResumeIsNeverDowngraded`.

### A resume seeds its dedup baseline from the checkpoint

`_stream_turn` separates "this turn" from history by finding the `HumanMessage`
that carries this call's `run_id`, and everything before it becomes
`historical_message_ids` — skipped as a delta and excluded from cumulative usage.
A resume passes `Command(resume=...)` and deliberately appends no `HumanMessage`,
so that marker never appears: the index resolves to `None`, the baseline stays
empty, and on a populated thread the whole prior turn is re-emitted as new deltas
while its `usage_metadata` is added to this resume's total.

`_resume_baseline_messages` therefore reads the parked checkpoint directly when
`resume` is set. It is best effort — a failed read costs a noisy stream, not the
resume.

**The trailing AI message is held out of the history set but still added to the
usage ledger**, and the split is the subtle part — the two sets answer different
questions.

It must not be history: it carries the gated tool calls, and `edit` rewrites its
args under the *same id*. The baseline skip is a `continue` ahead of the "same id,
different object" branch, and that branch re-emits appended *text* only, never
tool calls, so suppressing this id would silently drop the human's edit.
Re-emitting it costs nothing, because a `messages-tuple` event merges into the
message carrying that id — which is precisely how an edit reaches the client.

Its `usage_metadata` is the opposite case: those tokens were spent by the model
call that produced the gated request, on the turn that parked, and were counted
there. Counting them again would bill the resume for the park's model call. So the
id goes into `counted_usage_ids` regardless.

Pinned by `tests/test_client_tool_approval.py::TestResumeDoesNotReplayThePriorTurn`
— `test_an_edited_gated_call_still_reaches_the_client` for the history exclusion,
`test_the_gated_calls_own_usage_is_not_counted_again` for the usage inclusion, and
`test_an_ordinary_turn_still_uses_its_run_id_marker` for the unchanged path.

### The resume payload is validated, not trusted

`start_run` forwards any non-`None` `command.resume` straight into
`Command(resume=...)`, so what comes back from `interrupt()` is client-shaped: a
bare string, a mapping with no `decisions`, or a `decisions` that is not a list.
`_gate_on_review_batch` checks the shape before subscripting it and raises the
same style of `ValueError` it raises for a decision-count mismatch. Every one of
those inputs fails closed either way — the run errors and the checkpoint keeps
its pending write, so the thread can be resumed again — so this is about the
operator getting a failure that names the contract instead of a `KeyError` from
wherever Python happened to complain. Pinned by `TestResumePayloadShape`.

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

1. **Two downgrade reasons**, either of which auto-approves everything, so no
   caller without a human on the other end can park a thread nobody can resume.
   `disable_tool_approval` is the tool-approval counterpart of
   `disable_clarification`, set by `channels/manager.py` for **all** channels
   before the empty-by-default `CHANNEL_RUN_POLICY` lookup. It is the only raw
   key `_approval_disabled` reads, because it is this middleware's own opt-out
   for a client that has no approval surface.

   Everything else goes through `resolve_run_interaction_policy`, the repo's one
   definition of "no human is attached to this run" — the same call
   `ClarificationMiddleware._clarification_disabled` and `sandbox/middleware.py`
   make. That resolver covers `non_interactive` (scheduler, MCP task
   notifications), `interaction_mode` (a GitHub webhook run sets `webhook`) and
   `channel_name`. Reading `non_interactive` directly instead is a bug in two
   directions: a run marked only by `interaction_mode` or `channel_name` would
   park here with nothing able to post `Command(resume=...)`, and since
   `interaction_mode` takes *precedence* over `non_interactive` inside the
   resolver, a raw read can also invert the answer relative to clarification on
   the same run — the model being invited to ask a question while every tool call
   is silently auto-approved. Honouring only the newer key is what left scheduled
   runs parking unresumably. Pinned by
   `tests/test_human_in_the_loop_middleware.py::TestUnattendedRunsShareOneSignal`.
2. **`tool_approval_omit`** carries tool names the human stopped wanting to be
   asked about ("don't ask again"), scoped to one caller's session rather than
   persisted to config. It is the one runtime-only key a client legitimately
   supplies, so the Gateway normalizes its shape and caps its length
   (`MAX_TOOL_APPROVAL_OMIT_ENTRIES`) rather than forwarding it verbatim. It
   must be on `_CONTEXT_CLIENT_RUNTIME_ONLY_KEYS` to reach `runtime.context` at
   all: `merge_run_context_overrides` forwards whitelisted keys only, and
   omitting it is what first shipped the browser's button inert while the TUI's
   — a direct `DeerFlowClient` caller that never crosses the Gateway — worked.
   That set, not `_CONTEXT_RUNTIME_ONLY_KEYS`, and the difference is the whole
   point: keys on the latter are internal-only and `strip_internal_context_keys`
   deletes a client's copy, which for this key would make the browser's button
   inert all over again. Its shape is
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

### An `edit` is checked against the schema the human was shown

The captured `args_schema` is forwarded into the `ReviewConfig` precisely so a
client can render a schema-driven edit form, which makes it the contract the
human was shown — but nothing downstream re-checks the reply. Upstream's
`_process_decision` builds the revised call straight out of `edited_action`, and
a tool declared with a raw-JSON `args_schema` gets no pydantic check at execution
either, so an unvalidated bad edit would simply run. `_check_decision` validates
`edited_action["args"]` against that same schema with `jsonschema`'s
`Draft202012Validator` and raises `ValueError` naming the offending field.

The check is exactly the schema and deliberately nothing stricter, which bounds
what it catches. Against the real captured schema for `bash_tool`:

| Edit | Result |
| --- | --- |
| the original args, resubmitted unchanged | accepted |
| an optional field omitted (`timeout` has a default) | accepted |
| an unknown extra key | **accepted** — see below |
| a missing required field (`command`) | refused |
| a required field set to `null` | refused |

Unknown keys pass because pydantic emits no `additionalProperties: false`, and
adding one here would make approval *stricter* than the ungated path: the same
call with the same extra key executes fine when approval is off, and a human
resubmitting what they were shown could be refused. The tool ignores fields it
does not declare. So this validation is a guard against an edit that is broken
on its face, not a schema-tightening layer. `TestEditIsValidatedAgainstTheArgsSchema`
uses the real captured schema rather than a hand-written one for exactly this
reason — a local schema with `additionalProperties: false` makes an
unknown-field test pass while production accepts that edit — and
`test_the_captured_schema_shape_these_tests_rely_on` pins the shape those
expectations depend on.

Two deliberate asymmetries. A schema the validator cannot walk is **our**
capture's problem, not the human's, so it logs and allows the edit rather than
refusing it — and both the construction and the `iter_errors` walk are guarded,
since an invalid `type` only raises when the validator reaches it. And when no
schema was captured at all the client was editing raw JSON, so there is nothing
to validate against.

`_check_decision` also runs *before* `_process_decision`, not after, because that
upstream method reads `edited_action["name"]` unguarded: a client omitting the key
would get a bare `KeyError` from library code before any check here could describe
the contract. The rename refusal lives in the same place, for the same reason —
`interrupt_on` is name-keyed, so a rename would run a *different* tool under the
approval its own gate never issued, and `rewrite_tool_call_args` rewrites args but
not names, so a rename would also leave the raw payload and content blocks naming
the old tool. Pinned by `TestEditIsValidatedAgainstTheArgsSchema` and
`TestEditShapeIsValidated`.

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
that frame intact. No browser code reads it yet — the web UI downgrades instead,
per the client table above — so this row is the wire contract the approval card
will consume, not a description of a live consumer; the change that builds that
card documents the consuming side in `frontend/src/AGENTS.md`.

### A park is not a finished turn

`interrupt()` exits the graph **normally**: the stream ends cleanly, so the run
worker stages `RunStatus.success` — `RunStatus.interrupted` is only ever set by
the cancellation path, and the worker never inspects `__interrupt__`. A park
therefore reaches the run-history metadata writer looking exactly like a
completed turn.

Writing there would destroy the park. `pending_writes` is not a field of the
checkpoint — the checkpointer keys it by checkpoint id — so
`persist_run_history_metadata`'s `aput`, which parents a *new* latest checkpoint
on the parked one, cannot carry it over. The pending task stays behind on the old
id while the new checkpoint becomes latest, and every subsequent
`GET /threads/{id}` or `/state` read then reports no pending approval even though
the client just saw one on the stream. The thread stays resumable — a
`Command(resume=...)` still finds the write — so what is lost is precisely the
read surface an approval UI depends on.

`persist_run_history_metadata` therefore returns early when the head checkpoint
still carries an `__interrupt__` pending write. Skipping is correct rather than
merely safe: a duration measured on a turn that has not ended is not that turn's
duration, and the run that eventually completes the turn writes its own entry.
Its other caller is a read-through history cache that already treats a skip as
retryable, and no production caller reads the return value.

This is reachable only because tool approval stopped being downgraded for
Gateway resumes: before that no HTTP run could park, so "approve, then hit a
second gated call" could not happen. Pinned by
`tests/test_run_duration_preserves_park.py`, which drives a real compiled graph
through park → approve → second park against an `InMemorySaver`.

`interrupts` is added to a task only when one is pending, so an ordinary
in-flight task keeps the `{id, name}` shape older clients already parse.
`POST /threads/search` keeps `interrupts` empty on purpose: it serves thread
metadata, and filling it would cost one checkpoint load per listed row.
