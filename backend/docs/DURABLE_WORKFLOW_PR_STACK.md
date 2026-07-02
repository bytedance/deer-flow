# Durable Workflow PR Stack

Status: working stack
Date: 2026-06-27

This stack is ordered for upstream review. PR 1-5 is the first community-visible
milestone: existing DeerFlow run APIs keep their current behavior, but each run
also has durable workflow identity, idempotency, lifecycle events, and an
inspectable trace.

## Review Principles

- Keep the Durable Workflow Runtime layer generic. Do not introduce AICOS, PM
  tool, visual designer, board, or external-orchestrator concepts into that
  runtime layer.
- Keep module boundaries explicit. Durable Workflow Runtime, Work Module, and
  WorkBoard are separately gated by `modules.*` config and should not require
  each other except for WorkBoard depending on the Work Module API.
- LangGraph remains owner of graph execution, checkpoint state, graph-local
  memory, interrupts, and resume semantics.
- DeerFlow owns intake identity, workflow status projection, idempotency,
  run/checkpoint references, channel/API routing, and runtime observability.
- The optional DeerFlow Work Module may map workflow ids to generic Work Units.
  DeerFlow core should define enough external-ref metadata for PM systems to
  integrate later, but this stack does not implement Jira, ClickUp, Plane,
  Trello, or Lark bindings.

## PR 1: Runtime Architecture And Shared Contracts

Purpose: align vocabulary before schema and API changes.

Scope:

- Add `DURABLE_WORKFLOW_RUNTIME_PLAN.md`.
- Add `DURABLE_WORKFLOW_FRONTDOOR.md`.
- Link both docs from the backend docs index.
- Define shared identity names: `workflow_id`, `workflow_event_id`,
  `thread_id`, `run_id`, `checkpoint_ns`, `checkpoint_id`,
  `workflow_definition_id`, and `workflow_run_id`.
- Define status and event contracts.

Acceptance:

- No runtime behavior changes.
- Docs clearly separate runtime workflow identity from future visual workflow
  definitions and future work unit modules.

Suggested checks:

```bash
git diff --check
```

## PR 2: Workflow Envelope Schema And Store

Purpose: persist the minimal durable frontdoor envelope.

Scope:

- Add runtime workflow enums and `WorkflowStore`.
- Add in-memory workflow store.
- Add SQLAlchemy workflow repository.
- Add `workflows` ORM model and migration.
- Wire gateway dependency so production uses SQL store when a DB session
  factory exists, otherwise memory store.

Acceptance:

- `create_or_get` dedupes by `(source_type, source, idempotency_key)`.
- Store supports `get`, `list`, `bind_runtime`, `update_status`,
  `claim_next`, and `release_for_retry`.
- Existing run APIs still behave the same before wrapper adoption.

Suggested checks:

```bash
cd backend
PYTHONPATH=. PYTHONIOENCODING=utf-8 PYTHONUTF8=1 uv run pytest \
  tests/test_workflow_repository.py \
  tests/test_persistence_bootstrap.py \
  tests/test_persistence_bootstrap_concurrency.py \
  tests/test_persistence_bootstrap_regression.py \
  tests/test_persistence_scaffold.py -q
```

## PR 3: Workflow Events

Purpose: add append-only lifecycle facts for audit and recovery decisions.

Scope:

- Add `workflow_events` ORM model and migration.
- Add `append_event` and `list_events` to workflow stores.
- Keep workflow events separate from `RunEventStore`.
- Ensure migrations are idempotent when legacy `create_all` already created
  tables.

Acceptance:

- Event `seq` is monotonic per workflow.
- Events can exist before a run exists.
- No checkpoint values are copied into workflow event rows.

Suggested checks:

```bash
cd backend
PYTHONPATH=. PYTHONIOENCODING=utf-8 PYTHONUTF8=1 uv run pytest \
  tests/test_workflow_repository.py \
  tests/test_workflows_router.py \
  tests/test_persistence_bootstrap.py \
  tests/test_persistence_bootstrap_concurrency.py \
  tests/test_persistence_bootstrap_regression.py -q
```

## PR 4: Durable Run Trace API And UI

Purpose: make the runtime value visible without requiring WorkBoard, PM
adapters, or an external workflow engine.

Scope:

- Add read-only workflow endpoints:
  - `GET /api/workflows`
  - `GET /api/workflows/{workflow_id}`
  - `GET /api/workflows/{workflow_id}/events`
  - `GET /api/workflows/by-run/{run_id}`
  - `GET /api/workflows/{workflow_id}/timeline`
- Timeline merges workflow lifecycle events and run events at query time.
- Add a compact workspace Trace trigger for the latest run in a chat.

Acceptance:

- A user can open a chat and inspect the latest run trace.
- A developer can find `workflow_id` from `run_id`.
- Timeline includes both workflow events and existing run events.
- Endpoint additions do not change existing run API responses.

Suggested checks:

```bash
cd backend
PYTHONPATH=. PYTHONIOENCODING=utf-8 PYTHONUTF8=1 uv run pytest \
  tests/test_workflows_router.py \
  tests/test_gateway_services.py -q

cd ../frontend
CI=true pnpm run check
```

## PR 5: Run API Wrapper And Status Projection

Purpose: route existing run creation through workflow intake while preserving
client compatibility.

