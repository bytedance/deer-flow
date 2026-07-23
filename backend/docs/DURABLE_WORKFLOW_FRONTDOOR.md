# Durable Workflow Runtime Frontdoor

Status: architecture decision draft
Date: 2026-06-26
Scope: DeerFlow backend gateway, runtime, persistence, and channel adapters

## Decision

DeerFlow should add a native Durable Workflow Runtime Layer in core for inbound
messages, run requests, dashboard requests, and delegated agent tasks that may
invoke an agent. The first core surface should be a DeerFlow-owned workflow
envelope and ledger, not a hard dependency on AICOS, Restate, Temporal, Hatchet,
or any product-specific task model.

The frontdoor provides stable intake identity, idempotency, routing/binding
metadata, run/checkpoint references, and queryable workflow status. LangGraph
continues to own graph execution state, checkpoint values, graph-local memory,
interrupt semantics, and replay from checkpoints. DeerFlow owns generic intake,
run orchestration, channel routing, and event correlation.

External workflow engines such as Restate, Temporal, or Hatchet must not be a
required DeerFlow core dependency. The runtime layer should keep clean identity,
lifecycle, refs, and event boundaries so users are not locked out of those
systems when their deployments need them.

Scalable DeerFlow deployments should add a small native workflow leasing layer
to this envelope. Leasing gives DeerFlow a horizontal worker contract without
claiming full durable code replay: a worker can atomically claim an eligible
workflow, bind it to a LangGraph thread/run, renew or finish the lease, and let
another worker recover it when the lease expires.

For deployments that need durable work management, this frontdoor can later be
paired with an optional DeerFlow Work Module. The frontdoor remains the generic
intake and runtime-dispatch layer; the Work module would add reusable Work Unit
records, acceptance criteria, gates, artifact references, review metadata, and
external refs that make deployment-owned PM integrations easier to build.

## Current Architecture Summary

DeerFlow already has the foundation for durable agent runtime behavior:

- LangGraph checkpointer persists thread-scoped graph state by `thread_id`,
  `checkpoint_ns`, and `checkpoint_id`.
- LangGraph store persists runtime/application memory outside graph state.
- `RunManager` creates process-local `RunRecord` objects and persists run
  metadata through `RunStore`.
- `RunRepository` stores `run_id`, `thread_id`, status, model, token usage,
  first/last messages, and run kwargs/metadata.
- `RunEventStore` stores an ordered event stream keyed by
  `(thread_id, run_id, seq)`.
- `run_agent()` executes `agent.astream(...)` in an `asyncio.Task`, writes run
  status transitions, publishes stream bridge events, and flushes `RunJournal`
  events.
- Gateway endpoints (`/runs`, `/threads/{thread_id}/runs`) call `start_run()`
  directly.
- Channel adapters normalize platform events into `InboundMessage`; the
  channel manager resolves/creates a DeerFlow thread, then calls
  `client.runs.wait()` or `client.runs.stream()`.

The important current limitation is that the executing run task is process
local. A persisted `pending` or `running` row does not imply an executor still
exists after gateway restart. Startup reconciliation explicitly marks orphaned
active runs as `error` for SQLite-backed deployments instead of pretending they
are resumable.

## Research Notes

LangGraph persistence separates thread-scoped checkpointers from cross-thread
stores. Checkpointers are the right owner for graph state snapshots,
conversation continuity, human-in-the-loop, time travel, and fault tolerance.
They require a stable `thread_id` and can reference concrete checkpoints by
`checkpoint_id`.

LangGraph interrupts pause graph execution, persist graph state through the
checkpointer, and resume by invoking the same thread with `Command(resume=...)`.
Interrupt side effects before the interrupt must be idempotent because the
node can restart when resumed.

Temporal and Restate solve a different boundary: durable orchestration replay.
Temporal workflows must be deterministic and push non-deterministic operations
such as API/LLM calls into activities. Restate journals steps, side effects,
timers, and service calls so handlers can replay without duplicating completed
effects. These are valuable external systems, but making either mandatory would
raise DeerFlow's deployment bar and entangle the core runtime with a specific
execution engine.

Hatchet is useful as a scale and worker model reference. Its durable execution
docs separate ordinary task execution from durable tasks that checkpoint when
they wait or spawn children. Its DAG model persists each completed task result
so retries can avoid re-running succeeded parts, and its platform emphasizes
worker slots, concurrency, priority, retries, and observability. DeerFlow should
borrow those operational primitives at the workflow-envelope layer, while still
leaving graph execution and checkpoint state inside LangGraph.

OpenAI Agents SDK tracing and handoffs are useful compatibility concepts:
trace/group IDs and spans map naturally to workflow/run/event correlation,
while handoffs show how multi-agent delegation can remain tool-like and
runtime-owned. They do not replace DeerFlow's need for an intake ledger.

