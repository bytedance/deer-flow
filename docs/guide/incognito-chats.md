# Incognito chats

An incognito chat is a temporary conversation for material you do not want in
your ordinary workspace. It never appears in the chat list, archive, project,
share, activity or search surfaces, and it is not usable as a conversation
reference or as the reuse target of a scheduled task. It also cannot create a
scheduled task, branch into a new chat or open a side chat, because each of
those would copy the conversation into a durable object. While it is alive,
only its owner can open it by its exact thread URL; there is no sidebar entry.

Incognito is a DeerFlow storage boundary, not a promise about third parties.
Conversation content still goes to the model provider and any tools or
connectors you use, whose data handling is outside DeerFlow's control. DeerFlow
is self-hosted and does not train models on your conversations.

## Start and end

Start an incognito chat from the ghost icon at the top right of a blank new
chat, or open `/workspace/chats/new?incognito=true`. A saved conversation does
not offer the icon: an ordinary chat and an incognito chat cannot be converted
into one another. The workspace sidebar is removed and the chat takes the whole
window: a dark top bar around a framed conversation area, a dashed composer
border and two notices. The first says the chat does not enter history, memory
or search and gives the idle lifetime from the live configuration; the second
names the third-party boundary below.

Use the **×** control in the top bar to end the chat. The browser leaves immediately; the
Gateway then schedules a short deletion grace in the background. If that
request fails, the idle lifetime still ends the chat. An ended chat cannot be
reopened from a list, and its deadline no longer grows when a run finishes.
Ending it again does not move the deadline either, so a repeated close cannot
keep the chat around. The ordinary thread-delete API refuses an incognito
thread and points at the end endpoint, because it would remove the tombstone
and make the thread ID reusable.

The first version allows incognito creation only from an authenticated browser
session. Personal access tokens, IM channels, extensions and scheduled runs
cannot create one. An operator can disable new incognito chats with
`incognito.enabled: false`; existing incognito chats still expire on schedule.

## What the chat does not offer

These entry points are closed because each one produces a durable object from
the conversation:

- **Scheduled tasks.** A task's prompt and schedule outlive the chat and appear
  on the tasks page, so a run in an incognito chat binds no scheduler
  capability. The model can still explain a schedule, but it cannot create one:
  `schedule_task` reports that tasks are unavailable here. The API also rejects
  naming an incognito thread as a task's reuse target, whether the task is
  created or edited.
- **Durable subagent batches.** A durable batch stores each item's prompt and
  execution spec in the database so it can resume after a restart, which makes
  it a persistent copy of the conversation. The `batch_task` tool family is not
  offered in an incognito chat, and `batch_task` refuses if reached anyway.
  Ordinary subagents still work through the in-process `task` tool.
- **Agent creation and edits.** Creating an agent, or changing a custom
  agent's persona, skills or model, writes outside the chat and stays visible
  in every later conversation. `setup_agent` and `update_agent` are withheld in
  an incognito run, and both tools refuse if reached anyway.
- **Side chat.** A side chat is its own persistent thread, so the header
  trigger, the panel and the "Ask in side chat" toolbar action are absent.
  "Add to conversation" still works, because a quote only rides the next
  message and is deleted with the thread.
- **Branch.** A branch copies the conversation into a new persistent thread,
  so the branch action is not offered; the API rejects a branch of an
  incognito thread as well.

## What the run does not write

Runs in an incognito chat do not write long-term memory or the shared blob
store. Passive memory capture, the compaction flush and the memory tools'
write operations are skipped; large tool outputs and viewed images stay in the
thread's own workspace instead of entering shared blob storage. Reading
memory that already exists (injection and search) still works. Subagents stay
available and inherit the same rule, so a delegated run neither writes blobs
nor leaves durable batch rows behind. Everything the chat does write stays
inside its thread directory and is removed by the same expiry sweep.

## What the assistant is told

The system prompt states the storage boundary rather than a list of individual
features. It tells the assistant that the conversation is temporary and that
neither it nor anything derived from it can be made persistent from within the
chat, so the rule still covers a capability that is added later. It also states
that memory writes are unavailable and that the assistant must never claim to
have saved or remembered something; a working note such as `task_note` is a
note for this conversation, not long-term memory.

Delegated work inherits the same rule. The lead is told not to ask a subagent
to persist anything and not to trust a report that claims it did; each
subagent's own system prompt carries the boundary as well.

The prompt keeps the third-party edge explicit: content still goes to the
model, search and MCP services, and an external write is not undone when the
chat ends. The interface notices are shown once; the assistant is told not to
repeat them unless the limitation matters to the answer.

## What stays outside the boundary

The promise covers DeerFlow's own storage: an incognito chat leaves no
conversation content in lists, memory, shared blobs or another thread. Three
edges are worth knowing:

- **External side effects are not recallable.** Searches, fetched pages, tool
  and MCP calls, and anything a connector writes happen outside DeerFlow.
  Ending the chat deletes its local trace, not what a third party already saw
  or stored.
- **MCP OAuth credentials belong to the connection.** Connecting or refreshing
  an MCP server's OAuth token writes that credential to the deployment's MCP
  credential store, because credentials are shared by every chat rather than
  owned by one conversation. Disconnect the server in MCP settings if you want
  no trace of the connection.
- **Memory retrieval bookkeeping.** With DeerMem's hybrid eviction policy, a
  memory search records usage metadata (access heat and last-accessed time) for
  the facts it returned in a user-level sidecar. That sidecar stores no
  conversation text.

## Lifetime and deletion

The deadline shown in `expires_at` moves forward on run admission and run
completion, but never past the absolute maximum measured from creation. A
deadline that has already passed is final: a run finishing after it cannot
push it out again, and a run that races the sweep is stopped before its agent
starts rather than allowed to write into a purged thread. The defaults are:

| Setting                            | Default | Meaning                             |
| ---------------------------------- | ------- | ----------------------------------- |
| `incognito.idle_ttl_seconds`       | 86400   | idle window after the last activity |
| `incognito.end_grace_seconds`      | 3600    | grace after an explicit end         |
| `incognito.max_lifetime_seconds`   | 604800  | absolute lifetime from creation     |
| `incognito.sweep_interval_seconds` | 60      | Gateway scan cadence                |
| `incognito.sweep_batch_size`       | 100     | maximum threads purged per pass     |

The Gateway's background sweep writes a tombstone first
(`status="expired"`, with the row's title, metadata and project membership
cleared), then removes the thread directory, checkpoints, run and event
records, feedback, scheduled-task lines, tracked MCP task records, read
markers and browser/MCP sessions through the same orchestration as an ordinary
thread deletion. The tombstone row is retained so the thread ID cannot be
reused and read routes answer `404` instead of an empty `200`. The sweep
rechecks the deadline under the row lock, so a chat renewed after the batch was
read is skipped rather than deleted. A purge interrupted by a crash or a
work-in-flight conflict keeps its retry marker and is retried on the next pass;
the marker is cleared only after the checked stores (runs, events, feedback,
scheduled-task lines, MCP tasks, read markers and durable batch rows) have been
cleaned. Browser and MCP sessions are runtime resources rather than stored
content, so their teardown is best-effort and is not retried. See
[configuration](configuration.md) and the commented `incognito:` block in
`config.example.yaml` for the operator settings.