Scope:

- Wrap `/api/runs/*` and `/api/threads/{thread_id}/runs*` creation paths.
- Create a workflow envelope before run creation.
- Bind `thread_id`, `run_id`, `checkpoint_ns`, and `checkpoint_id`.
- Project run lifecycle to workflow status:
  - `running`
  - `succeeded`
  - `failed`
  - `cancelled`
- Append lifecycle events:
  - `workflow.received`
  - `workflow.deduped`
  - `workflow.run_created`
  - `workflow.run_started`
  - `workflow.succeeded`
  - `workflow.failed`
  - `workflow.cancelled`

Acceptance:

- Old clients can ignore workflows entirely.
- Duplicate idempotency keys do not create duplicate bound runs.
- Workflow terminal status matches the bound run terminal status.
- Trace UI shows terminal status on new runs.

Suggested checks:

```bash
cd backend
PYTHONPATH=. PYTHONIOENCODING=utf-8 PYTHONUTF8=1 uv run pytest tests/ -q
PYTHONPATH=. PYTHONIOENCODING=utf-8 PYTHONUTF8=1 uv run ruff check .
PYTHONPATH=. PYTHONIOENCODING=utf-8 PYTHONUTF8=1 uv run ruff format --check .

cd ../frontend
CI=true pnpm run check
NEXT_PUBLIC_BACKEND_BASE_URL=http://127.0.0.1:18081 \
NEXT_PUBLIC_LANGGRAPH_BASE_URL=http://127.0.0.1:18081/api \
DEER_FLOW_INTERNAL_GATEWAY_BASE_URL=http://127.0.0.1:18081 \
DEER_FLOW_TRUSTED_ORIGINS=http://127.0.0.1:13001,http://localhost:13001 \
DEER_FLOW_AUTH_DISABLED=1 \
pnpm exec next build
```

## Post-Milestone PRs

These should come after PR 1-5, so the foundation is already visible and
testable.

### PR 6: Recovery And Orphan Reconciliation

Status: implemented in `codex/deerflow-durable-recovery`.

- Reconcile active workflows with existing run reconciliation at gateway
  startup.
- Mark `running` / `run_created` workflows as `orphaned` when process-local
  execution was lost.
- Add recovery hints in timeline responses.

### PR 7: Deterministic Binding Resolver

Status: implemented in `codex/deerflow-durable-binding-resolver`.

- Normalize explicit thread/run/checkpoint/source bindings.
- Persist ambiguous candidates instead of guessing.
- Give channel adapters a generic binding contract.

### PR 8: Channel And Dashboard Intake Adoption

Status: implemented in `codex/deerflow-durable-channel-intake`.

- Route Slack/Discord/Telegram-style adapters through workflow intake.
- Use stable external message ids as idempotency keys.
- Keep channel UX compatible.

### PR 9: Durable Waiting And Resume Refs

Status: implemented in `codex/deerflow-durable-waiting-resume`.

- Represent LangGraph interrupt waits as durable workflow state.
- Route resume commands through workflow intake.
- Keep actual interrupt payloads in LangGraph checkpoint state.

### PR 10: Worker Pool Readiness

Status: implemented in `codex/deerflow-workflow-worker-readiness`.

- Add worker identity and lease renewal.
- Prepare the store contract for future worker processes without enabling a
  separate worker pool by default.
- Keep gateway process execution as the default mode.

## Next Module Tracks

The following tracks should remain separate from the runtime PRs:

- Work Module: generic Work Unit records with external-ref fields that make PM
  adapters possible later.
- WorkBoard: built-in board UI for deployments without a PM tool.
- Workflow Designer: visual workflow definition authoring and versioning.
- Optional orchestrator adapters: Restate, Temporal, Hatchet integration
  examples, not hard dependencies.

## Module PRs After Runtime

These PRs depend on the runtime identity/event foundation but should not be
required for a minimal durable runtime deployment.

### PR 11: Work Module Schema And API

- Add `DEERFLOW_WORK_MODULE.md`.
- Add `work_units` and `work_events` schema/migration.
- Add memory and SQL stores.
- Add `/api/work-units` CRUD and event list endpoints.
- Allow optional links to `workflow_id`, `thread_id`, and `run_id`.

### PR 12: WorkBoard MVP

- Add `/workspace/work`.
- Show Trello-style columns over `work_units.status`.
- Create local work units.
- Show runtime-driven status projection; local human-created work starts in
  `backlog`.
- Link cards to chat threads and workflow traces when refs exist.

### PR 13: External PM Binding Contract

- Define adapter mapping for Jira/Trello/ClickUp/Plane/Lark-style work objects.
- Add external ref/url/source conventions.
- Keep credentials, webhooks, sync cursors, and conflict policy in adapters.
- Do not implement concrete PM connectors in the core stack.

### PR 14: Work Gates And Criteria

- Add acceptance criteria and lightweight human gates.
- Link gates to runtime `waiting` workflows where appropriate.
- Keep LangGraph interrupt payloads in LangGraph checkpoint state.

### PR 15: Agent Workflow Definition Plane

- Add Agent Workflow DSL schema/validation.
- Add definition/version persistence.
- Add visual designer under a feature flag.
- Compile from DeerFlow DSL to LangGraph/runtime plans, not from editor JSON.
