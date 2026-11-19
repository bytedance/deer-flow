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

{"request_id":"review-27","objective":"Review the report","assistant_id":"lead_agent"}
```

The response includes the task, its assignment (agent and thread), and the
latest execution. Replaying the request reuses the worker. Read the same
view with `GET /api/coordination/tasks/{task_id}`. Add a follow-up with
`POST /api/coordination/tasks/{task_id}/inputs` and a JSON object containing
`request_id` and `content`. A text message sent to the worker thread uses
the same queue. Streaming and wait callers observe the run that consumes
their message. An interrupted graph requires an explicit resume command.

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

Worker observation uses the initiating session's process-local run handle.
The task, frozen inputs, native run IDs and artifact contents survive a Gateway
restart. Automatic reauthorization and restart reconciliation are tracked in
the next stage of [RFC #8345](https://github.com/bytedance/deer-flow/issues/8345).
