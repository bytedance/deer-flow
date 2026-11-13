# Scheduled Tasks

DeerFlow now includes a first-class scheduled-task MVP in the workspace.

Editing a one-time task's title or prompt preserves its original execution time, including seconds and the selected occurrence during a daylight-saving clock rollback. Changing its date, time, or timezone recalculates the execution time. Switching tasks while editing loads the selected task's own title, prompt, and schedule.

An unchanged one-time execution time can still be saved within `scheduler.min_once_delay_seconds` of its run. New execution times and reactivated finished tasks must satisfy that minimum delay.

Current MVP capabilities:

- Manage tasks at `/workspace/scheduled-tasks`
- One-time task forms reject local times skipped by daylight-saving transitions; select another time before creating or saving the task.
- Existing one-time tasks display the scheduler's execution time even when a conversation or API saved a local time skipped by daylight saving. Local times without an explicit offset use the first occurrence of a repeated hour.
- Choose whether each scheduled task reuses a thread and its conversation history or creates a fresh thread per run
- Pin each task to `lead_agent` (default) or a custom agent the owner already has; unknown names are rejected
- Sending `assistant_id: null` in a scheduled-task PATCH resets the task to `lead_agent`; omitting `assistant_id` preserves the current agent, including when that custom agent has since been deleted
- Duplicate an existing task into the create form as an editable draft without copying its run history
- Support `once`, `cron`, and `interval` schedules
- Editing or duplicating an interval task preserves its saved cadence until the interval is explicitly changed, including sub-minute intervals allowed by the operator's scheduler configuration
- Run background scheduled executions as non-interactive DeerFlow runs (`ask_clarification` is not exposed there)
- Persist a due execution as `queued` when its reused thread or the global execution budget is busy, then launch it when capacity is available; queued occurrences survive Gateway restarts and fail after `scheduler.queue_timeout_seconds`
- Retrying a busy scheduled task keeps its execution slot while an earlier recovery pass is still in progress.
- A scheduled run whose completion hook fails is finalized from its durable terminal run on the next scheduler poll instead of staying `running` until a restart.
- A storage or bookkeeping error on one occurrence during queue cleanup or dispatch is logged without stopping the remaining occurrences and healthy due tasks in that poll. The affected occurrence remains subject to normal queue and lease recovery; persistent storage failures can delay its recovery. A run that has exceeded `scheduler.queue_timeout_seconds` never starts while cleanup is retried, and expired rows do not consume capacity or fair-queue slots from healthy waiting work; they stay queued until a later timeout sweep records the skip.
- A recurring task whose saved schedule can no longer be computed (for example, its timezone is missing from the time zone database after an upgrade) is paused with the reason as its last error, and every other task keeps running. Resuming it reports the problem until you fix the schedule.
- Share execution slots fairly between task owners: one owner may have at most `scheduler.max_concurrent_runs_per_user` scheduled runs starting or running at a time (default 2, never more than `max_concurrent_runs`; `0` turns the per-owner cap off), and the waiting queue is drained owner by owner, so one owner's backlog never holds back another owner's run. A run that waits longer than `scheduler.queue_timeout_seconds` is skipped, and its history reads "Skipped: it waited too long for a free slot"
- Freeze a task's definition while an occurrence is `queued`, `launching`, or `running`, so a durable occurrence cannot silently pick up a different prompt, thread, or schedule; transitioning a task to paused or deleting it cancels an existing waiting occurrence, while `launching`/`running` work must finish before those mutations are retried and an explicit manual trigger may still wait and run without resuming a paused schedule
- Pause, resume, trigger, inspect history, and delete tasks
- Search task titles or prompts, combined with status/type filters and the current thread scope.
- Execute scheduled work through the normal DeerFlow run lifecycle
- When `channel_connections.enabled: true`, send scheduled task updates to the task owner's connected IM identities (outbox + delivery worker) on apps that support proactive push, which today is WeCom, Feishu/Lark, WeChat and QQ private chat; Settings → Notifications controls proactive updates per connected app, independently of browser notifications and ordinary chat replies. Each occurrence queues at most one message per target: a finished, failed or goal-missed run, the automatic pause after three missed goals, a pause by the agent (its stop condition was met) or the task finishing (all `max_runs` done, `end_at` reached); when several apply, the pause or finish wins and still says how the last run went. A one-time task sends only its run's outcome. The message is queued in the same database transaction that records the outcome, so runs finalized after a crash or a lost lease do not enqueue a duplicate notice for the same target. It reads on its own, in your web UI language (else `channel_connections.notification_locale`): the task title, what happened, a one-line result when the agent replied, and "Open DeerFlow → Scheduled tasks for details.", with no IDs and no links. Plain manual "run now" trials and interrupted runs stay silent, and so do occurrences that end without a finished run (launch error, queue timeout, interrupted by a restart). Channel/transport outages park deliveries without exhausting retries, for up to about a day; platform rejections retry for roughly 15 minutes before settling as `failed`. An identity you disconnect while a delivery is waiting is never pushed to: the row is dropped as `failed`.
- Browse execution history in pages of 50; older pages pause automatic refresh, with an explicit return to the latest runs. Counts appear only after a successful read; loading and failed reads are not reported as zero runs.

