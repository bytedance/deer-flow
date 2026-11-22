# Run postmortem — explain one sealed run from its own evidence

An opt-in Python plugin that turns a finished run's persisted evidence into a
**verdict, an anomaly list, a timeline and a shareable Markdown report**. It
answers the question an operator asks after a run goes wrong: *what actually
happened, and what should I check next?*

It uses extension API 0.2.11 with no host code changes. The host owns evidence
storage, sealing, retention and authorization; this package owns only the
interpretation of one sealed run, exposed both as HTTP routes and as a
workspace page.

## What it produces

```
GET /api/extension-run-postmortem/runs/{thread_id}/{run_id}
GET /api/extension-run-postmortem/runs/{thread_id}/{run_id}/markdown
```

```jsonc
{
  "verdict": "Run ended with status error.",
  "anomalies": [
    {"code": "run_failed", "detail": "run status is error (Artifact delivery incomplete: ...)"},
    {"code": "delivery_incomplete", "detail": "delivery unsatisfied (presented=0, produced=1)"}
  ],
  "message_counts": {"user": 1, "assistant": 2, "tool_results": 1},
  "delivery": {"satisfied": false, "presented": 0, "produced": 1},
  "timeline": [{"seq": 1, "event_type": "run.start", "summary": "run.start"}, ...],
  "caveats": ["No complete background subagent, remote MCP, or external side-effect coverage.", ...]
}
```

Anomaly codes: `evidence_partial` (seal not complete), `run_failed`,
`run_or_model_errors`, `guardrail_triggered`, `delivery_incomplete`,
`tool_failures`, `stopped_early`, `subagent_unfinished`, plus three distinct
read-bound signals: `evidence_bounded` (the caller's `max_events` cut the read),
`evidence_incomplete` (the snapshot retains more events than it returned), and
`evidence_truncated` (the host truncated event payloads).

The Markdown route renders the same data as a document that can be attached to
an incident ticket. Query `max_events` (1–2000, default 200) bounds the work.


### Workspace page

The same plugin adds a **Run postmortem** page (sidebar entry, localized en/zh)
with the same data. When the host supplies the current thread id to the surface,
the page prefills it; hosts that mount pages without thread context leave the
field empty, so it stays editable. The page can load the latest run the caller
owns on that thread **when the changed-run feed can be read to its end**; a
bounded scan that stops early says so and asks for a run ID instead of
presenting an older run as latest. It renders the verdict, anomalies, activity
and a timeline that reveals further events on demand, and downloads the
Markdown report. It reaches the host only
through three declared actions — `latest`, `report`, `markdown` — so the page
holds no credentials and no network code of its own. A run the caller does not
own answers `{"not_found": true}` rather than an error, and the action route's
principal binding is the same one the HTTP routes use.

## Install and configure

From the DeerFlow checkout root:

```sh
make extension-install SOURCE=examples/deerflow-extension-run-postmortem
```

Grant the evidence capability in `config.yaml` and restart the Gateway:

```yaml
plugins:
  - use: deerflow_extension_run_postmortem:install
    name: run-postmortem
    host_access:
      evidence:
        owners: ["your-user-id"]
```

Prerequisites are the durable database backend and `run_events.backend: db`,
the same as any completed-run evidence consumer. Without the grant the service
fails to start and the Gateway reports a diagnostic; nothing else changes.

Callers are bound twice: the route requires an authenticated principal, asks the
host's request-scoped reader whether the run is visible (when the host offers
one), and compares the snapshot owner with the caller. A run owned by someone
else answers `404`, never `403`, so the route does not disclose existence.

## Design notes

- **Bounded reads.** One request reads at most `max_events` events, follows the
  host cursor, and stops on a repeated cursor. Event payloads are truncated per
  the host's `EvidenceLimits`.
- **Pure derivation.** `postmortem.py` contains no I/O; the service only fetches
  a snapshot and its pages. That keeps the interpretation unit-testable and the
  HTTP surface thin.
- **Evidence is not authorization.** The snapshot and events are data. The route
  binds the caller explicitly; references in the evidence confer no access.
- **Truncation is reported, never hidden.** A short read or a truncated payload
  becomes an `evidence_truncated` anomaly plus a caveat.

## Tests

```sh
cd examples/deerflow-extension-run-postmortem
uv run pytest -q
```