Dust-style platforms are useful as product pattern evidence: many surfaces
(web, Slack, Teams, API, browser extension) can call the same agent layer with
selected knowledge sources and tools. DeerFlow should generalize that as
surface-agnostic intake and routing, not as a Dust-specific feature.

References:

- https://docs.langchain.com/oss/python/langgraph/persistence
- https://docs.langchain.com/oss/python/langgraph/checkpointers
- https://docs.langchain.com/oss/python/langgraph/interrupts
- https://docs.temporal.io/workflow-definition
- https://docs.restate.dev/foundations/key-concepts
- https://docs.hatchet.run/v1/durable-execution
- https://docs.hatchet.run/v1/durable-tasks
- https://docs.hatchet.run/v1/directed-acyclic-graphs
- https://openai.github.io/openai-agents-python/tracing/
- https://openai.github.io/openai-agents-python/handoffs/
- https://docs.dust.tt/docs/intro

## Schema Lessons From Durable Workflow Systems

The schema should borrow the smallest durable ideas from LangGraph, Restate,
Temporal, and Hatchet without turning DeerFlow into another workflow engine.

From LangGraph:

- use `thread_id`, `checkpoint_ns`, and `checkpoint_id` as refs into graph
  state;
- never copy checkpoint `values` into DeerFlow workflow rows;
- remember that a checkpoint snapshot already has `metadata`, `created_at`,
  `parent_config`, `tasks`, and `next` for graph-local replay and inspection;
- rely on LangGraph checkpoint writes/pending writes for graph node recovery
  inside a super-step;
- use interrupts/resume as the primary graph-local human-in-the-loop primitive.

From Restate:

- keep a durable identity before handler execution starts;
- dedupe repeated submissions by identity/idempotency key;
- distinguish retryable errors from terminal errors;
- model external waits as durable workflow state, not as an in-memory future;
- keep boundaries clean enough that deployments can integrate Restate later if
  they need durable handler execution outside DeerFlow core.

From Temporal:

- separate stable `workflow_id` from per-attempt/per-run execution identity;
- use append-only event history concepts for observability and recovery
  decisions;
- keep workers stateless enough that another worker can pick up eligible work;
- treat calls to LLMs, databases, channels, and PM tools as external effects
  that require idempotency or a durable result record;
- avoid putting critical execution data only in searchable/memo metadata.

From Hatchet:

- expose worker-facing lease/claim/concurrency primitives without requiring
  full deterministic replay in core;
- make waits and child work visible as durable state;
- persist completed step/task refs so retries do not need to guess what already
  happened;
- keep DAG/workflow-builder concerns separate from the core runtime layer.

The practical result is a small DeerFlow schema made of a mutable workflow
projection plus append-only lifecycle facts. LangGraph remains the durable graph
runtime. DeerFlow still has a native frontdoor that every deployment can run,
while users remain free to integrate external workflow engines when needed.

## Boundary Rules

LangGraph owns:

- graph execution;
- checkpoint values and checkpoint writes;
- graph-local memory and interrupt/resume mechanics;
- replay from a checkpoint.

DeerFlow core owns:

- generic workflow intake identity;
- source/channel metadata;
- deterministic conversation/thread binding records;
- run creation and cancellation orchestration;
- workflow-to-run/checkpoint references;
- workflow event projection over `RunEventStore`;
- restart reconciliation and orphan status visibility.

Integrations own:

- domain-specific work semantics;
- task/goal/work-unit lifecycle;
- approval policies and business gates;
- evidence/artifact acceptance rules;
- semantic completion beyond "the DeerFlow run ended".

DeerFlow runtime core must not know integration-specific names such as Gate,
Evidence, Review, Runtime Invocation, AICOS, OpenClaw, Restate, or Temporal.
It also must not require the Work Module to run durable workflows.

The optional Work Module intentionally sits above DeerFlow runtime core. It
provides generic community primitives such as Work Units and Work Gates, plus
external refs that make it easier for teams to connect Jira issues, Trello
cards, ClickUp tasks, Plane issues, Lark tasks/docs, internal systems, or other
work records without making those integrations DeerFlow core.

## Core Primitive: Workflow Envelope

The workflow envelope is a generic record for one inbound message or command
that may cause an agent invocation.

Minimum fields:

- `workflow_id`: DeerFlow-generated durable identity.
- `workflow_kind`: `message`, `command`, `resume`, `handoff`, or `other`.
- `source_type`: `api`, `dashboard`, `channel`, `agent_session`, or `other`.
- `source`: provider/surface name such as `slack`, `telegram`, `dashboard`, or
  `api`.
