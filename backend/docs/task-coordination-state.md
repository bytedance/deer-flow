# Task coordination state

The coordination repository persists a unit of work and its ordered follow-up
inputs. Task IDs are independent of Thread and Run IDs. The Gateway can use
the repository to retain work identity when a later execution moves to a
different agent or thread.

Each call takes an owner resolved by the caller. Task creation deduplicates
requests per owner. Input submission deduplicates requests per task and
assigns consecutive sequence numbers. Reusing a request ID with changed
content returns a conflict. Input request IDs should include the source
namespace if more than one source can submit to a task.

A child inherits its parent's project. Dependencies are immutable and
refer to already-created tasks under the same owner, project, and parent.
A task can start after its dependencies succeed and its parent has started.
Success requires every
owned child to succeed and the accepted result to cover the current input
sequence. Failure can be recorded after all owned children settle.

Mutations within one task tree run under a shared root lock on PostgreSQL and
a short write transaction on SQLite. Callers pass the revision they used to
decide a start, finish, or cancellation. Completion also checks the execution
epoch and input sequence.

Requesting cancellation marks the task and its open descendants as cancelling
and advances their execution epochs in one transaction. Independent
prerequisites keep their state. A running caller can record cancellation
once it has confirmed that the subtree's executions have stopped. The
repository handles work state. Host admission, run control, and artifact
authorization belong to the execution integration.

## Managed workers

A signed-in caller can dispatch a task through the Gateway on a SQL-backed
installation. The following request starts a worker without a project. Pass
an optional `project_id` to create its thread in an existing project.

```http
POST /api/coordination/tasks
Content-Type: application/json

{
  "request_id": "review-27",
  "objective": "Review the report",
  "assistant_id": "lead_agent",
  "run": {"recursion_limit": 400, "thinking_enabled": true, "is_plan_mode": false}
}
```

The optional `run` object accepts a positive integer `recursion_limit` and
boolean `thinking_enabled` and `is_plan_mode` flags. Omit any field to use the
normal run default. Each admission caps the requested recursion limit at the
Gateway's current `max_recursion_limit`. The task view shows the requested
settings in `task.run_settings`, or `null` when the task uses defaults.
Settings are saved at creation and apply to every turn, including follow-ups,
approval responses, and restart recovery. Reusing a create request ID with
changed settings returns HTTP 409.

The response includes the task, its assignment (agent and thread), and the
latest execution. After the task has admitted a Run, replaying the same create
request returns the saved task view and its current `authorization_required`
value, even if the Worker grant has expired. Read the same view with
`GET /api/coordination/tasks/{task_id}`. Add a follow-up with
`POST /api/coordination/tasks/{task_id}/inputs` and a JSON object containing
`request_id` and `content`. The owner can replay an accepted input with the same
ID and content to get its original receipt after task closure or grant expiry.
This applies to the task input and managed Run input endpoints. New inputs need
a valid Worker grant. A text message sent to the worker thread uses the same
queue. Streaming and wait callers observe the run that consumes their message.
An interrupted graph requires an explicit resume command.

The task owner can poll `GET /api/coordination/tasks/{task_id}/inputs`
to read the inbox in sequence order. Pass the last seen `sequence` as
`after` and set `limit` up to 100. Rows include the content, creation
time, and source (`task_api`, `run_input`, or `worker_chat`).
An input is `pending` while it can still enter a Run, `admitted`
with its `run_id` once a Run has accepted the turn, or `not_admitted`
when the task has closed to further work.

The Gateway freezes each turn before admission. The SQL transaction that
creates the native run locks the task tree, verifies the execution epoch,
and records the run ID. A follow-up that arrives during a turn advances
the input sequence. When that run stops, the worker continues on its own
thread with the outstanding inputs. Each task has one assignee per epoch.
Workers can use the agent's allowed subagents for local delegation. Background
batches can run local work. A batch cannot schedule an independent follow-up
run on a managed thread; the task owns the next turn.

`POST /api/coordination/tasks/{task_id}/cancel` accepts `expected_revision`.
It fences the owned subtree before requesting run and native batch
cancellation. If confirmation takes longer than five seconds after the
fence is committed, the response is HTTP 202 with status `cancelling`.
The Gateway continues confirming in the background and publishes
`cancelled` once the runs have stopped and batch cancellation is requested.
Poll `GET /api/coordination/tasks/{task_id}` for the status.

A completed task links to the producing run's messages. For presented output
files, the Gateway stores the captured bytes with their SHA-256 hashes and
producing execution. The owner's task artifact URL continues to serve those
bytes after the source file changes. Capture uses the existing archive budgets
of 50 files, 50 MiB per file and 100 MiB per execution. The execution reports
`delivery_failed` if a presented file cannot be captured.

Use `GET /api/coordination/tasks/{task_id}/artifacts` to list the task's
deliveries, including files from earlier executions. The response lists
artifact IDs, source paths, hashes, sizes, producing `run_id` and `turn`,
and download URLs. Results are ordered by turn, then source path and ID.
Use `limit` (default and maximum 100) and `offset` (default 0) to page
through them. Files presented under the same path in different turns
have separate IDs and URLs. The task detail's `execution.artifacts` lists
deliveries produced by that execution.

## Authorization and restart recovery

Dispatch saves a task-scoped grant alongside the first Worker assignment. The
grant expires after 24 hours. The Gateway revalidates the owner's account,
session version, permissions and current grant on each host operation.
Grant replacement and Run admission share the task tree lock.

The Gateway can also mint a grant for an authenticated IM adapter after looking
up the sender's current channel connection. Disconnecting or replacing the
binding invalidates the grant. The adapter entry point runs inside the Gateway.
IM commands and delivery are covered by a later stage of
[RFC #8345](https://github.com/bytedance/deer-flow/issues/8345).

On startup and periodically, the Gateway reconciles open tasks with grants.
It observes live Runs, records results from committed terminal Run evidence,
and retries frozen admissions with their original idempotency key. A Run
interrupted by Gateway shutdown can continue from a pending checkpoint written
by that Run. When the checkpoint is missing, the Gateway settles the execution
from the Run's durable outcome. Pending approvals still require an
explicit response. Recovery also continues work already fenced for cancellation.

The task view reports `authorization_required` when an open task lacks a
valid grant or its current permissions no longer cover the work. Recovery
waits for permission to return and can then continue with the same grant if
it remains valid. Older tasks created before the migration need a grant.
An authorized owner can renew with `PUT /api/coordination/tasks/{task_id}/authorization`
or revoke with `DELETE /api/coordination/tasks/{task_id}/authorization`.
The Grant table stores only authority metadata and the binding generation.
