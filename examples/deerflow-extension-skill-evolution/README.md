# Agent self-evolution for DeerFlow

Pluggable **Agent self-evolution** for DeerFlow. The first module is **Skill evolution** — the interactive evolution policy
prompt and the `skill_manage` tool entry point, shipped as an installable extension
package. Implements [RFC 6954](https://github.com/bytedance/deer-flow/discussions/6954)
See [Design and behavior](docs/design.md) for the current architecture,
configuration lifecycle, safety boundaries and operational limits.

## Agent evolution workspace (0.15.0)

Navigation and the page title now read **Agent 自演进 / Agent self-evolution**.
Skill evolution is the first available module. Memory evolution is shown as
**planned** only; it has no backend actions and does not receive Skill permissions.
The operational section is named **信息 / Information** and lives inside the Skill
module, together with installation, policy, capabilities and permission notes.
The refresh button sits in the Skill module header and refreshes only its data.
The host renders the single page H1. Evolution modules use H2 (22px);
Self-evolved skills, Configuration and Information use H3 (18px), each with
a description. Expanded configuration groups use H4 (14px).

The workspace groups Skill records and their collapsible configuration together,
uses consistent spacing and wrapping operation buttons, follows the host theme,
and hides pagination for a single page. Changing evolution mode still applies
immediately; changing host grants requires a Gateway restart.

The module catalog (`static/modules.mjs`) provides UI factories, while Skill UI
lives in `static/skill.mjs` and shared DOM helpers in `static/common.mjs`. Future
modules can add their own factory, actions and explicitly granted capabilities.
The status response adds `product: "agent-evolution"` and a module availability
catalog. Existing distribution/import/entry-point names, namespace
`community.skill-evolution`, browser module ID, stored data and configuration keys
remain compatible. Continue upgrading with the existing source directory:

```bash
make extension-upgrade SOURCE=examples/deerflow-extension-skill-evolution
```

Restart Gateway after upgrading and refresh the browser. For the first upgrade
from installation-local settings, migrate before replacing the old package;
see the persistence instructions below. Subsequent upgrades retain settings.

## What this extension owns — and what stays in the host

The split follows the RFC's single-owner rule:

| Concern | Owner |
| --- | --- |
| When the agent should consider evolving a skill, and the exact policy text it reads | **This extension** |
| The `skill_manage` tool entry point offered to the model | **This extension** |
| Name/path validation, static scan, LLM moderation scan, per-user storage, JSONL history, sandbox projection, cache invalidation | **Host** (unchanged) |

The extension binds to the host's existing public `skill_manage` tool object
(`deerflow.tools.skill_manage_tool:skill_manage_tool`) instead of
re-implementing it, so security enforcement and storage truth can never fork.
If the host does not provide that tool, `install()` fails the extension load
with an actionable error (`required: true` turns that into a startup abort) —
the extension never silently registers a weaker replacement.

### Relation to the host's `SkillMutationService` (API 0.2.7+)

Newer hosts ship a controlled-mutation backbone — `read_skill` → `stage` →
`check` → `commit` / `discard` / `revert` proposals over existing skills, with
asset revisions, crash recovery and idempotency — delivered to extension
services as `ExtensionRuntimeDeps.skill_mutations` (plus the sealed
completed-run evidence reader `ExtensionRuntimeDeps.completed_run_evidence`)
when the operator grants them:

```yaml
plugins:
  - name: skill-evolution          # explicit stable name is required for grants
    use: deerflow_extension_skill_evolution:install
    enabled: true
    host_access:
      evidence:
        owners: ["<user-id>"]      # must be a superset of skill_mutations owners
      skill_mutations:
        owners: ["<user-id>"]      # exact IDs; no wildcards
        operations: ["stage", "check", "commit", "revert"]
        target_skills: ["my-skill"]
        trigger_agents: ["<agent-id>"]  # agent whose sealed runs may act as evidence
        topology: single_host_local
```

Two layers exist side by side:

- **Interactive path (unchanged).** The `skill_manage` tool the middleware
  declares remains the host's user-bound tool: it resolves the runtime user on
  every call and may create brand-new skills. The landed mutation service is
  bound at Gateway start to operator-declared owner IDs, so the interactive
  tool deliberately does **not** route through it. The RFC's user-bound
  six-action `apply()` seam (and the `SkillVersionService` query/rollback
  contract) are still proposals; when they land, `tools.py` is the single
  module that changes.
- **Managed path (new).** With the grants above, the extension now actually
  drives the guarded backbone through read-only-owner plugin backend actions
  in the `community.skill-evolution` namespace:

  | Action | Payload | Effect |
  | --- | --- | --- |
  | `managed_read` | `{skill_name, source?}` | Read the current revision/content of an enrolled skill |
  | `managed_stage` | `{skill_name, content, source?}` | `read_skill` → `stage` only; returns the pending proposal (the page's Stage button) |
  | `managed_check` | `{proposal_id}` | Run the host's guarded `check` on an owned staged proposal (the page's Check button) |
  | `managed_propose` | `{skill_name, content, source?}` | `read_skill` → `stage` → `check` in one call; returns the proposal and the scan verdict |
  | `managed_publish` | `{proposal_id}` | `commit` a checked proposal (host re-gates on a fresh `allow` verdict) |
  | `managed_discard` | `{proposal_id}` | Discard a pending proposal |
  | `managed_rollback` | `{operation_id}` | `revert` one published operation to its recorded before-state (host fence: the operation must be the current head, within its rollback window) |
  | `evolved_version` | `{operation_id}` | Return one journal entry's saved content snapshot for the "restore this version" flow |
  | `annotation_draft` | `{skill_name}` | Plan A: synthesize a draft SKILL.md — the current content plus a trailing `## Usage Feedback` section built from the caller's saved annotations — for the stage editor (answers `UNAVAILABLE` when `evolution_mode: model`) |
  | `annotation_evolve` | `{skill_name, model_name?}` | Admit one background draft job per owner+skill (`BUSY` otherwise). Browser callers select an ordinary chat model by `model_name`; no plugin model-role grant is required. Explicit `model_role` remains a legacy service-call path only |
  | `evolution_status` | `{skill_name}` | Return the caller's latest evolution job: `running` progress without contents, or a succeeded job's base and draft content for the diff view; a draft committed through the pipeline after the job finished carries `published: true`, and a draft identical to its input carries `unchanged: true` (both derived from the version journal) |
  | `evolution_discard` | `{skill_name, job_id}` | Delete one caller's job record (cancels a still-running task) |
  | `skill_config` | `{}` | Read the operator-grant state this page can edit: the current `target_skills`, the granted `model_invocation.roles`, the caller's live skill catalog (public + their custom skills, the same source as `/api/skills`), the configured model names, and whether config.yaml was found and the caller may write (membership in `skill_mutations.owners`) |
  | `skill_config_write` | `{skill_names}` | Validate the proposed target skills against the caller's live catalog, then rewrite only this plugin's `host_access.skill_mutations.target_skills` in config.yaml's `plugins:` block through the host's surgical editor under the extension-manager lock. The model invocation grant is deliberately untouched (model choice is a per-launch selection). Returns the reinstall command; the change applies only after a Gateway restart |
  | `skill_trajectories` | `{skill_name}` | List the caller's most recent sealed runs (max 3) whose event journal activated the skill, as a readable timeline: each event carries a kind (human/model/tool/activation), the tool name where recorded, and a bounded preview of the caller's own content (their message, the model's reply, or a tool-result excerpt); system noise (`run.*`, `context:*`) and textless model turns are filtered out |
  | `trajectory_annotate` | `{skill_name, run_id, event_id, note}` | Save or replace the caller's note on one trajectory event (plugin-owned `skill_annotations` table) |
  | `trajectory_unannotate` | `{skill_name, run_id, event_id}` | Remove the caller's note on one trajectory event |

  `source` is optional: omit it to auto-discover the caller's newest sealed
  completed run, or pass `{"thread_id", "run_id"}` explicitly. Every mutation
  call carries that sealed snapshot as its acting source, which is what makes
  the proposal attributable to real task evidence.

**Identity model.** The acting owner is never taken from the payload: it is
the host-stamped principal of the backend-action caller, and `mutations.py`
requires it to match the evidence source's owner (`managed_read` /
`managed_stage` / `managed_propose`) or the existing proposal/operation owner
(`managed_check` / `managed_publish` / `managed_discard` / `managed_rollback`). This check is a
real boundary, not just defense in depth: the Gateway injects the
service-bound evidence reader with global cross-user visibility, so without
the extension-side check any authenticated user of the plugin surface could
stage proposals against an enrolled owner's sealed runs. The host
additionally re-validates the operator's owner/target/trigger-agent allowlist
on every call, and owner mismatches are indistinguishable from missing
snapshots (`SOURCE_STALE_OR_GONE`) so the surface cannot be used to probe
other users' runs.

All actions return `{"ok": true, ...}` or `{"ok": false, "error": {"code":
...}}` with stable host error codes (`UNAVAILABLE`, `SOURCE_STALE_OR_GONE`,
`REVISION_CONFLICT`, `CHECK_REQUIRED`, `QUOTA_EXCEEDED`, `BUSY`, …) and no
exception text. `propose` derives its idempotency key deterministically from
(owner, skill, source snapshot, content), so a retried proposal safely
replays the same staged proposal; `publish`/`rollback` keys derive from the
proposal/operation id. Publication is deliberately two-step — the check
verdict comes back to the caller, and only an explicit `managed_publish`
mutates the skill.

On hosts without the grants (or older than API 0.2.7) every managed action
reports `UNAVAILABLE` and the `status` snapshot shows
`managed_pipeline: "unavailable"`; the interactive `skill_manage` path is
unaffected.

`PromptContributor` likewise remains a proposal, which is why the policy still
reaches the model through a hidden state-injected message (below).

## How the policy reaches the model

- **Tool** — a middleware declares the host tool through its `tools` instance
  attribute. The host's Layer-1 authorization narrows middleware-declared
  tools before binding, so a deployment that denies `skill_manage` keeps it
  denied.
- **Prompt** — the extension injects one hidden, provenance-stamped
  `SystemMessage` in `before_agent` (stable ID
  `extension-skill-evolution-policy`, so re-injection is idempotent). This is
  the interim mechanism until the host ships a dedicated prompt-contribution
  contract; `wrap_model_call` request overrides are intentionally discarded
  by the isolation wrapper and cannot carry prompt text.

Known limitation of the interim wiring: the injected policy does not react to
a build in which authorization narrowed `skill_manage` away (the isolated
middleware cannot observe its own narrowing). Authorization still blocks the
call; only the prompt's selective suppression waits for the host contract.

## Install

```bash
# from the repository root
make extension-install SOURCE=./examples/deerflow-extension-skill-evolution
```

or add it to `config.yaml` manually:

```yaml
plugins:
  - source: ./examples/deerflow-extension-skill-evolution
    enabled: true
    config:
      # All keys optional; defaults reproduce the historical core behaviour.
      min_tool_calls_hint: 5      # 1..100 — prompt advice only, never a counter
      prefer_patch: true          # prefer `patch` over full-rewrite `edit`
      confirm_before_create: true # ask before creating a brand-new skill
      scope: lead                 # lead | lead_and_subagent
      # feedback_mode is superseded by the page's evolution_mode switch (below);
      # it remains parsed for compatibility.
      # storage_path: /absolute/path/skill-evolution.sqlite  # enables the plugin-owned record/annotation store
```

Restart the Gateway after every extension mutation. There is deliberately **no
private `enabled` key** — the `plugins:` entry's own `enabled` flag is the only
deployment switch. Unknown or wrongly-typed config keys fail the load instead of
silently changing the model-visible policy.

`scope: lead` is the deliberate default: subagents do not need an active
evolution prompt. Opt into `lead_and_subagent` only when your subagents should
also create or patch skills.

## Annotation-driven evolution (`evolution_mode`)

Trajectory annotations (below) can feed skill evolution through one runtime
switch, with two deliberately different shapes:

- **`model` (default).** Using the same configured models and caller
  permissions as chat, the trajectory panel offers **"Evolve from feedback" (确认并优化)**:
  confirming annotations triggers an *immediate, plugin-driven* model call
  (see the jobs section below for the full lifecycle).

- **`append` (直接添加 — fully offline).** Every skill row gains a
  **"Draft from feedback" (标注草案)** button. The `annotation_draft` action
  reads the skill's current SKILL.md through the guarded managed pipeline,
  appends a `## Usage Feedback` section listing the caller's saved
  annotations (newest 20, bounded), and the page prefills the stage editor
  with the result — the normal stage → check → commit gates apply unchanged.
  Without a store or without annotations the draft simply equals the current
  content. No new model surface and no new authorization.
- **`model` (模型 — read-only model tool + annotation-triggered jobs).** Two
  complementary surfaces:
  - The middleware additionally declares a read-only `skill_feedback(skill_name)`
    tool (next to `skill_manage`), and the evolution policy tells the agent to
    consult it before creating or updating a skill. The tool resolves the
    effective user from the injected runtime — the model can never supply a
    user id — reads only that user's annotations, never raises (every failure
    degrades to an informative string), and is only declared when
    `storage_path` is configured.
  - Using authenticated chat-model access, the trajectory
    panel offers **"Evolve from feedback" (确认并优化)**: confirming
    annotations triggers an *immediate, plugin-driven* model call instead of
    waiting for the next agent run. `annotation_evolve` reads the current
    SKILL.md through the guarded managed pipeline plus the caller's
    annotations, admits one background job in the plugin-owned
    `evolution_jobs` table (at most one running job per owner+skill), and
    returns at once. The background task assembles the prompt (editing policy
    + current content + feedback notes) and invokes `ActionContext.chat_models`,
    reusing the normal chat factory and model:use authorization. Calls have
    shared per-plugin admission, a 120-second maximum deadline including
    authorization, and bounded input/output sizes. The page polls `evolution_status` to show
    progress, then renders a **line diff** of the model's draft against the
    current content. Publishing stays human-gated: "Stage this draft" replays
    the draft into the normal stage → check → commit editor; "Discard" drops
    it; published versions roll back through the existing version history.
    When the poll first sees a terminal job, the transient "started" note is
    replaced by the outcome (draft ready / unchanged / published / failed) so
    a quiet finish never reads as a stuck launch. Two terminal outcomes are
    reported instead of a diff: a draft whose content has since been
    committed through the pipeline carries `published: true` (比对版本 journal
    加提交时间推导，无需新增状态) and shows a quiet confirmation with a
    "Clear record" action; a draft identical to its input carries
    `unchanged: true` — the model reviewed the annotations and kept the
    content — and says so plainly instead of an empty diff. Saving an
    annotation (new or edited) supersedes either consumed record: the job is
    auto-cleared and the panel returns to the evolve trigger — pending
    drafts and failed jobs are deliberately kept. The model only ever
    produces draft text — every mutation still passes the host's guarded
    pipeline.

  The page hides the deterministic draft button in this mode and the backend
  answers `annotation_draft` with `UNAVAILABLE`, so the switch is
  authoritative server-side, not just in the UI.

