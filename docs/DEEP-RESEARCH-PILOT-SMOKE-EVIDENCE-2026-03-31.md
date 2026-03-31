# Deep Research Pilot Smoke Evidence

## Scope

This evidence pack records the post-implementation verification for the Sprint 1 `Deep Research` pilot wrapper.

## Verification Summary

### 1. Unit Tests

Command:

```bash
docker run --rm \
  -v D:/project/research-agentic/deer-flow:/repo \
  -w /repo/backend \
  docker-gateway \
  sh -lc "PYTHONPATH=.:packages/harness /app/backend/.venv/bin/python -m pytest tests/test_deep_research_pilot.py -q"
```

Result:

- `7 passed`

Coverage added by this suite:

- prompt/artifact persistence
- idempotency cache reuse
- heartbeat emission during quiet long tasks
- timeout with usable partial result
- adapter-managed artifact materialization from response markers
- output-profile validation and prompt shaping
- profile-aware short-summary shaping for metadata-heavy operator outputs

### 2. Real Smoke Run

Command:

```bash
docker run --rm \
  --env-file D:/project/research-agentic/deer-flow/.env \
  -e DEER_FLOW_HOME=/repo/backend/.deer-flow \
  -v D:/project/research-agentic/deer-flow:/repo \
  -v D:/project/research-agentic/deer-flow/.home/.claude:/root/.claude:ro \
  -v D:/project/research-agentic/deer-flow/.home/.codex:/root/.codex:ro \
  -w /repo \
  docker-gateway \
  sh -lc "/app/backend/.venv/bin/python scripts/run_deep_research_pilot.py --model gpt-4o-goclaw-bridge --objective 'Using the provided context, create a Sprint 1 implementation brief focused on scope, guardrails, and next steps.' --context-file /repo/docs/FINAL-DECISION-HYBRID-SYSTEM-2026-03-31.md --expected-output 'Implementation brief with scope, guardrails, and next steps' --request-id smoke-20260331-v7 --idempotency-key smoke-20260331-v7 --thread-id deep-research-smoke-20260331-v7 --timeout-seconds 240 --heartbeat-interval-seconds 15 --heartbeat-start-after-seconds 15"
```

Result:

- `status`: `completed`
- `request_id`: `smoke-20260331-v7`
- `thread_id`: `deep-research-smoke-20260331-v7`
- `duration_seconds`: `155.831`
- `token_usage.total_tokens`: `43576`
- `partial_result_available`: `false`

Artifact:

- `backend/.deer-flow/threads/deep-research-smoke-20260331-v7/user-data/outputs/smoke-20260331-v7-executive-brief.md`

Operator traces:

- `backend/.deer-flow/pilots/deep-research/requests/smoke-20260331-v7/result.json`
- `backend/.deer-flow/pilots/deep-research/requests/smoke-20260331-v7/status.json`
- `backend/.deer-flow/pilots/deep-research/requests/smoke-20260331-v7/events.jsonl`
- `backend/.deer-flow/pilots/deep-research/requests/smoke-20260331-v7/pilot-scorecard.md`

## What the Smoke Run Proved

- The adapter produced a final `completed` result with a real Markdown artifact.
- Heartbeats were emitted during a long-running task.
- `request_id`, `thread_id`, and `idempotency_key` were all persisted.
- The scorecard template was generated automatically for operator review.

## Important Finding

The runtime still did **not** write the artifact directly through the model/tool path.

Instead, the model returned the full brief between:

- `EXECUTIVE_BRIEF_MARKDOWN_START`
- `EXECUTIVE_BRIEF_MARKDOWN_END`

The adapter then created the artifact itself. This is visible in:

- `events.jsonl` via `adapter_fallback_artifact_generated`
- `pilot-scorecard.md` via the auto note

This is not a bug in the evidence pack. It is the key architectural lesson from the pilot: the adapter-managed artifact contract is not optional.

## Operational Interpretation

- `Execution path`: viable
- `Tracing path`: viable
- `Artifact contract`: viable with adapter-managed artifact generation
- `Runtime purity`: not yet ideal

Conclusion:

The pilot wrapper is good enough for Sprint 1 because it turns a runtime/tooling mismatch into a usable artifact contract instead of a silent failure.
