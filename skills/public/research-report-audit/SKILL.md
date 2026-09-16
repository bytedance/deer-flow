---
name: research-report-audit
description: Explicitly audit a completed research report for coverage arithmetic, selection provenance, unjudged items, and citation integrity. Use only when the user explicitly asks for an audit, an auditable report, or invokes /research-report-audit. Requires the optional research_audit MCP server; never blocks report delivery when that server is unavailable.
---

# Research Report Audit

Audit a completed research report immediately before delivery. This is an
opt-in finalization step, not a replacement for research and not an automatic
hook for every report.

## Preconditions

- Finish the research and draft the report before starting the audit.
- Use the report's actual collection notes, source list, filters, and claim
  inventory. Do not attempt to reverse-engineer coverage from polished prose.
- The expected MCP tool is `research_audit_audit_report`. If it is unavailable,
  do not simulate its result or repeatedly search for an equivalent tool.

## Build The Audit Input

Construct one `audit-input-v1` JSON object in memory:

    {
      "title": "Report title",
      "source_of_set": {
        "method": "api | script | filesystem | html-page",
        "description": "How and when the complete candidate set was obtained"
      },
      "coverage": { "examined": 0, "total": 0 },
      "clusters": [{ "name": "cluster", "count": 0 }],
      "filters": [{ "criteria": "documented rule", "removed": 0 }],
      "claims": [
        {
          "id": "c1",
          "count": 1,
          "text": "Atomic report claim",
          "sources": [
            { "name": "source name", "url": "https://example.com" }
          ]
        }
      ],
      "unjudged": ["stable item identifier"]
    }

Apply these evidence rules:

- Never invent totals, examined counts, filters, items, claims, or sources to
  make a gate pass. If the complete-set size is unknown, say that the report
  cannot establish coverage and preserve the missing fact in the delivered
  audit status.
- `claims[].count` accounts for examined items covered by that claim. Counts
  plus `unjudged` must reconcile to `coverage.examined` without double-counting.
- `clusters` are optional, but declared cluster counts must sum to the examined
  count. Do not create artificial clusters merely to satisfy the equation.
- Record excluded candidates in `filters`. Record examined items that could not
  be decided in `unjudged`; use stable identifiers, not vague summaries.
- Use canonical source URLs. Mirrors, reposts, and aliases of one origin are one
  source, even when their URLs differ.

## Run And Interpret The Audit

1. Call `research_audit_audit_report` with `report` set to the constructed
   object. Set `verify_sources` to `true` when claims contain public HTTP(S)
   sources; otherwise use `false` and state that live source verification was
   not run. Private and loopback URLs are blocked by default.
2. Treat `outputs.verdict` as the audit decision. A `FAIL` verdict is a valid
   tool result, not a tool failure.
3. If the first verdict is `FAIL`, inspect the failed gates and make one honest
   correction pass. Correct the report when its statement is wrong; correct
   the audit input when it misrepresented the actual research record. Never
   change facts solely to obtain `PASS`.
4. Call the audit tool at most twice. After the second result, stop even if it
   is still `FAIL`.
5. Do not retry a `degraded: true` result just to clear a network failure.

## Persist And Deliver

- For every valid tool result, write the complete, unmodified
  `audit-output-v1` envelope to `<report-stem>.audit.json` beside the report.
  For example, `market-report.md` produces `market-report.audit.json`.
- Present the report and JSON sidecar together. In the final response, show
  only the verdict, `degraded` state, failed gate names, and both artifact
  paths. Do not dump the full envelope into chat.
- If the tool is missing or raises an execution/protocol error, deliver the
  report normally, do not create a fabricated sidecar, and label the result
  `UNAUDITED` with the short operational reason.
- If the tool returns `degraded: true`, deliver the report and sidecar and label
  the result `DEGRADED`; unknown network checks are not dead citations.
- If the second valid result remains `FAIL`, deliver both artifacts and clearly
  list the remaining failed gates. Audit failure never blocks delivery.

## Completion Check

Before finishing, confirm that:

- the audit input is traceable to the actual research record;
- no item or source was invented, silently removed, or counted twice;
- no more than two audit calls were made;
- a valid envelope was saved byte-for-byte as JSON, or the report was labeled
  `UNAUDITED` without a fake sidecar;
- report delivery continued for `FAIL`, `DEGRADED`, and tool-error outcomes.