### Where the switch lives (persistent settings, 0.16.0)

The **插件配置 / Plugin configuration** fold contains target skills and the
`evolution_mode` selector: **模型 / Model** (default) or **直接添加 / Append**.
Selected skills appear first when the fold opens; each group is alphabetical.
Unsaved checkbox choices are retained when closing and reopening the fold.

With `storage_path: /state/evolution.sqlite`, the choice is stored in
`/state/evolution.sqlite.settings.json`. It is read per call, takes effect
immediately, and survives package replacement. Valid legacy installation-local
`settings.json` is copied on initialization if the persistent file is absent;
existing persistent settings win, and unrelated JSON keys are preserved.
Without `storage_path`, the old installation-local file is a compatibility
fallback and cannot survive package replacement. Missing/corrupt/invalid values
default to `model`.

**First upgrade from 0.15.x or older:** the installer can remove the old package
before new code starts. Run this migration using the new checkout **before**
`make extension-upgrade`, with the actual configured database and old installed
package settings paths (not the example paths):

```bash
backend/.venv/bin/python examples/deerflow-extension-skill-evolution/deerflow_extension_skill_evolution/modes.py \
  --storage-path /state/evolution.sqlite \
  --legacy-settings /old/installed/deerflow_extension_skill_evolution/settings.json
```

