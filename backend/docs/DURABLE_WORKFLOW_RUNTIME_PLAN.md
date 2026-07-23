# Durable Workflow Runtime Plan

Status: implementation plan
Date: 2026-06-26
Scope: first-priority PR stack for DeerFlow durable workflow runtime, shared identity, workflow events, and runtime adoption

## Relationship To DeerFlow Runtime

This plan is the focused execution track for the Durable Workflow Runtime plane
in DeerFlow core. It should land before the Agent Workflow Definition,
Compiler/Run Binding, Work Module, and WorkBoard tracks depend on it.

The runtime layer is the shared foundation because it gives all later modules a
stable way to answer:

- what external request/message arrived;
- whether it was already accepted;
- which DeerFlow thread/run/checkpoint it bound to;
- who claimed execution;
- whether it is running, waiting, terminal, retryable, or orphaned;
- which lifecycle and run events explain what happened.

## Core Standardization Goals

### Shared Identity Model

Standardize these names before expanding module surface area:

- `workflow_id`: durable frontdoor envelope id for one inbound command/message.
- `workflow_event_id`: append-only lifecycle fact id.
- `workflow_definition_id`: design-time workflow definition id; not owned by
  this runtime plan, but reserved now to avoid name collisions.
- `workflow_definition_version`: immutable design snapshot version/id.
- `workflow_run_id`: execution of a designed workflow; later compiler/run
  binding plane.
- `thread_id`: LangGraph/DeerFlow thread id.
- `run_id`: DeerFlow run id.
- `checkpoint_ns`: LangGraph checkpoint namespace.
- `checkpoint_id`: LangGraph checkpoint ref.
- `step_id`: designed workflow node/step id; reserved for later projection.
- `work_unit_id`: generic task/card/issue id; Work module, not runtime core.
- `external_binding_id`: external object mapping id; Work module or
  deployment-owned integrations.

Runtime core owns `workflow_id` and `workflow_event_id`. It may store refs to
the other ids, but it must not require the modules that own them.

### Status Contracts

Initial workflow statuses:

- `received`: intake persisted, not yet resolved/claimed.
- `bound`: deterministic thread/checkpoint binding resolved.
- `claimed`: worker/process lease acquired.
- `run_created`: DeerFlow run row created.
- `running`: bound run is executing.
- `waiting`: run/workflow is paused for interrupt, human input, external event,
  or safe retry time.
- `succeeded`: terminal success.
- `failed`: terminal failure.
- `cancelled`: terminal cancellation.
- `orphaned`: previous executor is gone and automatic safe resume is not known.
- `ignored`: accepted and intentionally not executed.

These statuses are a public runtime contract. Later modules can project their
own statuses from them, but should not redefine runtime meaning.

### Event Contract

`workflows` is the mutable latest projection. `workflow_events` is the
append-only lifecycle log.

`workflow_events` should record DeerFlow runtime facts such as:

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

It should reference `run_events` by `(thread_id, run_id, run_event_seq)` rather
than copying low-level execution events. Timeline APIs merge workflow lifecycle
facts with `RunEventStore` rows at query time.

### LangGraph Boundary

LangGraph owns:

- graph execution;
- checkpoint state values;
- checkpoint writes and pending writes;
- graph-local memory;
- interrupt/resume mechanics;
- replay from checkpoints.

DeerFlow runtime owns:

- intake identity;
- idempotency;
- source/channel refs;
- deterministic thread/run/checkpoint binding records;
- worker lease and retry metadata;
- startup reconciliation;
- lifecycle events and runtime correlation.

The runtime layer stores refs to LangGraph state, never checkpoint payloads.

## Core Data Model

### `workflows`

Purpose: durable intake envelope and latest runtime projection.

Minimum fields:

- `workflow_id`
- `workflow_kind`
- `source_type`
- `source`
- `external_message_ref`
- `conversation_ref`
- `thread_ref`
- `sender_ref`
- `idempotency_key`
- `thread_id`
- `run_id`
- `checkpoint_ns`
- `checkpoint_id`
- `status`
- `attempt_count`
- `max_attempts`
- `next_attempt_at`
- `lease_owner`
- `lease_expires_at`
- `error`
- `metadata`
- `created_at`
- `updated_at`

Indexes:

- unique idempotency scope, initially `(source_type, source, idempotency_key)`
  when `idempotency_key` is present;
- `(status, next_attempt_at, lease_expires_at)` for claiming/recovery;
- `(thread_id, run_id)`;
- `(source_type, source, conversation_ref)`;
- `updated_at`.

### `workflow_events`

Purpose: append-only lifecycle facts for audit, recovery, and timeline APIs.

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

Indexes:

