# Agent self-evolution extension

This package is the Agent evolution workspace. Skill evolution is its first
implemented module; Memory evolution is reserved and has no actions or permissions.
Keep the distribution, import path, entry point, namespace and browser module ID
stable for installed configuration, grants, persisted state and page URLs.

Browser code lives in `deerflow_extension_skill_evolution/static/`:
- `index.mjs`: Agent workspace shell, lifecycle and navigation.
- `modules.mjs`: module catalog and factories; planned modules have no factory.
- `skill.mjs`: Skill listing, configuration, trajectories, evolution pipeline, module refresh and information.
- `common.mjs`: shared DOM and localization helpers.
- `trajectory-cache.mjs`: per-page trajectory cache, warmup queue and freshness.
- `style.css`: host-themed, responsive styles scoped to the workspace.

Declare every browser asset in `ui_manifest.json`. Add future evolution modules
with their own UI factory, backend actions and explicit host capability admission;
never infer Memory permissions from Skill grants. The status catalog describes
implemented vs. planned modules, not whether the operator granted their services.

Run from the repository root:

```bash
PYTHONPATH=examples/deerflow-extension-skill-evolution backend/.venv/bin/python -m pytest examples/deerflow-extension-skill-evolution/tests -q
node --test examples/deerflow-extension-skill-evolution/tests/test_*.mjs
```

Verify changes with packaged assets in a browser; use isolated fixture responses
for visual checks without writing production skills or changing operator grants.

Refresh controls and operational information belong inside their module. The Agent
shell mounts module content and starts its lifecycle without calling Skill actions.

Heading hierarchy: the host supplies the page H1; module titles are H2, Skill
sections are H3, and configuration groups are H4. Use `createSectionHeading`
for section titles and descriptions. Do not duplicate the host page title.

Evolution modes are bound at install via `EvolutionModeSettings` and shared by
configuration, status, append drafts and model jobs. With storage_path, the JSON
sidecar is `<database-filename>.settings.json`. Migration is create-only; normal
writes use private unique temp files and atomic replacement. Before upgrading an
older install, the source `modes.py` migration command can preserve legacy settings.

Append idempotence derives from the current host skill content, never from marking
annotations consumed when a draft is merely generated. Markers use full source IDs
and note content; filter consumed feedback before applying draft quotas.

UI staging auto-checks the exact returned proposal. Keep manual check/retry and
human commit separate; failures preserve the staged proposal. Block concurrent
pipeline actions per skill and display host verdicts without bypassing admission.

Information labels distinguish Agent prompt guidance, runtime permissions and
advanced diagnostics. Never describe min_tool_calls_hint as an automatic trigger:
there is no count-based scheduler. Do not present legacy feedback_mode as an
independent active mode; use evolution_mode for the actual draft method.

Trajectory warmup is authenticated page-local work. Preload current/next pages,
limit concurrency to two, share in-flight reads and prioritize explicit clicks.
TTL is 60 seconds (errors: 5 seconds); retain stale data while revalidating except
on permission errors. Clear on manual refresh/unmount; annotation writes force a
new entry identity so older replies cannot overwrite it. Do not let a background
completion reset an open annotation editor. Add every relative module import to
the browser asset manifest and run all JS tests with `node --test tests/test_*.mjs`
from this extension directory.

Read oldest-first evidence metadata through `recent_runs.recent_changed_runs`,
which follows the feed to its end while retaining only a bounded tail. Limit
snapshot/event reads separately. Missing/repeating cursors fail closed; metadata
scans have a 200-page budget. Do not mistake the first page for the newest runs.

Evolution job discard must validate owner AND skill before cancelling any task.
Browser model selectors submit configured chat model names through host-bound
`ActionContext.chat_models`, never synthesize operator role grants. Explicit
legacy model_role requests keep their service-grant checks. Only unwrap
one complete Markdown response fence; preserve code blocks inside skill content.

Keep [docs/design.md](docs/design.md) as the current behavior and design reference.
Documentation filenames should describe their subject without dates. Avoid stale
session logs, local commit/deployment claims and solved issues presented as TODOs.

Browser model calls reuse the host factory and model:use authorization. Do not
import provider credentials or duplicate chat permission logic inside the extension.
Keep skill/evidence grants separate. Hosts without chat_models must return a clear
unavailable result for model_name calls rather than silently using a legacy model.

Trajectory runs use native details/summary disclosure, initially closed. Retain
explicit expansion per skill/run across page-local repainting, including annotation
edits and model-job polling; warmup must never expand a run.

Activation navigation uses only invocation=true events from the host journal;
show original seq numbers, never infer activation from tool names or previews.
Adjacent visible events are context, not per-step execution attribution.

Expanded run context shows the first available human-event preview separately;
never reorder journal events or infer missing input. Link to the full conversation
using the host thread_id with URL encoding, in a new tab to retain local editors.

Version history has distinct view and rollback modes. Always offer View versions
before pipeline controls; view mode renders only diff actions. Switching to
rollback must retain the existing undo/restore admission path.

Separate event discovery from display limits: scan sealed evidence with cursor
validation and an explicit quota error, retain at most 200 visible events around
the first activation (up to 100 before), and report shortened timelines. Annotation
writes must validate caller ownership, snapshot identity, the referenced visible
event and same-run target-skill activation via the evidence reader before any
store/job side effect. Do not restrict annotation validation to recent/display
windows. Other skills' activation events are not valid target-skill feedback.