This does not delete the legacy file, create a database, change host grants or
overwrite existing persistent settings. If there is no old settings file, the
mode defaults to Model and the first page save creates the persistent file.
The legacy `feedback_mode` config key remains parsed for compatibility only;
`skill_feedback` is declared whenever `storage_path` is configured.

### Staging and feedback deduplication (0.16.0)

Saving a staged proposal automatically runs the host check on that exact proposal
and displays its decision and reason code. The **检查 / Check** button remains
available for retries. If checking fails, the staged proposal remains available;
only an allowed verdict enables Commit, and publishing still requires a user click.

Append drafts exclude feedback already present in the current skill. Each new
entry includes a hidden SHA-256 marker based on owner, skill, full run/event IDs
and normalized note text. Saving the same annotation again does not duplicate it;
edited notes remain eligible. Exact legacy rendered entries are also recognized.
Deduplication happens before note/byte limits, so consumed notes cannot starve
remaining feedback. The response reports `already_included_count` separately.
Generating or staging a draft does not consume feedback: until publication,
repeated drafts are identical. Reverting the skill makes removed notes eligible
again. Keep the markers when editing content to retain this provenance.

Both shapes live entirely inside this extension: the tool, the prompt section,
and the draft action are all contributed by the extension's own middleware /
plugin registration, so disabling or uninstalling the extension removes all
of them at once — no host code references `skill_feedback`, and a deployment
without the extension never sees any of these surfaces.

