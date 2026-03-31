# Sprint 1 Deep Research Pilot Final Report

## Executive Verdict

**Decision Gate:** `Continue DeerFlow-only`

Sprint 1 is complete.

The final batch meets the completion bar:

- `5/5` deep research tasks completed end-to-end
- `5/5` produced real Markdown artifacts
- `5/5` were traceable by `request_id`, `thread_id`, and `idempotency_key`
- duplicate-submit control was verified after contract hardening
- quality distribution reached `3 usable now`, `2 light edits`, `0 heavy edits`, `0 unusable`

The correct post-sprint decision is:

- continue strengthening DeerFlow-only execution

The correct non-decision is:

- do **not** approve OpenClaw bridge work yet

## Why the Gate Passed

The first batch exposed three real problems:

- scope drift
- persona/setup leakage
- dependence on raw runtime file-tool behavior

Those were corrected by:

- locking the prompt to provided context unless external research is explicitly requested
- forbidding extra use cases unless explicitly requested
- making adapter-managed artifact materialization the standard contract
- suppressing greeting/setup behavior in execution mode

The second batch then produced stable, scope-clean outputs.

## Scope

Sprint 1 scope remained:

- DeerFlow-only
- one use case: `Deep Research`
- adapter v0.1
- request tracing, idempotency, heartbeat, timeout, partial-result policy
- operator-facing evidence pack

Still out of scope:

- OpenClaw bridge
- smart routing
- memory sync
- multi-use-case pilot

## Acceptance Check

### Hard Gates

1. 5 deep research tasks run end-to-end: **PASS**
2. Each task has an artifact output: **PASS**
3. Each task is traceable by `request_id`: **PASS**
4. Duplicate submit is controlled: **PASS**
5. Outputs are classifiable by quality bucket: **PASS**
6. Pilot report exists and is decision-ready: **PASS**

### Quality Gate

- `usable now`: 3
- `light edits`: 2
- `heavy edits`: 0
- `unusable`: 0

Interpretation:

The pilot now proves value with stable enough quality to continue DeerFlow-only.

## Evidence Table

| Request | Input Context | Duration | Total Tokens | Quality | Artifact Contract | Artifact |
|---|---|---:|---:|---|---|---|
| `smoke-20260331-v13` | `FINAL-DECISION-HYBRID-SYSTEM-2026-03-31.md` | 69.425s | 14,963 | usable now | standard adapter-managed | `smoke-20260331-v13-executive-brief.md` |
| `smoke-20260331-v14` | `VALUE-REALIZATION-MAP-HYBRID-SYSTEM-2026-03-31.md` | 57.312s | 16,793 | light edits | standard adapter-managed | `smoke-20260331-v14-executive-brief.md` |
| `smoke-20260331-v15` | `HYBRID-SYSTEM-BLUEPRINT-OPENCLAW-DEERFLOW-v2-2026-03-31.md` | 77.138s | 16,783 | usable now | standard adapter-managed | `smoke-20260331-v15-executive-brief.md` |
| `smoke-20260331-v16` | `IMPLEMENTATION-PLAN-HYBRID-SYSTEM-v1-2026-03-31.md` | 80.050s | 16,367 | light edits | standard adapter-managed | `smoke-20260331-v16-executive-brief.md` |
| `smoke-20260331-v17` | `SPRINT-1-BRIEF-DEERFLOW-FIRST-PILOT-2026-03-31.md` | 93.678s | 14,359 | usable now | standard adapter-managed | `smoke-20260331-v17-executive-brief.md` |

## Aggregate Metrics

- Average duration: `75.521s`
- Median duration: `77.138s`
- Max duration: `93.678s`
- Average total tokens: `15,853.0`
- Max total tokens: `16,793`
- Adapter-managed artifact generation: `5/5`

## Duplicate Submit Evidence

Duplicate-submit control was verified by rerunning the v13 task with the same `idempotency_key` (`smoke-20260331-v13`).

