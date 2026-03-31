# Deep Research Pilot Output Profile Evidence

## Scope

This evidence pack records real-runtime validation for the new `output_profile` contract added to the Sprint 1 Deep Research pilot, including a rerun after fixing profile-aware short-summary shaping.

Validated profiles:

- `founder_memo`
- `operator_memo`

## Verification Method

Both runs were executed in the Docker runtime used by the pilot, with the same adapter contract, tracing, heartbeat, and artifact materialization path as the main Sprint 1 evidence batch.

## Final Validation Batch

The final validation batch uses refreshed request lineage after the summary-shaping fix:

- `profile-20260331-founder-v2`
- `profile-20260331-operator-v2`

## Run 1: Founder Memo

- `request_id`: `profile-20260331-founder-v2`
- `thread_id`: `deep-research-profile-founder-v2`
- `output_profile`: `founder_memo`
- `status`: `completed`
- `duration_seconds`: `67.459`
- `token_usage.total_tokens`: `17914`

Artifact:

- `backend/.deer-flow/threads/deep-research-profile-founder-v2/user-data/outputs/profile-20260331-founder-v2-executive-brief.md`

Operator records:

- `backend/.deer-flow/pilots/deep-research/requests/profile-20260331-founder-v2/result.json`
- `backend/.deer-flow/pilots/deep-research/requests/profile-20260331-founder-v2/events.jsonl`
- `backend/.deer-flow/pilots/deep-research/requests/profile-20260331-founder-v2/pilot-scorecard.md`

Assessment:

- The artifact is clearly decision-oriented.
- It opens with explicit `Decision` and `One-line Rationale`.
- Strategic implications and top risks are prioritized over implementation detail.
- The presence-layer short summary is cleaner and now surfaces the decision signal directly.
- Quality bucket: `usable now`

## Run 2: Operator Memo

- `request_id`: `profile-20260331-operator-v2`
- `thread_id`: `deep-research-profile-operator-v2`
- `output_profile`: `operator_memo`
- `status`: `completed`
- `duration_seconds`: `73.617`
- `token_usage.total_tokens`: `16690`

Artifact:

- `backend/.deer-flow/threads/deep-research-profile-operator-v2/user-data/outputs/profile-20260331-operator-v2-executive-brief.md`

Operator records:

- `backend/.deer-flow/pilots/deep-research/requests/profile-20260331-operator-v2/result.json`
- `backend/.deer-flow/pilots/deep-research/requests/profile-20260331-operator-v2/events.jsonl`
- `backend/.deer-flow/pilots/deep-research/requests/profile-20260331-operator-v2/pilot-scorecard.md`

Assessment:

- The artifact is clearly handoff-oriented.
- It includes execution scope, validation matrix, risks, dependencies, and sequenced next actions.
- It reads like an operator memo rather than a founder decision memo.
- The short summary no longer leaks `Request ID` or other metadata lines into the presence layer.
- Quality bucket: `usable now`

## What This Proves

1. The new `output_profile` contract changes output shape in a meaningful way under real runtime execution.
2. The distinction is not cosmetic:
   - `founder_memo` emphasizes decision, rationale, and strategic risk.
   - `operator_memo` emphasizes execution detail, validation checks, and handoff readiness.
3. The adapter contract remains stable:
   - both runs completed successfully,
   - both emitted heartbeats,
   - both produced a real artifact,
   - both remained traceable by `request_id` and `thread_id`.

## Known Limitations

Both runs still used adapter-managed artifact generation rather than native model-side file creation. This remains acceptable under the current Sprint 1 contract.

Remaining quality issue:

- both summaries are now usable, but they would still benefit from profile-specific truncation thresholds under larger documents.

## Conclusion

`output_profile` is now validated beyond unit tests and revalidated after the summary-shaping fix.

The Deep Research pilot can now generate two materially different artifact shapes for two different operator types without widening scope beyond DeerFlow-only.
