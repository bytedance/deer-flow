# DeerFlow Scheduled Tasks MVP Design

**Date**: 2026-07-01
**Status**: Approved for implementation
**Scope**: First-class scheduled-task management for DeerFlow web workspace

---

## Problem Statement

DeerFlow main does not ship a real scheduled-task product surface today. The repository already has internal timers, worker pools, and run persistence, but users cannot create, inspect, pause, resume, trigger, or delete durable background tasks from the product.

This creates three concrete problems:

1. Users cannot automate recurring DeerFlow work such as daily summaries, periodic follow-ups, or recurring repo triage from the normal workspace.
2. Existing cron-related PRs prove demand, but they either cut scope too broadly or start from the wrong interaction surface, which makes them hard to merge and harder to operate safely.
3. Without a management surface, any future chat-created schedule would be operationally unsafe because users would have no first-class place to inspect or stop unattended jobs.

The first implementation must solve the operational and product-control problem before natural-language schedule creation.

## Solution Summary

Build a scheduled-task MVP with these hard boundaries:

1. **Durable backend resource**: add a `scheduled_task` resource with DB-backed persistence and DB-backed task-run history.
2. **Shared execution path**: scheduled executions must launch through the existing DeerFlow run lifecycle, not a parallel agent path.
3. **Workspace management page**: add a first-class page at `/workspace/scheduled-tasks` for list/detail/create/edit/pause/resume/trigger/delete.
4. **Execution context mode is explicit**: every task chooses whether runs reuse an existing thread or create a fresh thread per occurrence.
5. **Minimal schedule surface**: MVP supports `once` and `cron`, but not `interval`.
6. **Opt-in runtime gate**: background scheduling remains disabled by default and requires explicit config enablement.

## Explicit Non-Goals

The MVP intentionally does **not** include:

1. Conversation-created schedules or a `schedule_task` tool.
2. Text-only notification jobs.
3. Channel, IM, or GitHub dispatch targets.
4. Goal-backed scheduled work.
5. Retry/dead-letter orchestration.
6. Distributed leader election beyond a single enabled scheduler instance with DB lease claims.
7. Intervals shorter than 60 seconds for user-created tasks.

These exclusions are not optional polish cuts. They are what keeps the first PR reviewable.

## Chosen Architecture

### Why this shape

This MVP combines the right parts of prior DeerFlow cron attempts without inheriting their problems:

1. Keep the **execution discipline** from the narrower backend MVPs: scheduler decides *when* to run, existing run services decide *how* to run.
2. Keep the **durable task identity + task history** shape from broader implementations.
3. Put **management UI before chat-created scheduling**, because users need a reliable control plane before background automation can be created from conversation.

### Resource Model

The MVP introduces two durable entities:

1. `scheduled_tasks`
2. `scheduled_task_runs`

`scheduled_tasks` is the durable trigger definition. `scheduled_task_runs` is the execution ledger per occurrence.

This keeps schedule identity separate from DeerFlow `runs`, which already model one concrete execution attempt.

## User Stories

1. As a DeerFlow user, I want to create a one-time task that can run in a fresh thread, so periodic automation does not silently accumulate old context.
2. As a DeerFlow user, I want to create a recurring cron task that can either reuse a thread or create a fresh thread per run, so I can choose between continuity and isolation explicitly.
3. As a DeerFlow user, I want to see next run time, last run result, and last error at a glance, so I know whether automation is healthy.
4. As a DeerFlow user, I want to pause and resume a task, so I can stop automation without deleting configuration.
5. As a DeerFlow user, I want to trigger a task manually, so I can test or re-run it on demand.
6. As a DeerFlow user, I want to inspect task run history, so I can audit what happened.
7. As a DeerFlow user, I want tasks to be owner-scoped, so no other user can list or mutate my automations.
8. As a maintainer, I want scheduler execution to reuse existing run-launch code, so scheduled runs do not become a second runtime stack.

## MVP Product Shape

### Supported Task Kinds

Only one execution kind is supported in MVP:

- `task_type = "agent"`
- `dispatch_type = "thread"`

That means every scheduled task is defined as:

- context mode
- optional target thread id
- title
- prompt override
- schedule definition
- runtime policy

When it fires, DeerFlow launches a normal run, but the execution thread is selected by `context_mode`.

These are fixed MVP semantics, not user-editable API fields and not persisted schema columns. The first PR must behave as if every task implicitly carries those values, without prematurely generalizing the contract.