Observed behavior:

- the runner returned the existing cached result instead of creating a new request lineage
- the returned payload pointed back to the original request `smoke-20260331-v13`
- wall-clock rerun took about `13.687s`, dominated by container startup rather than a fresh model run

Interpretation:

Idempotency is working after the contract change.

## What Worked

- Thin adapter contract is enough to operationalize DeerFlow for one narrow use case.
- Heartbeats and operator traces make long tasks inspectable.
- Adapter-managed artifact generation removes dependence on runtime file-tool behavior.
- The second batch stayed inside source context and locked Sprint 1 scope.
- All five final-batch outputs are directly usable or need only light editorial cleanup.

## Remaining Constraints

### 1. Artifact generation is adapter-driven by design

This is now an explicit contract, not a defect.

### 2. DeerFlow-only value is proven, but omnichannel need is not

Nothing in this sprint proves that channel or presence gaps are large enough to justify OpenClaw bridge work.

### 3. Output shaping can still improve

Some founder/operator memos would benefit from tighter length control and profile-specific formatting.

## Final Assessment

### Strategic Assessment

**DeerFlow-only has proven it can create real value** for deep document synthesis and decision-support artifacts.

### Operational Assessment

The pilot is robust enough to continue as a DeerFlow-only execution program.

What it is robust enough for:

- more real Deep Research tasks
- deeper DeerFlow hardening
- operator-facing usage inside the current narrow scope

What it is not yet evidence for:

- OpenClaw bridge investment
- multi-use-case rollout
- smart routing or memory sync work

### Correct Post-Sprint Decision

`Continue DeerFlow-only`

## Recommended Next Steps

1. Keep the adapter-managed artifact contract as the default until runtime-native file creation is proven stable.
2. Preserve the new scope-lock and source-lock prompt rules.
3. Add optional style/output profiles so founder memos and operator memos do not share the same verbosity envelope.
4. Continue collecting real Deep Research workloads before revisiting any hybrid bridge decision.

## Key Artifacts

- Gate result: [GATE-RESULT-SPRINT-1-DEEP-RESEARCH-PILOT-2026-03-31.md](D:/project/research-agentic/deer-flow/docs/GATE-RESULT-SPRINT-1-DEEP-RESEARCH-PILOT-2026-03-31.md)
- Pilot runbook: [DEEP-RESEARCH-PILOT-RUNBOOK.md](D:/project/research-agentic/deer-flow/docs/DEEP-RESEARCH-PILOT-RUNBOOK.md)
- Smoke evidence: [DEEP-RESEARCH-PILOT-SMOKE-EVIDENCE-2026-03-31.md](D:/project/research-agentic/deer-flow/docs/DEEP-RESEARCH-PILOT-SMOKE-EVIDENCE-2026-03-31.md)
- Final report: [SPRINT-1-DEEP-RESEARCH-PILOT-FINAL-REPORT-2026-03-31.md](D:/project/research-agentic/deer-flow/docs/SPRINT-1-DEEP-RESEARCH-PILOT-FINAL-REPORT-2026-03-31.md)

Representative operator records:

- [v13 result](D:/project/research-agentic/deer-flow/backend/.deer-flow/pilots/deep-research/requests/smoke-20260331-v13/result.json)
- [v14 result](D:/project/research-agentic/deer-flow/backend/.deer-flow/pilots/deep-research/requests/smoke-20260331-v14/result.json)
- [v15 result](D:/project/research-agentic/deer-flow/backend/.deer-flow/pilots/deep-research/requests/smoke-20260331-v15/result.json)
- [v16 result](D:/project/research-agentic/deer-flow/backend/.deer-flow/pilots/deep-research/requests/smoke-20260331-v16/result.json)
- [v17 result](D:/project/research-agentic/deer-flow/backend/.deer-flow/pilots/deep-research/requests/smoke-20260331-v17/result.json)