### Configuring target skills from the page

The status page's **Plugin configuration** (插件配置) card — rendered below the
self-evolved skills list — edits the operator grant without hand-editing
config.yaml:

- **Target skills** lists every skill the caller can see (DeerFlow public
  skills plus their own custom/project skills — the same catalog as
  `/api/skills`) as checkboxes pre-checked for the current
  `host_access.skill_mutations.target_skills`. A single-shot free-text input
  accepts one typed skill name, validated against that catalog before it is
  consumed.
- **Save** submits once: `skill_config_write` validates every name
  server-side (unknown skills fail closed with the offending list,
  non-canonical names never reach the file) and rewrites only this plugin's
  entry in the `plugins:` block through the host's surgical editor under the
  extension-manager lock. Only callers listed in `skill_mutations.owners`
  may write. The response carries the reinstall suggestion
  (`make extension-upgrade SOURCE=examples/deerflow-extension-skill-evolution`);
  the new grants apply after a Gateway restart — the running process never
  picks them up live.

Model choice reuses the ordinary chat catalog (`/api/models`) and current user
permissions. The picker submits `model_name` directly; there is no separate
plugin role list, authorization badge or model credentials to maintain. Its
first visible model is the default and is sent explicitly, so a user's filtered
model list and the selected model stay consistent. Selection is per launch.

