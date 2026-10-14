# Agent teams — independent plugin

Let existing full Custom Agents work together through directed requests and a
shared record. Each member gets its own persistent conversation, bound to its
Custom Agent name. Ordinary Agent configuration, tools, skills, memory,
checkpoints and approval rules remain in effect. There is no mandatory supervisor.

Requires DeerFlow's native mention-provider and full Agent run-control contracts
(`deerflow-extension-api >= 0.2.5`). This package is opt-in, with no core team
feature or frontend rebuild.

## Install

From `backend/`, install the trusted local package:

```sh
uv run deerflow extensions install ../examples/deerflow-extension-agent-teams --yes
```

Set the deployment-owned entry in `config.yaml`, then restart Gateway:

```yaml
plugins:
  - use: deerflow_extension_agent_teams:install
    enabled: true
    config:
      enabled: true
      storage_path: /var/lib/deerflow/agent-teams.sqlite
```

Mount a persistent writable directory. The package contains its browser assets;
the host serves the manifest-listed files. Both switches, package upgrades and
the path require a Gateway restart. This SQLite example supports **one Gateway
process per database**. A second service instance refuses to start against the
same database; it cannot dispatch through its actions or middleware.

## Use

1. Create at least two Custom Agents in **Agents**. Members can delegate work to
   each other using this plugin's collaboration tools. Usually no extra setup is
   needed; if an Agent has a tool-group allowlist, include `extensions` in it.
2. Open **Agent teams** in the sidebar, or
   `/workspace/extensions/community.agent-teams/teams`.
3. Set a name and goal, search your existing Agents by name or description, and
   select 2–8 members. The plugin reads the authenticated public `/api/agents`
   endpoint on its asset Gateway, preserving deployment prefixes. Catalog errors
   have a retry control and never silently fall back to invented agents. The
   roster is fixed for this team; create another team for a different composition.
4. In the team composer, type `@` and select one or more members, or click a member
   in the sidebar. Recipient chips determine routing; unselected plain-text names
   do not. Each selected member receives a separate request. Use Send or
   Command/Ctrl+Enter; Enter inserts a newline except while choosing a mention.
   The normal host chat's native `@` picker remains available too.
5. A member can call `send_member` to ask a peer for work. Its result returns to
   the requesting conversation in a later turn. `read_team_context` reads the
   current shared record; members do not synchronously block or poll each other.
   Handoffs inherit the executing request's parent and chain budget. Later queued
   requests do not change that attribution; an ordinary member chat with no
   executing team request starts its own chain.
6. The activity feed pairs requests with their results, identifies the sender and
   recipient, and shows peer handoffs and return status. It updates automatically
   while visible, preserving unsent drafts, expanded details and approval input.
   Unchanged revisions return a small response. Task details open the full member
   conversation or cancel an active task. Files stay in the original conversation.
7. When a task or its result receipt needs input, expand its details. An ordinary
   clarification shows its question and accepts a text answer, submitted as a
   human message. A graph interrupt instead requires inspection in the member
   conversation and an explicit JSON response. The plugin never generates
   approvals. Respond through the team page while it owns the request so it can
   track the continued run. Unanswered questions do not produce completed-result
   receipts. Cancelling keeps checkpoints; unresolved questions and interrupts
   block subsequent new tasks in that conversation until answered.
8. After restarting Gateway, choose **Manage → Reconnect** in an active team.
   Persisted jobs retain their inputs and idempotency keys; active runs are
   reconciled instead of blindly restarted. Reconnection also recreates a missing
   member thread with its recorded Agent binding. If creation was interrupted,
   the team becomes ready only after all member threads are ensured successfully.
   Existing threads stay unchanged.

A new authenticated native mention can also reconnect its team. Existing queued
jobs then continue under that caller's current delegated capability.

## Find earlier team evidence

Members have three read-only tools in addition to the short `read_team_context`:

- `read_team_history`: page through retained shared messages, newest first.
  Optional `member_id`, `job_id` and literal case-insensitive `query` filters
  apply before pagination. The shared record retains at most 100 messages.
- `search_team_results`: find finished requests by the same filters, searching
  both task text and the stored answer. Results follow newest-first request
  creation order and include completed, failed and cancelled requests; result
  receipts are excluded to avoid listing a delivery as another member task.
- `read_team_result`: read one request or receipt by `job_id`. It returns member,
  requester, status, parent task, timestamps, and `conversation` thread/run IDs,
  with a short request excerpt and the retained answer. Source IDs are references;
  the host's ordinary conversation permissions remain authoritative.

