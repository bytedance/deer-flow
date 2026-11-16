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

Start an incognito chat from the ghost icon at the top right of a chat, or open
`/workspace/chats/new?incognito=true`. The workspace sidebar is removed and the
chat takes the whole window: a dark top bar around a framed conversation area,
a dashed composer border and two notices. The first says the chat does not enter
history, memory or search and gives the idle lifetime from the live
configuration; the second names the third-party boundary below. Ordinary chats
and incognito chats cannot be converted into one another.

Use the **×** control in the top bar to end the chat. The browser leaves immediately; the
Gateway then schedules a short deletion grace in the background. If that
request fails, the idle lifetime still ends the chat. An ended chat cannot be
reopened from a list, and its deadline no longer grows when a run finishes.

The first version allows incognito creation only from an authenticated browser
session. Personal access tokens, IM channels, extensions and scheduled runs
cannot create one. An operator can disable new incognito chats with
`incognito.enabled: false`; existing incognito chats still expire on schedule.

## What the chat does not offer

Three entry points are closed because each one produces a durable object from
the conversation:

- **Scheduled tasks.** A task's prompt and schedule outlive the chat and appear
  on the tasks page, so a run in an incognito chat binds no scheduler
  capability. The model can still explain a schedule, but it cannot create one:
  `schedule_task` reports that tasks are unavailable here. The API also rejects
  naming an incognito thread as a task's reuse target.
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
completion, but never past the absolute maximum measured from creation. The
defaults are:

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
records, feedback, scheduled-task lines, read markers and browser/MCP
sessions through the same orchestration as an ordinary thread deletion. The
tombstone row is retained so the thread ID cannot be reused and read routes
answer `404` instead of an empty `200`. A purge interrupted by a crash or a
work-in-flight conflict is retried on the next pass. See
[configuration](configuration.md) and the commented `incognito:` block in
`config.example.yaml` for the operator settings.