- `external_message_ref`: stable external message/event id when one exists.
- `conversation_ref`: external conversation/session/channel id.
- `thread_ref`: external topic/thread/reply id.
- `sender_ref`: external user/account/bot id.
- `thread_id`: DeerFlow LangGraph thread id, once resolved.
- `run_id`: DeerFlow run id, once created.
- `checkpoint_ns`: checkpoint namespace, usually `""` for the root graph.
- `checkpoint_id`: checkpoint ref when the workflow targets or observes one.
- `idempotency_key`: caller or adapter supplied stable key.
- `status`: `received`, `bound`, `claimed`, `run_created`, `running`, `waiting`,
  `succeeded`, `failed`, `cancelled`, `orphaned`, or `ignored`.
- `attempt_count`: how many times DeerFlow has claimed or attempted the
  workflow.
- `max_attempts`: retry ceiling for safe retry policies.
- `next_attempt_at`: earliest time the workflow can be claimed again.
- `lease_owner`: worker/process id that currently owns execution.
- `lease_expires_at`: time after which another worker may recover/claim it.
- `error`: short error summary.
- `metadata`: JSON for source/runtime extension data.
- `created_at`, `updated_at`.

The envelope stores refs and summaries. It must not copy LangGraph checkpoint
state values or large raw transcripts.

## Core Primitive: Workflow Event

The workflow row is the latest projection. A separate append-only event table
should record workflow lifecycle facts that are useful for audit, recovery, and
UI timelines.

Minimum fields:

- `workflow_event_id`
- `workflow_id`
- `seq`
- `event_type`
- `source`
- `thread_id`
- `run_id`
- `checkpoint_ns`
- `checkpoint_id`
- `run_event_seq`
- `idempotency_key`
- `payload_summary`
- `metadata`
- `created_at`

Suggested event types:

- `received`
- `deduped`
- `bound`
- `claimed`
- `run_created`
- `run_started`
- `waiting`
- `resumed`
- `retry_scheduled`
- `lease_expired`
- `orphaned`
- `succeeded`
- `failed`
- `cancelled`
- `ignored`

This table is not a copy of `RunEventStore`. It records DeerFlow workflow facts
and points at run event sequence numbers where graph execution details already
exist. UI timelines can merge workflow events and run events at query time.

## Durable Runtime Schema

The first scalable schema should be intentionally small:

```text
workflows
  durable intake identity
  source refs and idempotency key
  current status projection
  worker lease and retry metadata
  LangGraph thread/checkpoint refs
  DeerFlow run refs
  compact error/metadata

workflow_events
  append-only workflow lifecycle facts
  refs to run_events, checkpoints, and external ids
  compact payload summaries

run_events
  existing DeerFlow execution stream

LangGraph checkpoints/checkpoint_writes/store
  existing graph state and graph-local memory
```

Do not add a `workflow_steps` table in the first native layer. Step-level
durability is already owned by LangGraph for graph nodes and can later be owned
by an external workflow engine in deployments that need deterministic code
replay beyond LangGraph checkpoints.

Do not add a separate `workflow_runtime_bindings` table until DeerFlow needs
one workflow to fan out into multiple runs or runtimes. The first model can bind
the current `thread_id`, `run_id`, and checkpoint refs directly on `workflows`,
with richer execution attempts represented later by the optional Work module's
`runtime_invocations`.

Human waits can begin as `status = waiting` plus checkpoint/interrupt metadata.
If this becomes too overloaded, add a focused `workflow_waits` or
`workflow_signals` table later with `wait_id`, `workflow_id`, `wait_type`,
`status`, `resume_id`, `expires_at`, and `metadata`.

## Deterministic Binding Resolver

Routing should be deterministic before the agent is invoked:

1. Respect explicit request fields (`thread_id`, `checkpoint_id`, selected
   assistant/agent, explicit external refs).
2. Resolve channel conversation mappings using existing channel connection and
   conversation stores.
3. Detect explicit references in message text only when their syntax is
   unambiguous and generic, such as a DeerFlow thread/run/workflow id.
4. Bind to an active thread/run only when the source conversation and binding
   rules make that deterministic.
5. If multiple valid candidates exist, persist the candidates in workflow
   metadata and pass the ambiguity to the agent or human flow. Do not guess in
   channel/source-specific code.

This resolver is intentionally not a semantic classifier. Semantic intent
belongs in the agent or integration layer.

## Scalable Execution Model

The native DeerFlow layer should be a durable intake and dispatch ledger, not a
second graph engine. The scalable path is:

```text
surface/API/channel
  -> workflow intake row (idempotent)
  -> deterministic binding resolver
  -> workflow lease claim
  -> LangGraph run creation
  -> LangGraph checkpointer/store/run_events
  -> workflow status projection
```