For example, a reviewer can search `{"team_id":"...","query":"release evidence"}`
with `search_team_results`, then pass a returned `job_id` to `read_team_result`.
The result remains available after leaving the recent eight-message context or
the shared record, provided its bounded answer was saved in the task ledger.
Reads work after service restart without reconnecting or starting Agent runs.
Only the owning user's current member conversations may call these tools.

Pages default to eight records and accept `limit` from 1 to 20. Follow
`next_cursor` with the same tool and filters; page size may change. Cursors anchor
to record identity, so newer arrivals do not shift an existing page. Pages are
live, not immutable snapshots: newly completed older requests may appear on later
result pages. If an anchor leaves retained history, `cursor_expired=true` returns
an empty page; restart the query explicitly. Changed filters reject the cursor.

Each response is limited to 24,000 UTF-8 JSON bytes, including metadata and
escaping, so a page may contain fewer than `limit` records. Search summaries have
500-byte request/result excerpts; history text and individual answers have a
6,000-byte limit. `truncated=true` marks shortened text. New answers also preserve
whether the original collected answer was truncated; legacy answers report
`result.truncated=null` when that provenance is unknown. `result.available=false`
distinguishes unfinished work, cancellation without an answer, and a legacy
answer no longer retained. Inspect the source conversation for further evidence.
Cancelled requests have no available answer at either cancellation timing;
their cancellation notices remain in shared history.
These tools expose retained task data, not hidden reasoning, execution inputs,
approval responses, attachment bytes or an unbounded transcript archive.

Deleting a finished team removes its plugin records, not its Agent conversations.
Cancel/finish all queued, running and interrupted jobs first. Each user has their
own teams. Sharing a host conversation does **not** share its team's private data.

## Execution and limits

- Full Agent runs use the host-bound `AgentRuns` capability, never `task()` workers
  or raw model invocation. Capabilities are process-local, never stored in SQLite.
  Gateway rechecks the user, permission ceiling, current permissions and thread
  access on every call. PAT/internal callers without this capability cannot run teams.
- Admissions are bounded to eight active plugin jobs across this database.
  New requests and pending answers rotate by owner, one admission attempt per
  owner per round. The unfinished round carries over between passes, including
  when a served owner's queue becomes empty. Unavailable queues drop out and new
  owners join the tail. Spare capacity can be used by any queued owner; existing
  runs are not preempted when another owner joins.
- Each team has its own execution/control lock and background worker. Slow host
  calls in one team do not hold another team's create, send, cancel, resume,
  delete or reconnect operations, nor stop its background polling. Operations
  within the same team remain serialized, with a ten-second timeout per job
  advancement. Shutdown cancels and drains all workers before releasing the
  database service lock.
- Each conversation is serialized, including result receipts targeting a source
  shared across teams. The first unfinished job retains the conversation until
  it finishes or is cancelled. A busy host conversation stays queued without
  cancelling its run. Unadmitted conversation waits release their temporary
  reservation. An admitted job in `waiting_input` also releases its slot even
  though its original input remains frozen; it still retains the conversation's
  queue head. Pending answers wait for capacity. Other unfinished frozen jobs,
  including unknown admission outcomes and resumes already attempted, keep their
  slots while disconnected and after service restart. Reconnect the owning team
  to reconcile them. Cancelling an unstarted answer does not admit it.
- Each planning pass uses one indexed batch query for teams with unfinished jobs.
  Completed history is not decoded. The plugin database adds a pending-job flag
  and index, reads legacy rows completely before transactionally backfilling
  them at initialization, and updates the flag with each team mutation. The
  projection includes waiting-input jobs for conversation ordering even though
  those jobs do not occupy active slots.
- Each owner can have 20 teams. A team accepts at most 100 requests, with separate
  space for up to 100 result receipts (200 total job entries); a handoff chain
  accepts at most 12 requests. Start a new user request for another chain, or a
  new team when the team's capacity is exhausted. Agent-to-Agent loops therefore
  cannot grow without a bound.