Derived run summaries omit leading inline `<think>` reasoning before limiting the text, so a long thought does not replace the actual answer in previews or scheduled notices. Original response history and literal tags in the answer are unchanged; previously stored run summaries are not rewritten.

**Filter execution history through the API**

To inspect failures without downloading every successful occurrence, authenticated clients with `threads:read` can request `GET /api/scheduled-tasks/{task_id}/runs?status=failed&limit=50&offset=0` for an owned task. The optional `status` accepts `queued`, `launching`, `running`, `success`, `failed`, `skipped`, `interrupted`, or `unmet`; these are occurrence statuses, so task statuses such as `completed` are invalid (422).

Filtering happens before pagination. `limit` (1–200, default 50) and `offset` (nonnegative, default 0) apply to matching records, ordered by creation time then ID, both descending. Omitting `status` preserves the existing mixed-history array response; no matches return `[]`. The API does not change task execution, and the workspace history UI remains unfiltered.

Current MVP limits:

- No text-only notification jobs
- No channel or GitHub dispatch targets (result push above is not a dispatch target)

Enable background polling with `config.yaml -> scheduler.enabled`. Manual trigger uses the same scheduled-task resource and execution path.

In the task form, switching an hourly, daily, weekly, or monthly schedule to **Custom cron** starts from its current timing, including selected weekdays or day of the month. Switching back to Custom cron after preset edits uses those edits rather than an older expression.

## Control proactive IM notifications

Open **Settings → Notifications → IM notifications** to turn scheduled-task
updates on or off for each connected, push-capable app. Existing connections
keep receiving updates until you opt out. Turning a channel off cancels its
pending and retrying notices, including an explicitly selected group;
turning it on again does not resend the old backlog. Notifications whose
platform delivery already started may still arrive. Chat replies and scheduled
execution are unaffected. All Gateway workers must run the upgraded version
for the preference to be enforced.