### Supported Schedule Kinds

The user-facing MVP supports:

1. `once`
2. `cron`

The MVP does **not** support `interval` because:

1. it adds another schedule parser path,
2. it enlarges frontend validation,
3. it increases edge-case surface around cadence drift and minimum interval enforcement,
4. it is not required to prove the scheduler architecture.

If later added, `interval` can be layered on the same resource model.

### Execution Context Rule

The MVP supports two execution-context modes:

1. `fresh_thread_per_run` — default. Each scheduled occurrence creates a fresh DeerFlow thread.
2. `reuse_thread` — optional. Each scheduled occurrence reuses an existing thread.

This is deliberate:

1. recurring digests, summaries, and automation jobs should not silently accumulate context forever;
2. follow-up and reminder use cases still need an explicit reuse mode;
3. the scheduler definition stays separate from the execution thread used by each occurrence.

## Backend Design

### Persistence Layout

Add harness-owned persistence packages:

- `backend/packages/harness/deerflow/persistence/scheduled_tasks/`
- `backend/packages/harness/deerflow/persistence/scheduled_task_runs/`

Add ORM registration in:

- `backend/packages/harness/deerflow/persistence/models/__init__.py`

Add Alembic migration under:

- `backend/packages/harness/deerflow/persistence/migrations/versions/`

### `scheduled_tasks` schema

Fields:

- `id`: string primary key
- `user_id`: owner user id, indexed
- `thread_id`: nullable target thread id, indexed
- `context_mode`: `fresh_thread_per_run | reuse_thread`
- `assistant_id`: nullable assistant id snapshot
- `title`: user-visible task title
- `prompt`: explicit prompt to send when the task runs
- `schedule_type`: `once | cron`
- `schedule_spec`: JSON payload
- `timezone`: IANA timezone
- `status`: `enabled | paused | running | completed | failed | cancelled`
- `overlap_policy`: fixed to `skip` in MVP, still persisted explicitly
- `misfire_policy`: fixed to `run_once` in MVP, still persisted explicitly
- `next_run_at`: UTC timestamp, indexed
- `last_run_at`: nullable UTC timestamp
- `last_run_id`: nullable DeerFlow run id
- `last_thread_id`: nullable DeerFlow thread id from the latest execution
- `last_error`: nullable text
- `lease_owner`: nullable string
- `lease_expires_at`: nullable UTC timestamp
- `run_count`: integer
- `max_runs`: nullable integer
- `created_at`
- `updated_at`

Not included in MVP schema:

- `dispatch_type`
- `dispatch_target`
- `task_type`
- `sandbox_profile`
- `trust_policy`
- `credential_scope`

Reason: those are real future needs, but introducing dormant columns now weakens the first implementation and invites half-implemented policy behavior. The first PR should store only what it truly enforces.

### `scheduled_task_runs` schema

Fields:

- `id`: string primary key
- `task_id`: foreign-key-like indexed link to `scheduled_tasks.id`
- `thread_id`: indexed for efficient thread-level lookup
- `run_id`: nullable DeerFlow run id
- `scheduled_for`: UTC timestamp
- `trigger`: `scheduled | manual`
- `status`: `queued | running | success | failed | skipped`
- `error`: nullable text
- `started_at`: nullable UTC timestamp
- `finished_at`: nullable UTC timestamp
- `created_at`

This run ledger is distinct from DeerFlow `runs` because:

1. a scheduled occurrence may fail before a DeerFlow run is created,
2. an overlap skip still deserves audit visibility,
3. manual and scheduled triggers need explicit occurrence records.

### Repository APIs

Create two repositories:

1. `ScheduledTaskRepository`
2. `ScheduledTaskRunRepository`

Required repository behavior:

- create/get/list/update/delete tasks
- owner-scoped search
- claim due tasks atomically
- update lease / clear lease
- record status transitions
- insert run history rows
- list task run history

Atomic due-claim API must operate in one DB transaction:

- find due enabled tasks
- skip tasks with live unexpired lease
- set `lease_owner`, `lease_expires_at`, and temporary `status="running"`
- return claimed rows

The scheduler service must not implement claim logic in Python-only in-memory filters.

## Scheduler Runtime Design

### Location

Runtime service lives under:

- `backend/app/scheduler/`

Reason: it needs app-layer dependencies and shared run-launch services. Harness persistence remains app-agnostic.

