# Incognito chats

An incognito chat is a temporary conversation for material you do not want in
your ordinary workspace. It never appears in the chat list, archive, project,
share, activity or search surfaces, and it is not usable as a conversation
reference or as the reuse target of a scheduled task. While it is alive, only
its owner can open it by its exact thread URL; there is no sidebar entry.

Incognito is a DeerFlow storage boundary, not a promise about third parties.
Conversation content still goes to the model provider and any tools or
connectors you use, whose data handling is outside DeerFlow's control. DeerFlow
is self-hosted and does not train models on your conversations.

## Start and end

Start an incognito chat from the new-chat entry point or open
`/workspace/chats/new?incognito=true`. The workspace shows a dark incognito
frame, a dashed composer border and two notices: the chat does not enter
history, memory or search, and the idle lifetime shown is taken from the live
configuration. Ordinary chats and incognito chats cannot be converted into one
another.

Use the **×** control to end the chat. The browser leaves immediately; the
Gateway then schedules a short deletion grace in the background. If that
request fails, the idle lifetime still ends the chat. An ended chat cannot be
reopened from a list, and its deadline no longer grows when a run finishes.

The first version allows incognito creation only from an authenticated browser
session. Personal access tokens, IM channels, extensions and scheduled runs
cannot create one. An operator can disable new incognito chats with
`incognito.enabled: false`; existing incognito chats still expire on schedule.

## What the run does not write

Runs in an incognito chat do not write long-term memory or the shared blob
store. Passive memory capture, the compaction flush and the memory tools'
write operations are skipped; large tool outputs and viewed images stay in the
thread's own workspace instead of entering shared blob storage. Reading
memory that already exists (injection and search) still works. Everything the
chat does write stays inside its thread directory and is removed by the same
expiry sweep.

## Lifetime and deletion

The deadline shown in `expires_at` moves forward on run admission and run
completion, but never past the absolute maximum measured from creation. The
defaults are:

| Setting | Default | Meaning |
| --- | --- | --- |
| `incognito.idle_ttl_seconds` | 86400 | idle window after the last activity |
| `incognito.end_grace_seconds` | 3600 | grace after an explicit end |
| `incognito.max_lifetime_seconds` | 604800 | absolute lifetime from creation |
| `incognito.sweep_interval_seconds` | 60 | Gateway scan cadence |
| `incognito.sweep_batch_size` | 100 | maximum threads purged per pass |

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
