# Script workflows (Phase 1)

An opt-in packaged extension that runs inspectable JavaScript orchestration in the
background. Scripts call full DeerFlow Agents through the public `AgentRuns`
capability. A chat tool or authenticated plugin action returns a workflow run ID
promptly; **Script workflows** shows the script, argument hashes, execution limits,
progress, child conversation/run identities, and final result.

Phase 1 has no saved definition library, resume, authenticated output sign-off,
continuation serialization, automatic restart replay, or hard monetary budget.
It therefore does not complete the inspection-report scenario requiring human
approval between stages. Agent execution success, a script verdict and human
approval are separate facts.

## Install and enable

Requires a POSIX Gateway (Linux/macOS), Python 3.12+, the public extension API 0.2.5,
and a **single Gateway process per storage file**. Windows execution is unsupported.
The package holds an exclusive process lock; another process using that same file
fails service startup rather than recovering another worker's live workflows.
Use only a trusted operator-installed package.

Pinned QuickJS 1.19.4 provides CPython 3.12 wheels for macOS universal2 and Linux
x86_64. Python 3.13/3.14 and Linux arm64 installations build its source distribution:
install a C compiler and matching Python development headers first (for example,
Xcode Command Line Tools on macOS, or `build-essential` plus the matching
`python3-dev` package on Debian/Ubuntu). Source-build compatibility depends on your
Python/toolchain; use CPython 3.12 on a wheel-supported platform if the build fails.
This also applies to backend development dependency installation and arm64 containers.

From the repository root:

```sh
make extension-install SOURCE="$(pwd)/examples/deerflow-extension-workflows"
```

Set the installed plugin's operator-owned `config.yaml` entry:

```yaml
plugins:
  - name: workflows
    use: deerflow_extension_workflows:install
    enabled: true
    config:
      enabled: true
      storage_path: /absolute/deployment-owned/workflows.sqlite
      agents: [lead_agent]  # Add explicitly authorized existing Custom Agent names.
      concurrency: 2
      global_concurrency: 4
      max_calls: 16
      max_workflows: 4
      max_workflows_per_owner: 2
      timeout_seconds: 300
      admission_timeout_seconds: 10
      cpu_seconds: 5
      memory_bytes: 16777216
```

Find **Script workflows** in the workspace extension directory for the installation
guide. Its catalog listing does not indicate installation or activation; the operator
configuration above and Gateway runtime registration determine availability.

Restart Gateway. The namespace is `community.workflows`; the page is
`/workspace/extensions/community.workflows/runs`. The UI and tools are disabled by
default. `agents` restricts target selection in addition to normal host permissions;
it does not grant access to otherwise unauthorized models, tools or Agents.
Only supported host session/auth-disabled credentials supply a retained AgentRuns
handle; PAT/internal/channel callers cannot acquire one.

## Run an example

Open **Script workflows**, paste
[`examples/checks.workflow.js`](examples/checks.workflow.js), and enter:

```json
{"product":"Synthetic sample","formula":["ingredient A"],"claims":["sample claim"]}
```

Click **Launch workflow**. An accepted launch shows its run ID immediately;
if refreshing the list or details fails, use **Retry inspection**. Inspection retries
do not launch another workflow. Resubmitting unchanged script/arguments retains the
same request ID, including after a lost launch response; changing either creates a
new launch identity. The example sequences evidence collection, fans out two
checks, performs at most two review calls, and branches on a structured verdict.
It returns findings for human review, never a product-pass or approval claim.
This invokes your configured real Agents and can incur provider costs.

In chat, ask the lead to write an inspectable workflow script and launch it with
`launch_workflow`, retaining a stable `request_id`. Host tool names are derived
from the namespace. Use `inspect_workflow` on demand to inspect outcomes and
`cancel_workflow` to request cancellation; do not ask the lead to poll continuously.
The plugin page refreshes active progress every two seconds.

## Script API

A script is an async function **body**, not a Node module. No imports, module
loader, `process`, shell, filesystem, network, credentials, or Python callbacks
are exposed. Frozen `args` is a JSON object.

```js
const first = await agent({stepId:'first', agentRef:'lead_agent', task:args.task});
const checks = await parallel([
  () => agent({stepId:'a',agentRef:'lead_agent',task:{evidence:first.output}}),
  () => agent({stepId:'b',agentRef:'lead_agent',task:{evidence:first.output}})
]);
log('Two checks finished');
return checks.map(check => check.output);
```

`agent()` resolves to `{output, threadId, runId, status: 'success'}`. `output` is the
last attributable non-tool assistant answer: parsed JSON if valid, otherwise text
or content blocks. There is no provider-enforced structured output schema in this
API; validate verdicts in the script before branching. Every Agent call must be
awaited, including fan-out calls. Returning while child promises are outstanding
fails the workflow and interrupts tracked children.

`parallel()` takes lazy thunks and preserves order. The service, independently of
JavaScript promises, bounds admitted children per workflow and globally. A rejected
call rejects its promise; failures are not silently converted to null. Scripts may
catch ordinary failures and use explicit bounded revisions with **new** step IDs.
Limit faults, human-input waits, and uncertain admissions stop the supervisor even
if script code catches their promise rejection.

Step IDs contain 1–80 ASCII letters, digits, underscores or hyphens and cannot
repeat within a workflow. Attempts are currently always 1. `task` is JSON and
becomes an ordinary human message on a distinct, stably named owned child thread.
The host binds that thread's target Agent, checks current authorization on each
operation, and uses its normal agent assembly, models, tools, skills, memory and
checkpoints. The ledger records the requested agent reference and child IDs;
it does **not** claim to record a per-run effective assembly fingerprint.