This requires a host that supplies `ActionContext.chat_models`. The Gateway
binds it to browser sessions (or the normal default user in explicit auth-disabled
local mode); PAT/internal calls and model tools receive no such capability.
Existing service-held `host_access.model_invocation` roles remain supported for
legacy non-browser calls, but are not required or consulted by the page picker.
Updating the plugin alone on an older host is insufficient; update/restart the
Gateway as well. No live model request is made just to display the picker.

## Migrating from the core `skill_evolution` switch

The legacy core block in `config.yaml`:

```yaml
skill_evolution:
  enabled: true
```

renders the same policy from inside the host. When both are on, the extension
detects the core switch, keeps contributing the tool, suppresses its duplicate
prompt, and logs one warning per process. To complete the migration, set
`skill_evolution.enabled: false` and let this extension be the single owner.
(The forced host-side suppression of the core prompt when the extension is
active is a core-side change, outside this package.)

Uninstalling/disabling the extension stops new injections, but a policy
message already persisted in an older thread checkpoint remains there (it is
part of that checkpoint's history). Start a new thread or compact to clear it.

## Operational status

The extension registers a read-only `status` backend action under the plugin
namespace `community.skill-evolution`, plus a browser status page
(`ui_manifest.json` + `static/`). The page reports the resolved config,
whether the host still provides the `skill_manage` tool, whether the legacy
core switch is on, and the grant state of the host's guarded evolution
capabilities (`skill_mutations`, `completed_run_evidence`,
`managed_pipeline`) — never skill content, user data, or credentials. On
hosts without full-stack plugin support the registration degrades to a log
line.

The status surface ships as packaged browser assets
(`ui_manifest.json` + `static/index.mjs` + `static/style.css`), contributing one
`page` surface with navigation. Once installed and enabled, the workspace
sidebar shows **"Skill 自演进 / Skill self-evolution"** under the extensions
group (next to other page-surfacing plugins like agent teams). The
**self-evolved skills** list is the page's primary content — exactly the skills
this plugin has saved through the managed pipeline — in a paginated list (name,
saved/reverted state, enabled state, description, updated time). The deployment
details (installation identity, evolution policy, host capabilities, mutation
grant) fold away in collapsed `<details>` sections below it. Authorship is
tracked in the plugin's own SQLite record store (operator-configured
`storage_path`; commits and reverts through the pipeline are recorded per
owner), and the live description/enabled state is joined from the host's
existing authenticated `GET /api/skills` endpoint fetched from the packaged
asset origin with session credentials — the same pattern as the agent-teams
plugin. Without a configured `storage_path` the listing degrades to an inline
"records disabled" notice. Pagination is client-side (8 per page).