WeChat needs a private message after binding to save its current conversation
context securely; an old binding or changed bot token also needs a fresh private
message. QQ requires a C2C/private binding and platform permission to send
proactively. WeChat remains private-only; QQ and WeCom also support explicitly
selected group destinations.
See [setup and delivery limits](../../backend/docs/IM_CHANNEL_CONNECTIONS.md#proactive-notification-settings).

The same page offers separate **Task & goal run notifications** for completion,
terminal failure and requests for input. These ordinary web/background reminders
are off by default. A pending input request takes precedence over completion;
unmet goal stand-downs stay silent, and IM-originated chats keep their original
reply rather than receiving a second proactive notice. Turning an event off
also cancels its waiting backlog. Messages direct you back to Conversations.

## Optional group notifications

In a task's create or edit form, **Also notify a group (optional)** adds
one chosen group to the existing personal notifications. Add the app bot to the
group, choose its supported channel in the binding panel, then send the displayed
`/connect` command while mentioning the bot in that group. QQ and WeCom require
a name in the binding panel so you can identify the receiving group; the name
travels with the owner-issued binding code and is saved on the connection.
Refresh and select the group by name. Feishu additionally needs `im:chat:read`
to retrieve its group names; every provider needs permission to send proactively.

While the form checks group-notification support, it shows a loading hint and
retains the saved selection.

No group is selected automatically. Clearing the selection stops new group
notices; changing it affects future notices, while already queued notices keep
their original target. A disconnected binding never receives a waiting notice.
The first version is configured through the task form or REST API; conversation
schedule tools keep their existing inputs. See the [group delivery guide](../../backend/docs/IM_CHANNEL_CONNECTIONS.md#group-notifications).

## Lifecycle, safety caps and stop conditions

- The tasks page and the REST API (`POST` / `PATCH /api/scheduled-tasks`) accept the same per-run goal (`goal_objective`), safety cap (`max_runs`, `end_at`) and stop condition (`stop_condition`) as a conversation. Sending `null` in a PATCH clears any of these four; an `end_at` without a UTC offset is wall-clock time in the task's timezone.
- New or changed one-time `run_at` values and submitted `end_at` values without an offset must exist in the chosen timezone. For these fields, a time skipped by a daylight-saving transition is rejected; choose a valid local time or supply an explicit instant with a UTC offset. Repeated local times keep the earlier occurrence unless an offset selects the later one. Recurring cron schedules keep their existing runtime behavior: a fixed-time occurrence in a skipped local time fires at the shifted time that day.
- A stop condition is the user's "stop when …" rule. It is stored in its own field (migration `0031`), never inside the task instructions. Only when a run starts does DeerFlow append it to that run's message and ask the run to call `stop_scheduled_task` when the rule holds. While `scheduler.tool_enabled` is on, every scheduled run can stop its own schedule, whether a chat or the tasks page created the task; with it off, the run is asked to report a met rule instead of calling a tool it does not have.
- Goal tasks created on the tasks page are now evaluated like chat-created ones, and their runs also receive the saved notes and the previous-run reference.
- Resume computes the next run from now, so a long pause never causes a catch-up run. A one-time task whose time has passed returns `422 once_time_passed` and needs a new time. Resuming an active task changes nothing; pausing a finished task returns `409 task_finished`.
- `max_runs` is a lifetime total of automatic runs; trial runs never count. Reactivating a task whose cap is used up (Resume, or a PATCH that re-arms a finished task's schedule) returns `409 limits_exhausted` unless the same request renews the limit that ran out: a used-up run limit needs a higher `max_runs` or `null`, a passed end time needs a later `end_at` or `null` (a later `end_at` alone does not renew a used-up `max_runs`). `POST /api/scheduled-tasks/{task_id}/resume` accepts an optional `{"max_runs": …, "end_at": …}` body for that (`null` clears a cap; chat-created sub-hourly tasks must keep one). A PATCH that only changes the cap of a finished task saves it and leaves the task finished.
- Goal-check failures (the evaluator failed, or the conversation changed during the check) neither count toward the three-miss automatic pause nor reset it. Changing the goal, the instructions or the stop condition, or adding a note, starts a new count; Resume keeps it.
- While this Gateway process's scheduler is not running, creating a task (including Duplicate) returns `409 scheduler_not_running`, because the task would never run on schedule. `GET /api/features` reports `scheduled_tasks.available`, `running`, `tool_enabled` and `min_interval_seconds`.
- Errors from `/api/scheduled-tasks*` are `{"detail": {"code", "message", "params"}}`; see [`backend/docs/API.md`](../../backend/docs/API.md#scheduled-tasks) and `contracts/scheduled_task_errors_contract.json`.

## Create schedules in a conversation

Set both `scheduler.enabled: true` and `scheduler.tool_enabled: true`, then restart
Gateway. An authorized interactive turn can use `schedule_task` to create, update,
list, pause, resume or delete tasks, request a card for a trial run, or save a note. For
example: “Every weekday at 9:00, check release-checklist.md and tell me what is
still unchecked; stop when everything is checked.” In the web app the result is a
live card with the schedule, the stop condition and buttons, and the agent
replies in one or two sentences; IM and other non-web turns describe the
schedule, the next run and the stop condition in plain text.

- **Which tasks a conversation manages.** The tasks created in it, and, in a run
  conversation (the chat a scheduled run posted into), the task that run belongs
  to: “pause this” or “move it to 10:00” work there too. This applies only to
  turns you send. A scheduled run itself can only pause its own schedule with
  `stop_scheduled_task`.
- **Edits keep the task.** Changing the time, instructions, goal, stop condition
  or safety cap is an `update` of the same task, so its ID and run history stay.
  `resume` restarts a paused or finished task without a catch-up run. When the
  cap is used up, the agent asks how to renew the limit that ran out (a higher
  `max_runs` or none; a later `end_at` or none) and sends that with the resume.
- **Timezone.** A zone you name wins. Otherwise a new task uses the browser
  timezone the web app sends with each message (`context.client_timezone`, read
  only for this), and the result says which zone was used. Intervals and
  one-time times with a UTC offset need no zone; for a cron schedule or a local
  one-time time with no known zone (for example from IM), the agent asks. Edits
  keep the saved zone; the browser zone never changes an existing task.
- **Where results appear.** Each run posts its result in a new chat of its own,
  titled “{task} · {local time}”, or in the originating chat when the task runs
  there. When the schedule is paused by the agent, is paused automatically or
  finishes, the originating chat shows one line where the conversation stood,
  with a link to that run or to the task; nothing else is posted back to it.
  The line stays after the task is deleted. A run chat shows the task
  instructions as one collapsed “Task instructions” block under the run's
  header instead of a long user message.
- **Language.** The agent writes the title, instructions and stop condition in
  your language, and scheduled runs answer in the language of the instructions.

New tasks default to a fresh conversation for each occurrence. A configured
`goal_objective` applies only to that occurrence: success does not stop a
recurring schedule. The running agent can request `stop_scheduled_task` for its
own schedule when your stop condition has been met; the request takes
effect during terminal finalization. `max_runs` counts automatic launches only,
and `end_at` provides a deadline. Either end condition takes precedence over a
pause request. Tool-created sub-hourly schedules require an end condition; each
owner may keep at most 20 live tool-created tasks, including paused tasks.

An unmet occurrence is recorded as `unmet`, distinct from an execution failure.
Three eligible automatic unmet occurrences pause a recurring task. Accepted
success resets the streak, including a success relying on disclosed assumptions;
manual trials, interruption, execution failure, external waiting and
goal-check failures do not advance it. Resume retains the streak, so another eligible unmet occurrence can
pause the task again. Connected IM apps with proactive push receive one notice
per occurrence through the same durable outbox (goal missed, auto-paused, paused
by the agent, finished); plain manual trials stay silent.

You can ask the agent in a conversation that manages the task to save an
explicit note for future runs (at most 10 notes of 500 characters). Fresh
recurring runs may read the previous executed occurrence through opt-in
`read_conversation`, with the same owner and read-permission checks. This
provides a source reference, not an automatic summary or a post-back into the
originating chat.

To start a trial, use the task card's **Run once now** button or the corresponding action on `/workspace/scheduled-tasks`. A request in chat can bring up the card, but its wording alone does not dispatch a run. The action uses the existing authenticated, owner-checked endpoint; an already waiting run is not duplicated. A trial does not count toward `max_runs`.

A goal occurrence can use up to nine agent turns, with an evaluator request after
each. Evaluator requests and provider-reported tokens are included in run usage;
missing usage makes the corresponding cost estimate unknown. `token_budget`
limits the main graph and is checked after model calls; evaluator usage is
additional, so it is not a strict whole-run or dollar limit.

**Goal evaluation upgrade:** existing scheduled, webhook and autonomous goal
runs can accept disclosed low-risk, reversible assumptions and record
`relied_on_assumption` in their verdict. Interactive goal evaluation remains
strict. This policy also applies when conversation schedule tools are disabled;
it does not authorize sensitive actions or substitute for user authorization.


Scheduled runs use `scheduler.recursion_limit` in `config.yaml` (default `1000`, matching the web UI's interactive budget). Values above `max_recursion_limit` are clamped. This field is read at dispatch, so the next scheduled run picks it up without a Gateway restart.

The background scheduler is single-instance by default. For a multi-pod deployment, set `scheduler.multi_instance: true` and use shared Postgres, `run_ownership.heartbeat_enabled: true`, and `run_events.backend: db`; startup and periodic recovery then preserve live peer runs, atomically return expired launch claims to the queue, take over only expired run leases, and fence stale launch writes. `max_concurrent_runs` is a shared global cap across Pods for `launching`/`running` occurrences; waiting `queued` rows do not consume it. Without those settings, enable the scheduler on exactly one Gateway pod. These scheduler fields are startup-only; restart all Gateway Pods together when changing them.

## Preview cron occurrences through the API

Authenticated clients with `threads:read` can call `POST /api/scheduled-tasks/preview-cron` before creating a task:

```json
{"cron":"0 9 * * 1-5","timezone":"Asia/Shanghai","count":3,"start_at":"2026-09-12T00:00:00Z"}
```

The response contains normalized `cron`, `timezone`, the effective UTC `start_at`, and `occurrences` with UTC `run_at` and offset-bearing `local_time`. In this example the first occurrence is `2026-09-14T01:00:00Z` / `2026-09-14T09:00:00+08:00`.

`count` is an integer from 1 to 10 (default 5). `start_at` must include a timezone; omit it to capture server time once. Cron expressions use the scheduler's five-field syntax (maximum 256 characters); timezone names are at most 128 characters. Invalid inputs or schedules without the requested future occurrences return 422. Preview shares the scheduler's DST behavior, creates no task, thread or run, and does not reserve execution. This is an API capability; the workspace form does not yet display these occurrences.

## Upgrade Notes

- Occurrence ordering applies to rows admitted by upgraded Gateway instances, which project only sequenced occurrences onto the parent task and defer recovery while any occurrence is still live, whichever instance admitted it; a task whose history is entirely unsequenced keeps the previous timestamp ordering until its first sequenced admission. During a rolling upgrade, rows admitted by pre-upgrade instances are projected by those instances themselves, as before the upgrade, and the ordering guarantees hold once every Gateway writer runs the upgraded version. Existing history is not backfilled; the upgrade does not reconstruct past order or repair historical counts.
- Before upgrading a deployment with `GATEWAY_WORKERS > 1` and `scheduler.enabled: true`, either keep the scheduler on exactly one Gateway worker or configure `scheduler.multi_instance: true` with shared Postgres, `run_ownership.heartbeat_enabled: true`, and `run_events.backend: db`. The upgraded Gateway rejects the unsafe combination at startup instead of starting silently.
- In multi-instance mode, `scheduler.max_concurrent_runs` is a cluster-wide execution cap, not a per-Pod cap. It includes `launching` and `running` scheduled occurrences, so capacity does not multiply with the number of replicas; durable waiting rows remain outside the cap.
- `scheduler.multi_instance` and the related scheduler, ownership, and run-event settings are startup-only. Apply changes with a coordinated restart of all Gateway Pods; changing the ConfigMap alone does not activate multi-instance recovery.
