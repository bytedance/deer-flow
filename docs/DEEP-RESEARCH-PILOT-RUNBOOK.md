# Deep Research Pilot Runbook

## Purpose

This runbook describes the Sprint 1 DeerFlow-first pilot for one narrow use case: `Deep Research`.

The pilot wrapper lives outside the core runtime and provides:

- adapter v0.1 with `accepted`, `running`, `completed`, `failed`
- `request_id` and `idempotency_key`
- explicit `output_profile` selection for `default`, `founder_memo`, or `operator_memo`
- heartbeat logging for long-running tasks
- timeout handling
- usable partial-result policy
- file-based operator traces under `backend/.deer-flow/pilots/deep-research/`
- an adapter-managed artifact contract that persists the Markdown artifact from the model response

## Core Files

- Runner module: `backend/packages/harness/deerflow/pilot/deep_research.py`
- CLI entrypoint: `scripts/run_deep_research_pilot.py`
- Unit tests: `backend/tests/test_deep_research_pilot.py`

## Operator Output Layout

Each request writes to:

`backend/.deer-flow/pilots/deep-research/requests/<request_id>/`

Files:

- `request.json`: normalized request payload
- `status.json`: latest live state for operators
- `result.json`: final adapter response
- `events.jsonl`: execution trace and heartbeats
- `pilot-scorecard.md`: latency/quality/cost review template

Artifacts are written to:

`backend/.deer-flow/threads/<thread_id>/user-data/outputs/`

## Standard Run Command

From the repository root:

```bash
python scripts/run_deep_research_pilot.py \
  --model gpt-4o-goclaw-bridge \
  --objective "Using the provided context, create a Sprint 1 implementation brief focused on scope, guardrails, and next steps." \
  --context-file docs/FINAL-DECISION-HYBRID-SYSTEM-2026-03-31.md \
  --output-profile founder_memo \
  --expected-output "Implementation brief with scope, guardrails, and next steps" \
  --request-id smoke-20260331-v7 \
  --idempotency-key smoke-20260331-v7 \
  --thread-id deep-research-smoke-20260331-v7 \
  --timeout-seconds 240 \
  --heartbeat-interval-seconds 15 \
  --heartbeat-start-after-seconds 15
```

## Docker Runtime Command

Use this when the backend dependencies only exist inside the Docker image:

```bash
docker run --rm \
  --env-file D:/project/research-agentic/deer-flow/.env \
  -e DEER_FLOW_HOME=/repo/backend/.deer-flow \
  -v D:/project/research-agentic/deer-flow:/repo \
  -v D:/project/research-agentic/deer-flow/.home/.claude:/root/.claude:ro \
  -v D:/project/research-agentic/deer-flow/.home/.codex:/root/.codex:ro \
  -w /repo \
  docker-gateway \
  sh -lc "/app/backend/.venv/bin/python scripts/run_deep_research_pilot.py --model gpt-4o-goclaw-bridge --objective 'Using the provided context, create a Sprint 1 implementation brief focused on scope, guardrails, and next steps.' --context-file /repo/docs/FINAL-DECISION-HYBRID-SYSTEM-2026-03-31.md --output-profile founder_memo --expected-output 'Implementation brief with scope, guardrails, and next steps' --request-id smoke-20260331-v7 --idempotency-key smoke-20260331-v7 --thread-id deep-research-smoke-20260331-v7 --timeout-seconds 240 --heartbeat-interval-seconds 15 --heartbeat-start-after-seconds 15"
```

## Output Profiles

Use `--output-profile` to shape the artifact for the reader:

- `default`: balanced research brief
- `founder_memo`: short, decision-oriented memo with strategic tradeoffs up front
- `operator_memo`: handoff-oriented memo with assumptions, evidence, risks, and next actions spelled out

## Adapter Behavior

### Primary Delivery Path

The standard contract is:

1. the model returns the full brief between:

- `EXECUTIVE_BRIEF_MARKDOWN_START`
- `EXECUTIVE_BRIEF_MARKDOWN_END`

2. the adapter materializes the Markdown file at:

- `backend/.deer-flow/threads/<thread_id>/user-data/outputs/<request_id>-executive-brief.md`

3. the adapter records:

- `adapter_fallback_artifact_generated` in `events.jsonl`
- an auto note in `pilot-scorecard.md`

This is intentional. It is the standard Sprint 1 artifact contract.

## Attachment Handling

The pilot supports both:

- `--attachment` uploads
- `--context-file` inline context

For small text/markdown attachments, the runner also inlines excerpts into the prompt. This reduces failure when the model runtime refuses direct access to uploaded virtual paths.

## Status Contract

The final `result.json` follows this shape:

- `request_id`
- `idempotency_key`
- `thread_id`
- `output_profile`
- `status`
- `short_summary`
- `artifacts`
- `partial_result_available`
- `error_code`
- `error_message`
- `duration_seconds`
- `token_usage`
- `operator_paths`

## Verification Commands

Unit tests:

```bash
docker run --rm \
  -v D:/project/research-agentic/deer-flow:/repo \
  -w /repo/backend \
  docker-gateway \
  sh -lc "PYTHONPATH=.:packages/harness /app/backend/.venv/bin/python -m pytest tests/test_deep_research_pilot.py -q"
```

Static syntax check:

```bash
python -m py_compile backend/packages/harness/deerflow/pilot/deep_research.py backend/tests/test_deep_research_pilot.py scripts/run_deep_research_pilot.py
```

## Review Checklist

After each run, inspect:

- `result.json` for final status and operator paths
- `events.jsonl` for heartbeat cadence and fallback usage
- generated artifact quality
- `pilot-scorecard.md` for human evaluation

## Known Constraints

- The pilot is intentionally single-use-case and DeerFlow-only.
- It does not include OpenClaw bridge, smart routing, or memory sync.
- The adapter currently uses file-based traces, not a full observability stack.
- Artifact generation is adapter-driven by design; direct model-side file creation is not required.