- Team names accept up to 80 characters / 160 UTF-8 bytes; goals accept up to
  2,000 characters / 4,000 UTF-8 bytes. Tasks and clarification answers accept
  up to 4,000 characters / 8,000 UTF-8 bytes. The UI validates both bounds before
  submission and preserves oversized text for editing. String answers count their
  raw UTF-8 bytes, including the 8,000-byte ceiling; JSON quotes and escapes do not
  reduce that allowance. Structured graph-interrupt responses retain an 8,000-byte
  UTF-8 JSON limit. Responses with unpaired Unicode surrogates are rejected through
  the normal response validation. Native mention labels
  fall back to the member name when the combined team/member label exceeds the
  host's 120 UTF-16-unit limit; selection still routes by team/member IDs.
  Shared context contains
  at most eight recent messages within a 24 KiB JSON budget, plus the goal and
  roster. Final answers are capped at 6,000 UTF-8 bytes with a truncation notice.
  Team storage retains the most recent 100 shared messages. Each new job also
  keeps its bounded result independently, so context rotation does not erase its
  activity card. Older installations fall back to retained messages; an unavailable
  old result links to the original conversation. Compact request pages default to
  20 records. The UI requests up to 200 detailed entries (within the bounded team
  capacity), and sends a revision to avoid retransmitting unchanged results. This
  is a bounded working context, not a transcript archive.
- Shared task text and peer results travel as human-message data with provenance,
  never as framework system instructions. Only final text is shared automatically;
  hidden reasoning, tool transcripts and attachment bytes are not copied.
- Do not launch unrelated turns or manually compact a member conversation while
  a team request is being collected. If its identifying checkpoint is gone or a
  later human turn is detected, the plugin reports that the result cannot safely
  be attributed and asks you to inspect the conversation.
- Admission timeouts retain the exact input/key for idempotent recovery. Revoked
  access or an ambiguous host failure disconnects the team without pretending
  that its active jobs completed. Reconnect after resolving the cause.

## Validation

From `backend/`:

```sh
uv run pytest tests/test_agent_teams_plugin.py tests/test_extension_agent_runs.py tests/test_plugin_tools.py -q
uv run ruff check ../examples/deerflow-extension-agent-teams
uv run ruff format --check ../examples/deerflow-extension-agent-teams
```

The tests load the real extension and exercise owner isolation, directed requests,
real ToolNode dispatch, mention middleware in the Lead middleware pipeline,
host-compatible mention labels at the UTF-16 boundary with stable routing IDs,
serialization, interrupts, cancellation, restart/reconnect (including incomplete
creation), request capacity independent of receipts, ambiguous admission, and
lifecycle locking. Event-gated scheduling regressions also cover cross-team control
isolation, continued background cancellation, owner rotation with single-slot
release and mixed backlogs, exhausted/cancelled queues and new owners, overlapping
ticks, pending answers, shared-source receipts, worker
shutdown and durable slots across restart. Storage regressions cover indexed batch
reads, terminal-history exclusion, complete legacy reads before backfill, rollback
and projection updates when queuing, cancelling, finishing or creating receipts.
History tests cover filtered cursor pagination under new arrivals, expired anchors,
output byte budgets with escaping and Unicode, old answers after record rotation
and restart, legacy unavailable/truncation states, owner/member isolation, and
real ToolNode retrieval followed by another peer handoff.
Host-run transport is controlled for deterministic tests.
Clarification tests execute the host's real tool and middleware in an Agent graph,
including repeated questions, peer/mention/result-receipt paths, lost response
acknowledgements and restart. Response regressions cover the 7,999/8,000/8,001-byte
boundaries for both input paths, structured JSON, escaping and malformed Unicode.
Queued-request regressions pin handoff attribution
and the chain limit while the first request is running or awaiting admission acknowledgement.

For a browser check, install the repo's frontend dependencies, then start the
loopback-only fixture from `backend/`:

```sh
uv run python -m extension_test_fixtures.agent_teams_gateway 8197
```

In another terminal, from the repository root:

```sh
node examples/deerflow-extension-agent-teams/verify_browser.mjs
```

This drives packaged UI assets, real plugin routes, SQLite and graph checkpoints,
with a synthetic identity and deterministic model. It verifies team creation,
insecure HTTP without `crypto.randomUUID`, Shadow DOM, catalog failure/retry,
search and selection, unique bounded member labels after truncation, Unicode
character/byte validation with draft preservation for names, goals, tasks and
clarification answers, accepted ASCII/CJK/emoji boundary inputs, keyboard
mentions, task/result pairing, peer receipts,
automatic conditional updates, draft/detail preservation, owner isolation,
conversation navigation, mobile/dark layouts, delete-action contrast in both
themes, ordinary clarification and text responses, reopening, deletion and disposal.
The agent catalog and identity are synthetic; the peer fixture calls the real
plugin handler through the public ToolContext contract. It does not claim production
authentication or live-model coverage. Set `TEAM_PREVIEW_URL` for another port and
optionally `TEAM_SCREENSHOT` to save a local screenshot outside the repository.