Each skill row also renders one **operation button per operator-granted
mutation operation** (config.yaml `host_access.skill_mutations.operations`, in
canonical pipeline order), each bound to its backend action:

- **Stage** opens an inline SKILL.md editor pre-filled from `managed_read` and
  stages the edited content through `managed_stage`;
- **Check** runs the host's guarded scan on the staged proposal
  (`managed_check`) and shows the verdict;
- **Commit** publishes the checked proposal (`managed_publish`);
- **Revert** opens the skill's **version history** panel. The host's revert is
  CAS-fenced to the current head operation, so the newest entry offers
  "Undo this operation" (`managed_rollback`), while older entries offer
  "Restore this version": their content snapshot (recorded at stage time in
  the plugin's own journal) is fetched via `evolved_version` and replayed
  through the stage editor — restoring an old version publishes it as a new
  forward version through the normal stage → check → commit gates. Entries
  without a snapshot are shown disabled. Every entry also offers **"View
  changes"** (查看变更): it fetches that version's snapshot plus the previous
  one and renders the inline line diff (与演进草案同一 diff 组件) under the
  entry, toggleable; the earliest retained version diffs against empty
  content.

Activation discovery follows event pages until a match or the end of a sealed
run, with a 200-page scan budget (100 events / 128 KiB per page). Missing or
repeated cursors and exhausted budgets return explicit errors. The returned
timeline contains at most 200 visible events around the first activation,
including up to 100 preceding events; shortened windows are labeled in the UI.

Each skill row starts with **View versions** (查看版本), a read-only history panel
with per-version changes. It shares the history and diffs used by Rollback, but
never offers undo or restore controls; these remain in the Rollback panel.

Every row additionally offers **Trajectories** (轨迹): a panel listing the
caller's most recent sealed runs (up to 3) whose event journal contains a
`middleware:skill_activation` event for that skill. Runs start collapsed, showing
their title, time, event count and recorded activation event numbers.
The Locate activation button expands the run and cycles through those points,
scrolling to and highlighting each point with its neighboring visible events.
Neighbors provide context, not evidence that every following step used the skill.
An expanded run separately shows its first available user-input preview with the
source event number. The original event order is preserved, even if activation
was journaled first. View earlier conversation opens the full thread in a new tab;
it does not merge earlier runs into this timeline. Click a header (or press Enter/Space
when focused) to expand its events and annotations. Expansion is retained during
page-local updates. Each expanded run renders as a readable timeline: system noise is filtered out and every event shows its
kind (用户/模型/工具/技能) plus a bounded preview of the caller's own
content — the user's message text, the model's reply, or the tool name with
a result excerpt — so a human can see what actually happened around each
activation and annotate the events that mattered. Activation points (调用点)
keep their badge with the recorded skill path/content hash. Previews are
excerpts of the caller's own sealed runs only, capped at 200 characters;
other users' data never reaches this surface. Clicking any event opens an
inline editor to annotate it (`trajectory_annotate` /
`trajectory_unannotate`, stored in the plugin's own `skill_annotations`
table per owner and skill). New or edited annotations require an owned,
sealed supported run, an existing visible event, and journal evidence that the
selected skill was activated in that same run. Other skills' activation events
are rejected. Validation scans evidence independently of the display window;
failures never save feedback or clear evolution jobs. Opening the trajectories panel closes the editor
and version panels. In `feedback_mode: draft` each row also offers the
**Draft from feedback** (标注草案) button described above.

Check/Commit are disabled until a proposal is staged in the page. Operation
outcomes and error codes render inline under the row. The page never calls
undeclared backend actions: `status`, `evolved_skills`, `evolved_version`,
`managed_read`, `managed_stage`, `managed_check`, `managed_publish`,
`managed_rollback`, `annotation_draft`, `annotation_evolve`,
`evolution_status`, `evolution_discard`, `skill_trajectories`,
`trajectory_annotate`, and `trajectory_unannotate` are its only backend calls.

`frontend: BrowserAssets` is optional for this extension — without it, the
extension still contributes the tool and prompt; only the sidebar page and the
capability-center module entry disappear.

## Development

```bash
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]" -e ../../backend/packages/extension-api
pytest tests/ -q
ruff check . && ruff format --check .
```

The wheel is validated by the repository's release gate:

```bash
uv run --project backend --no-sync python scripts/check_extension.py examples/deerflow-extension-skill-evolution
```


### Understanding the information panel

**Agent 行为建议 / Agent behavior guidance** explains prompt advice separately
from the saved evolution method. `min_tool_calls_hint: 5` only tells the agent
to consider saving experience after a complex task; no counter starts an evolution
job on the fifth tool call. The page starts a model draft through
`annotation_evolve` after the user clicks Confirm and improve.

**运行条件与权限 / Runtime requirements and permissions** reports connected host
services and storage configuration, with descriptions of their source and limits.
These indicators are not per-operation health or authorization guarantees.
The obsolete feedback_mode display is removed. Protocol, deployment topology and
the old built-in switch appear under **高级诊断 / Advanced diagnostics**.


### Background trajectory warmup (0.17.0)

Opening the plugin page starts trajectory reads as soon as the self-evolved skill
list arrives, in parallel with catalog descriptions. The current and following
pages are warmed (up to 16 skills with the current 8-item page size). Changing
pages warms the new window and drops obsolete queued speculative reads.

At most two trajectory requests run concurrently. Clicking a queued skill raises
its priority; clicking an in-flight skill shares the existing request. Completed
results, including empty histories, are reused for 60 seconds. Expired results
remain visible while refreshed in the background; a cold click can still wait if
warmup has not finished. The number of returned trajectories remains three.

Manual Refresh clears the cache and warms again. Saving/deleting annotations
forces a fresh read for that skill, and late old responses cannot overwrite it.
Failed reads have a five-second retry cooldown; permission errors discard stale
content. Background replies do not repaint an annotation currently being edited.

Warmup runs within the authenticated, mounted page, not globally at Gateway
startup. Cached data stays in page memory, is never written to localStorage, and
is discarded on unmount. Up to 32 completed/cache entries are retained by recency;
pending work is limited to the warmup window plus explicit clicks. Closing the
page stops queued requests and ignores in-flight replies; the host action API
cannot cancel an already dispatched backend action.


### Reliability fixes after commit review

- Discarding a job checks both caller ownership and skill identity before
  cancelling its background task. Foreign or mismatched IDs have no side effects.
- Recent trajectories and automatic mutation-source discovery follow the host's
  oldest-first metadata feed to its end. Only the last 25/50 statuses are retained
  for snapshot lookup; metadata scans stop with an error after 200 pages or on a
  missing/repeating cursor instead of silently presenting an old page as recent.
  Initial lookups may therefore traverse multiple metadata pages.
- Evolution model choices now reuse chat model names and user permissions.
  Legacy explicit service-role calls retain their existing grant validation.
- Model responses only lose one valid surrounding Markdown fence; multiple
  document code blocks and language-specific blocks remain intact.
- Configuration-read failures display an error instead of an endless loading
  message.