- unique `(workflow_id, seq)`;
- `(workflow_id, created_at)`;
- `(thread_id, run_id, run_event_seq)`;
- `(event_type, created_at)`.

## Store Contracts

The runtime store should work with in-memory tests, SQLite local dev, and
Postgres production.

Required methods:

- `create_or_get`: idempotent intake.
- `append_event`: append a lifecycle event with monotonic per-workflow seq.
- `get`: fetch workflow projection.
- `list`: filter by status, source, thread, run, and updated time.
- `update_status`: mutate projection and append lifecycle event.
- `bind_runtime`: attach `thread_id`, `run_id`, checkpoint refs.
- `claim_next`: atomically lease eligible workflow.
- `renew_lease`: extend active ownership for long execution.
- `release_for_retry`: clear lease and schedule next attempt.
- `mark_orphaned`: terminal or recoverable orphan projection.
- `timeline`: merge workflow events and run events.

Postgres should use row-level locking and `SKIP LOCKED` for `claim_next`. SQLite
can use a conservative transaction path suitable for local/single-process
development.

## PR Stack

The stack is ordered so later PRs are optional expansions. If review stops at a
given prefix, the runtime should still be useful at that maturity level.

Submit the work as one coherent Durable Workflow Runtime package, but make the
review groups explicit:

- PR 1-5: Core Runtime Package. A normal DeerFlow run has durable workflow
  identity, idempotent intake, lifecycle events, a visible run trace, and
  explicit orphan recovery visibility.
- PR 6-10: Hardening/Scale Package. Binding, channel/dashboard intake,
  waiting/resume, and worker readiness show the production path while remaining
  separable from the first landing target.

For the current open GitHub PRs, #3814 combines workflow store and lifecycle
events, and #3848 is the fifth Core Runtime Package PR for recovery/orphan
reconciliation. If maintainers prefer a finer split, #3814 can be separated
into store and event PRs before final review.

- PR 1-2: schema/store foundation.
- PR 1-3: durable envelope plus lifecycle events.
- PR 1-4: observable Durable Run Trace for operators and users.
- PR 1-5: existing run APIs create and update workflow envelopes.
- PR 1-6: restart/orphan behavior is production-visible.
- PR 1-8: universal API/dashboard/channel frontdoor.
- PR 1-9: durable human-in-the-loop.
- PR 1-10: horizontal worker readiness.

### Community Value Milestone

The first PR stack proposed upstream should not stop at invisible primitives.
It should include enough surface area that a DeerFlow user or operator can see
the benefit during normal chat/run usage:

- every run created through existing run APIs has a `workflow_id`;
- repeated client/channel retries with the same idempotency key do not create a
  duplicate run;
- the workflow can be found from `run_id` or `thread_id`;
- the trace shows intake, run creation, running state, and terminal
  success/failure/cancellation;
- the trace links workflow lifecycle events with the existing run event stream
  without copying LangGraph checkpoint payloads.

This milestone is still runtime-only. It intentionally does not include Work
Units, WorkBoard, PM integrations, visual workflow design, or an external
workflow engine dependency.

### PR 1: Runtime Architecture and Shared Contracts

Scope:

- Add `DURABLE_WORKFLOW_CORE_RFC.md` as the English package RFC/background
  anchor.
- Add this plan.
- Link it from the RFC/frontdoor docs and docs index.
- Align terminology with `DURABLE_WORKFLOW_FRONTDOOR.md`.

Acceptance:

- docs distinguish `workflow_id`, `workflow_definition_id`, and
  `workflow_run_id`;
- docs define initial runtime statuses and event contract;
- no runtime behavior changes.

### PR 2: Workflow Envelope Schema, Store, And Events

Scope:

- Add runtime enums for workflow kind/source/status.
- Add `workflows` ORM model and migration.
- Add `workflow_events` ORM model and migration.
- Add in-memory and SQL store implementations.
- Implement `create_or_get`, `get`, `list`, `update_status`,
  `bind_runtime`, `claim_next`, `release_for_retry`, `append_event`, and
  `list_events`.
- Wire store dependency without changing endpoint behavior.

Acceptance:

- idempotent create returns existing workflow for duplicate key;
- lease claim is atomic under SQL store;
- event seq is monotonic per workflow;
- timeline can include workflow events even before a run exists;
- no run event duplication;
- existing run APIs and channels behave unchanged;
- tests cover memory and SQL store behavior.

### PR 3: Durable Run Trace APIs

Scope:

- Add read-only gateway endpoints for workflow envelopes and run traces.
- Add filters by status, source, thread, run, and updated time.
- Add a timeline endpoint that merges workflow lifecycle facts with existing
  `RunEventStore` rows at query time.
