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
6. The activity feed pairs requests with their results, identifies the sender and
   recipient, and shows peer handoffs and return status. It updates automatically
   while visible, preserving unsent drafts, expanded details and approval input.
   Unchanged revisions return a small response. Task details open the full member
   conversation or cancel an active task. Files stay in the original conversation.
7. When a task or its result receipt needs input, expand its details, inspect the
   actual interruption in its conversation, then submit an explicit JSON response.
   The plugin never generates approvals. Respond through the team page while it
   owns the request so it can track the resumed run. Cancelling keeps checkpoints;
   an interrupted checkpoint blocks subsequent new tasks until resolved.
8. After restarting Gateway, choose **Manage → Reconnect** in an active team.
   Persisted jobs retain their inputs and idempotency keys; active runs are
   reconciled instead of blindly restarted. Reconnection also recreates a missing
   member thread with its recorded Agent binding. If creation was interrupted,
   the team becomes ready only after all member threads are ensured successfully.
   Existing threads stay unchanged.

A new authenticated native mention can also reconnect its team. Existing queued
jobs then continue under that caller's current delegated capability.

Deleting a finished team removes its plugin records, not its Agent conversations.
Cancel/finish all queued, running and interrupted jobs first. Each user has their
own teams. Sharing a host conversation does **not** share its team's private data.

## Execution and limits

- Full Agent runs use the host-bound `AgentRuns` capability, never `task()` workers
  or raw model invocation. Capabilities are process-local, never stored in SQLite.
  Gateway rechecks the user, permission ceiling, current permissions and thread
  access on every call. PAT/internal callers without this capability cannot run teams.
- Different member conversations can run concurrently; admissions are bounded to
  eight active plugin jobs. Each conversation is serialized, including result
  receipts. A busy host conversation stays queued without cancelling its run.
- Each owner can have 20 teams. A team accepts at most 100 requests, with separate
  space for up to 100 result receipts (200 total job entries); a handoff chain
  accepts at most 12 requests. Start a new user request for another chain, or a
  new team when the team's capacity is exhausted. Agent-to-Agent loops therefore
  cannot grow without a bound.
- Tasks accept up to 4,000 characters / 8,000 UTF-8 bytes. Shared context contains
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
serialization, interrupts, cancellation, restart/reconnect (including incomplete
creation), request capacity independent of receipts, ambiguous admission, and
lifecycle locking. Host-run transport is controlled for deterministic tests.

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
search and selection, unique bounded member labels after truncation, keyboard
mentions, task/result pairing, peer receipts,
automatic conditional updates, draft/detail preservation, owner isolation,
conversation navigation, mobile/dark layouts, delete-action contrast in both
themes, reopening, deletion and disposal.
The agent catalog and identity are synthetic; the peer fixture calls the real
plugin handler through the public ToolContext contract. It does not claim production
authentication or live-model coverage. Set `TEAM_PREVIEW_URL` for another port and
optionally `TEAM_SCREENSHOT` to save a local screenshot outside the repository.