### Lifecycle

The scheduler starts during FastAPI lifespan only when config enables it.

Suggested config section:

```yaml
scheduler:
  enabled: false
  poll_interval_seconds: 5
  lease_seconds: 120
  max_concurrent_runs: 3
  min_interval_seconds: 60
```

There is no separate `leader` toggle in MVP. The DB lease is the operational guard. If deployments later require multi-instance topology, a leader dimension can be added in hardening.

### Execution flow

For each poll cycle:

1. fetch up to `max_concurrent_runs` due tasks via repository claim,
2. for each claimed task:
   - create `scheduled_task_runs` row with `status=queued`,
   - compute and persist the next schedule before or immediately after launch,
   - dispatch a normal DeerFlow run through shared run-launch helper,
   - persist `last_run_id`, `last_run_at`, `run_count`, task-run status, and error fields,
   - release lease.

### Shared run-launch helper

MVP must extract or reuse a non-router helper based on existing logic in:

- [backend/app/gateway/services.py](/Users/nowcoder/Desktop/auto-code-work/deer-flow/.worktrees/scheduled-tasks-mvp/backend/app/gateway/services.py)
- [backend/app/gateway/routers/thread_runs.py](/Users/nowcoder/Desktop/auto-code-work/deer-flow/.worktrees/scheduled-tasks-mvp/backend/app/gateway/routers/thread_runs.py)

Required property:

- manual API trigger and background scheduler trigger both call the same launch helper.

The helper takes:

- target thread id
- target assistant id
- prompt content
- authenticated owner context
- origin metadata indicating `scheduled_task_id` and `scheduled_trigger`

### Overlap semantics

MVP uses one fixed overlap rule:

- if the target thread already has a pending/running run, record the occurrence as `skipped`, update `next_run_at`, and do not launch another run.

This is intentionally narrower than exposing multiple overlap policies in the first PR.

### Misfire semantics

MVP uses one fixed misfire rule:

- `run_once`

If the scheduler was down and multiple occurrences were missed, only the latest eligible missed occurrence runs when the scheduler comes back.

Reason:

1. avoids backlog explosion,
2. avoids unreviewed catch-up storms,
3. keeps first implementation deterministic.

### One-time task completion

For `once` tasks:

- successful dispatch marks task `completed`
- dispatch failure marks task `failed`
- task remains visible and queryable from UI/history after completion or failure

MVP uses soft retention, not destructive deletion.

### Cron semantics

Cron rules:

1. accept exactly 5 fields
2. reject 6-field cron with seconds
3. store explicit IANA timezone
4. compute `next_run_at` in UTC
5. normalize weekday semantics consistently and test them explicitly

The implementation must not silently depend on an ambiguous day-of-week interpretation.

## API Design

Add REST routes under `/api/scheduled-tasks`.

### Routes

- `GET /api/scheduled-tasks`
- `POST /api/scheduled-tasks`
- `GET /api/scheduled-tasks/{task_id}`
- `PATCH /api/scheduled-tasks/{task_id}`
- `POST /api/scheduled-tasks/{task_id}/pause`
- `POST /api/scheduled-tasks/{task_id}/resume`
- `POST /api/scheduled-tasks/{task_id}/trigger`
- `DELETE /api/scheduled-tasks/{task_id}`
- `GET /api/scheduled-tasks/{task_id}/runs`
- `GET /api/threads/{thread_id}/scheduled-tasks`

There is intentionally **no** dispatch-target discovery endpoint in MVP because the only target is an owned thread.

### Request validation

Create:

- title required
- prompt required
- thread id required and must be owner-accessible
- `schedule_type` required
- `once` requires run timestamp
- `cron` requires valid 5-field cron
- timezone required

Update:

- allow title/prompt/schedule/timezone changes
- disallow owner/thread reassignment across users
- disallow mutation while task is in temporary `running` state if that would invalidate schedule semantics

### Authorization

Owner checks are mandatory for:

- list
- detail
- run history
- patch
- pause
- resume
- trigger
- delete
- thread-scoped list

This should reuse existing auth patterns from thread/runs routers rather than inventing a new access scheme.

## Frontend Design

### Navigation

Add new workspace nav item:

- `/workspace/scheduled-tasks`

This belongs beside existing high-level workspace surfaces in `WorkspaceNavChatList`, not hidden under settings.

### Main page

Add page:

- `frontend/src/app/workspace/scheduled-tasks/page.tsx`