## Limits and status

Limits are deployment-controlled, not writable by generated script or browser input.
Defaults are in the configuration above; ceilings are concurrency 4, global
concurrency 8, calls 32, active workflows 8 (4 per owner), wall time 600 seconds,
admission 20 seconds, cumulative worker CPU 10 seconds, JS memory 32 MiB.

Each JS engine entry has a 50 ms CPU interruption limit; stack is 256 KiB. The
isolated worker additionally has a cumulative POSIX CPU limit, no core dumps,
zero file-write size allowance, a temporary working directory and a minimal
credential-free environment. The parent kills/reaps it on termination. This is a
capability-restricted JS interpreter in a separate process, not a general OS
sandbox or a guarantee against native engine vulnerabilities.

IPC frames are bounded to 48 KiB. Script JSON encoding is at most 16,000 bytes,
arguments 4,000 bytes, task 8,000 bytes, each captured Agent output/final result
12,000 bytes. There are at most 20 progress messages of 160 JSON bytes each and
100 retained workflows per owner. Inspect responses are bounded to 60 KiB. Unicode
limits apply to the JSON encoding too, including escapes. Oversized results fail
explicitly instead of truncating evidence silently. Latest list returns 20 records;
keep a workflow run ID to inspect older retained records.

There is **no hard dollar-cost limit**. Call/time/CPU limits and ordinary host token
policies do not constitute a shared workflow currency budget. Unknown configuration
keys such as `max_cost_usd` are rejected. Add a generic, authoritative host budget
reservation/enforcement contract before advertising that guarantee.

| State | Meaning |
| --- | --- |
| queued / running | Supervised execution in this Gateway process |
| completed | Script and awaited child calls returned; output is unapproved task data |
| failed | Script, resource limit (including wall deadline), attribution, child execution or observation failed |
| cancelled | Stop requested and known active children interrupted or already terminal |
| waiting_input | Child has a graph interrupt or human-input artifact; downstream stopped |
| needs_reconciliation | Admission/cancellation outcome uncertain; inspect child identities before new work |
| interrupted | Supervisor externally cancelled, or unfinished record recovered after Gateway restart; no execution replay |

Wall-clock expiry reports `failed` with `Execution deadline exceeded` and cleans
up tracked children and the worker. A timeout after child admission reports child
observation failure and interrupts/observes the known run; only uncertain cleanup
escalates it to `needs_reconciliation`. Admission timeouts without a known run ID
retain the stable child thread identity for reconciliation.

Allowlist order does not change request identity; adding or removing allowed Agent
references does. Matching retries still return the retained record after restart.

Cancel is asynchronous and never rolls back side effects. The service retains
in-flight admission until its bounded response returns, records the actual child
run ID, then explicitly interrupts and observes that child. If admission times
out or authorization is revoked during cleanup, it retains `needs_reconciliation`
with stable thread/input/idempotency identity. It never automatically retries an
uncertain admission. Stable request IDs return an existing workflow record; they
never resume it or reexecute completed work. Changed scripts/args/limits with the
same request ID conflict. Phase 2 definition/config invalidation is not implemented.

Caller cancellation during launch does not abandon a committed record: the service
owns persistence through supervisor publication, including shutdown coordination.
A matching retry returns that same supervised record rather than an unowned queued
launch. This does not add execution replay or resume.

Result collection anchors on the visible human input, including the host's canonical
`__user` rewrite after dynamic context injection. Hidden system/memory reminders
cannot become the anchor; genuinely later human input still conflicts.
Result collection checks input message/run attribution and rejects an intervening
human turn, because `get_state()` is the thread's latest state, not immutable run
output. Results are copied before further script calls. Raw per-step input/results
are retained privately; public inspection returns a bounded final result and step
metadata. Child conversations remain accessible through normal host authorization.

At startup, unfinished records become `interrupted`; retained IDs do not recreate
a capability or arbitrary JS continuation. Gateway revokes handles during shutdown,
so cleanup may require reconciliation. Neither graph resume nor tool permission
approval is interpreted as authenticated approval of an artifact version.

## Verify

Backend CI installs QuickJS as a POSIX development dependency; the extension declares
its own pinned runtime dependency. No provider keys are required for these checks.

```sh
cd backend
uv run pytest tests/test_workflow_plugin.py -q
make test
make test-blocking-io
make format
```

Browser checks use a synthetic loopback fixture, not a deployed Gateway:

```sh
node examples/deerflow-extension-workflows/verify_browser.mjs
# If using an installed Chrome instead of downloaded Playwright Chromium:
PLAYWRIGHT_CHANNEL=chrome node examples/deerflow-extension-workflows/verify_browser.mjs
```

Install frontend dependencies first, or set `PLAYWRIGHT_MODULE` to an absolute
Playwright ES module path. The suite exercises launch, inspect, child navigation,
cancel, escaped output, deletion and disposal. Backend tests include the real
Gateway/LangGraph bridge with deterministic test nodes, plus controlled admission
races, limits, owner scope, service shutdown and restart records.

The implementation uses an original small JSON bridge. `deer-workflow` was evaluated
for API shapes but is not imported or copied: its dynamic Node module loader,
unbounded fan-out and external CLI Agent adapters are not used here.