- Add run-to-workflow lookup so existing clients can discover the durable
  workflow for a run.
- Include idempotency/source refs, runtime refs, terminal status, and recovery
  hints in responses.

Acceptance:

- operators can query active, waiting, failed, orphaned, and terminal
  workflows;
- users and developers can inspect a normal chat/run and see the durable trace;
- one workflow timeline correlates workflow lifecycle events with run events;
- endpoint additions do not alter existing run API compatibility.

### PR 4: Run API Compatibility Wrapper and Status Projection

Scope:

- Wrap existing `/runs` and `/threads/{thread_id}/runs` paths with workflow
  intake when enabled.
- Create workflow envelope before `start_run`.
- Bind `thread_id`, `run_id`, and checkpoint refs after run creation.
- Project run lifecycle into workflow lifecycle (`running`, `succeeded`,
  `failed`, `cancelled`) without making LangGraph checkpoint state secondary.
- Preserve existing request/response behavior for clients.

Acceptance:

- old clients can ignore `workflow_id`;
- new clients can find the workflow for a created run;
- duplicate idempotency keys do not create duplicate runs when policy says
  dedupe;
- workflow terminal status matches the bound run terminal status;
- tests cover direct run creation.

### PR 5: Recovery and Reconciliation

Scope:

- Reconcile active workflow envelopes with existing run reconciliation.
- Mark orphaned workflows explicitly when process-local execution was lost.
- Requeue only workflows that are safe by idempotency/source policy.
- Record `lease_expired`, `orphaned`, and `retry_scheduled` events.

Acceptance:

- restart behavior is explicit and queryable;
- no workflow is silently left `running` without an owner;
- automatic retry is conservative and policy-driven.

### PR 6: Deterministic Binding Resolver

Scope:

- Add generic resolver for explicit `thread_id`, external conversation refs,
  checkpoint refs, and active run binding.
- Record ambiguous candidates in metadata.
- Do not use semantic guessing in channel/source-specific code.

Acceptance:

- explicit thread/checkpoint ids win;
- unambiguous channel conversation mappings bind deterministically;
- ambiguous cases are persisted and surfaced, not guessed.

### PR 7: Channel and Dashboard Intake Adoption

Scope:

- Route channel adapters through workflow intake.
- Route dashboard/API chat messages through workflow intake where applicable.
- Normalize source refs and idempotency keys for channels.

Acceptance:

- Slack/Discord/Telegram-style messages produce workflow envelopes;
- channel retries dedupe by stable external event/message ids;
- channel behavior remains compatible for users.

### PR 8: Waiting, Resume, and Human-In-The-Loop Refs

Scope:

- Add generic waiting metadata conventions for LangGraph interrupts and external
  human input.
- Route resume messages through workflow intake.
- Bind resume workflows to `thread_id`, checkpoint refs, and parent workflow
  metadata.

Acceptance:

- interrupted runs surface as `waiting`;
- resume creates/uses a durable workflow envelope;
- LangGraph remains owner of interrupt/resume state.

### PR 9: Worker Pool Readiness

Scope:

- Add lease renewal.
- Add configurable worker identity.
- Add claim loop abstraction behind feature flag or internal API.
- Keep gateway process execution as the default path.

Acceptance:

- Postgres deployments have a clear horizontal worker contract;
- local SQLite/default deployments remain simple;
- no mandatory external workflow engine dependency.

### PR 10: Optional Split Point

If maintainers want exactly ten PRs, split either waiting/resume or worker
readiness into two smaller hardening PRs during final packaging. Do not create a
new conceptual dependency just to fill a number.

## Review Grouping

The safest first code landing target is PR 1-5 as the Core Runtime Package:

- docs and shared contracts;
- `workflows` schema/store;
- idempotent create;
- lifecycle events;
- run/checkpoint binding fields;
- read APIs and timeline projection;
- existing run API compatibility wrapper;
- recovery/orphan reconciliation;
- focused repository, router, and gateway tests.

This is not too small: maintainers can see the end-to-end value during normal
chat/run usage without installing Work Module or WorkBoard.

PR 6-10 should be submitted as the Hardening/Scale Package. It is important for
production confidence, but it can be reviewed after the core package if
maintainers want staged landing.

## Defer Explicitly

Do not include in the runtime-first stack:

- Agent Workflow DSL persistence;
- visual designer UI;
- Work Unit schemas;
- WorkBoard;
- PM connector implementations;
- Restate/Temporal/Hatchet dependencies;
- AICOS-X concepts;
- checkpoint value copies;
- generic deterministic code replay.

These become easier and cleaner after the runtime identity, status, event, and
binding contracts are stable.