The page includes:

1. list table/cards
2. filter bar
3. create-task button
4. detail drawer or side panel

### List columns

- title
- thread title
- schedule summary
- status
- next run
- last run
- last result
- actions

### Filters

MVP filters:

- status
- schedule type
- thread

No owner filter is needed in MVP because tasks are already owner-scoped.

### Create/edit form

Fields:

- title
- thread selector
- prompt textarea
- schedule type: `once | cron`
- once datetime picker
- cron input
- timezone selector

Validation:

- prompt non-empty
- title non-empty
- once datetime must be in the future
- cron must be valid before submit

### Detail view

Displays:

- full prompt
- thread link
- raw schedule config
- last error
- run history list
- actions: pause/resume/trigger/delete/edit

### Thread-level entry point

Thread chat pages gain a visible entry point to view schedules for the current thread.

MVP behavior:

- small button/link in thread page header opens filtered scheduled-task page for current thread

It does not need a full embedded task manager in-thread. Reusing the main page keeps the first PR smaller.

## State and Data Fetching

Frontend adds a small `scheduled-tasks` API layer under:

- `frontend/src/core/scheduled-tasks/`

Recommended pieces:

- typed request/response models
- list/detail/run-history fetchers
- mutations for create/update/pause/resume/trigger/delete
- React Query hooks

This should follow the same shape the repo already uses for threads and feedback, not ad-hoc local fetch calls sprinkled through components.

## Error Handling

### Backend

Explicit failures that must surface cleanly:

1. missing or deleted thread
2. unauthorized owner access
3. invalid cron
4. invalid timezone
5. task already paused/resumed
6. trigger rejected due to active in-flight thread run
7. scheduler launch failure before run creation

Failure must never cause infinite immediate retry loops.

### Frontend

Users should see:

1. inline form validation errors
2. mutation toasts for pause/resume/trigger/delete
3. visible failed state in task row
4. visible `last_error` in details

The UI must not show a healthy-looking task row when the last scheduler attempt failed.

## Testing Strategy

### Backend unit tests

1. valid and invalid cron expressions
2. valid and invalid timezone handling
3. weekday normalization semantics
4. next-run computation across timezone boundaries and DST-sensitive cases
5. one-time schedule status transitions
6. due-task claim logic and lease expiry
7. overlap skip behavior
8. misfire `run_once` behavior

### Backend integration tests

1. CRUD API with owner isolation
2. thread-scoped task list route
3. pause/resume/trigger/delete flows
4. manual trigger creates a normal DeerFlow run through shared launch helper
5. scheduler loop claims each due task once
6. dispatch failure writes task and task-run errors correctly
7. deleted thread does not hot-loop retries

### Frontend unit tests

1. scheduled-task nav item renders and routes
2. list renders status/next run/last result
3. create dialog validates form state
4. action buttons settle correctly after API response
5. detail drawer renders history and last error

### Frontend E2E

Playwright with mocked APIs:

1. list page loads
2. create task from UI
3. pause/resume/trigger/delete flows
4. thread header link navigates to filtered scheduled-task view

### Real-path validation

Required before claiming feature complete:

1. start backend and frontend
2. create a one-time task due soon from the real UI
3. observe row move through live status updates
4. confirm linked DeerFlow run exists
5. confirm completed/failure state is visible in the management page

## Documentation Updates Required

If code lands, update:

1. `README.md` with feature overview and enablement note
2. `AGENTS.md` and `backend/AGENTS.md` with scheduler/runtime ownership and commands if architecture changes
3. config docs for new `scheduler` section

## Code Review Checklist

1. Scheduled runs reuse the existing run lifecycle.
2. Harness persistence does not import `app.*`.
3. Due-task claim logic is atomic.
4. No hot loop after dispatch failure.
5. Day-of-week semantics are explicit and tested.
6. Owner checks cover list/detail/history/mutate/trigger/delete.
7. UI shows failing state honestly.
8. Background scheduler remains opt-in.
9. Thread-level entry point does not introduce duplicate management UI logic.
10. Chat-created scheduling remains absent from MVP.

## Implementation Order

1. Backend persistence and repository layer
2. Schedule parser / next-run computation
3. Shared run-launch helper
4. Scheduler service and API
5. Frontend API layer and page
6. Thread header entry point
7. E2E and real-path validation

This order is mandatory because the frontend cannot be implemented against an unstable backend contract.