Core primitives needed for scale:

- `create_or_get`: idempotent intake.
- `claim_next`: atomically lease an eligible workflow for one worker.
- `bind_runtime`: attach `thread_id`, `run_id`, and checkpoint refs after run
  creation.
- `update_status`: complete, fail, wait, cancel, or orphan the workflow.
- `release_for_retry`: clear a lease, increment/reuse retry metadata, and set
  `next_attempt_at`.
- `recover_expired_leases`: mark or requeue workflows whose lease owner died.

The first implementation can keep run execution in the gateway process. A later
worker pool can use the same store API to claim workflows from Postgres without
changing public intake semantics.

This design intentionally does not provide Temporal/Restate-style deterministic
code replay in core. DeerFlow should replay at three safer boundaries instead:

1. API/channel retries dedupe at `workflow.idempotency_key`.
2. Workflow dispatch retries re-enter before LangGraph run creation, or after a
   known terminal/orphaned run state.
3. LangGraph graph resume uses `thread_id` and checkpoint/interrupt refs.

Any side effect outside those boundaries must be idempotent or pushed into a
tool/runtime layer that records its own durable result.

## Runtime Binding

Workflow rows bind to DeerFlow runtime refs:

```text
workflow_id
  -> thread_id
  -> run_id
  -> checkpoint_ns/checkpoint_id refs
  -> run_events(thread_id, run_id, seq)
```

Run events remain the source event stream for graph execution observations.
Workflow timeline APIs should project from workflow status changes plus
`RunEventStore` rows. The projection should include links/correlation, not
duplicate every run event into a second canonical stream.

## Recovery Semantics

The initial native layer does not make process-local `asyncio.Task` execution
durable across gateway restarts.

On startup:

- orphaned `pending`/`running` runs remain explicitly marked as `error` under
  current run reconciliation;
- workflows bound to those runs should be marked `orphaned` or `failed` with a
  recovery hint;
- workflows with expired leases and no run can be requeued when their
  idempotency key and source policy make retry safe;
- workflows with expired leases and an active/local run should keep the run as
  source of truth until the run reaches a terminal state;
- workflows that were only `received` or `bound` before a run was created can
  be retried only when the idempotency key, input refs, and source policy make
  retry safe;
- retry/resume policies must be explicit per workflow kind/source.

Deployments that require stronger execution replay can integrate external
workflow engines around the same DeerFlow identity, lifecycle, refs, and event
boundaries.

## Human-In-The-Loop

LangGraph interrupts should remain the primary graph-local HITL primitive.
DeerFlow workflow records should add:

- a durable `waiting` status for workflows whose run reached an interrupt or
  requires user input;
- references to the relevant `thread_id`, `run_id`, and checkpoint config;
- a generic pending-input record or metadata block that stores prompt summary,
  interrupt id(s), source, and resume route;
- `Command(resume=...)` intake through the same workflow frontdoor.

The human decision semantics remain outside DeerFlow unless they are generic
approval/resume mechanics.

## Observability

DeerFlow should expose workflow observability without requiring an integration:

- list workflows by status, source, thread, run, and updated time;
- get one workflow envelope;
- get workflow timeline projected from workflow lifecycle plus run events;
- show idempotency and external refs;
- surface orphan/retry/recovery hints;
- correlate workflow rows to run rows and checkpoint refs.

## PR Stack

Detailed implementation order lives in
[Durable Workflow Runtime Plan](DURABLE_WORKFLOW_RUNTIME_PLAN.md). The stack is
ordered so that cutting later PRs still leaves a useful durable runtime prefix.

1. Runtime architecture and shared contracts.
2. Workflow envelope schema/store/idempotency/lease tests.
3. Workflow events append-only lifecycle log.
4. Runtime read APIs and observability.
5. Existing run endpoint compatibility wrapper.
6. Recovery/reconciliation for orphaned workflows/runs.
7. Deterministic binding resolver.
8. Channel/dashboard intake adoption.
9. Waiting, resume, and human-in-the-loop refs.
10. Worker pool readiness.

## Review Grouping

Submit the implementation as one coherent durable runtime package with two
explicit review groups:

- PR 1-5: Core Runtime Package. Contracts, store, events, read APIs/trace, and
  run endpoint compatibility wrappers, plus recovery/orphan reconciliation.
- PR 6-10: Hardening/Scale Package. Deterministic binding, channel/dashboard
  intake, waiting/resume refs, and worker readiness.

The code stays split into reviewable PRs. The submit narrative should show the
end-to-end native Durable Workflow Runtime Layer so maintainers can evaluate the
core value without requiring Work Module, WorkBoard, PM connectors, or external
workflow engines.
