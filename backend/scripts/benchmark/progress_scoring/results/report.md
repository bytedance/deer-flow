# Synthetic progress-detection policy replay

This is a deterministic policy boundary check, not evidence of model scoring accuracy or a mainline adoption decision. All traces and scores are hand-authored. No model or real tool runs.

The adapters use the production hooks in separate source checkouts. All three policies are evaluated independently with pinned parameters. The replay continues counterfactually after stops; it does not measure whether an agent follows a hint.

| Policy | TP / stalled cases | FP / legitimate cases | TPR | FPR | Cases with hard stop |
| --- | --- | --- | --- | --- | --- |
| loop_detection | 5 / 8 | 2 / 3 | 62.5% | 66.7% | 7 |
| progress_scoring | 4 / 8 | 0 / 3 | 50.0% | 0.0% | 0 |
| tool_progress | 2 / 8 | 0 / 3 | 25.0% | 0.0% | 0 |

Detection means a warn, block, hard_stop, or replan_required audit transition. eval_noncompliance is diagnostic and does not count. Labels apply to the entire case; each case has one vote. Fixture selection is deliberately adversarial and these rates are not population estimates.

| Case | Label | Loop first hint / stop | Tool progress first hint / block | Candidate first hint / stop |
| --- | --- | --- | --- | --- |
| identical_calls | stalled | 3 / 5 | 4 / — | 3 / — |
| varied_no_results | stalled | — / — | 3 / — | 3 / — |
| cross_tool_identical | stalled | — / — | — / — | 3 / — |
| distinct_stagnation | stalled | — / — | — / — | — / — |
| same_call_distinct_stagnation | stalled | 3 / 5 | — / — | — / — |
| long_bash_artifacts | legitimate | 30 / 50 | — / — | — / — |
| long_mcp_resources | legitimate | 30 / 50 | — / — | — / — |
| hypothesis_elimination | legitimate | — / — | — / — | — / — |
| optimistic_scores | stalled | 3 / 5 | — / — | — / — |
| missing_evaluations | stalled | 3 / 5 | — / — | — / — |
| one_noisy_result | stalled | 3 / 5 | — / — | 3 / — |

## Protocol overhead

The fixed candidate instruction uses 188 cl100k_base tokens per model call. Token counts cover content only, excluding provider message envelopes, reasoning, prompt caching, and historical score retransmission (the candidate strips scores). The protocol is also sent on the initial call; a trace with N tool results measures N+1 protocol injections.

| Case | Protocol calls | Protocol input tokens | Score output tokens | Hint input tokens |
| --- | --- | --- | --- | --- |
| identical_calls | 9 | 1692 | 264 | 86 |
| varied_no_results | 9 | 1692 | 264 | 86 |
| cross_tool_identical | 9 | 1692 | 264 | 86 |
| distinct_stagnation | 9 | 1692 | 264 | 0 |
| same_call_distinct_stagnation | 9 | 1692 | 264 | 0 |
| long_bash_artifacts | 61 | 11468 | 1980 | 0 |
| long_mcp_resources | 61 | 11468 | 1980 | 0 |
| hypothesis_elimination | 9 | 1692 | 264 | 0 |
| optimistic_scores | 9 | 1692 | 264 | 0 |
| missing_evaluations | 9 | 1692 | 0 | 0 |
| one_noisy_result | 9 | 1692 | 264 | 86 |

Without a verified local tokenizer file, token fields are null; exact UTF-8 byte counts remain in report.json. No tokenizer or dataset is downloaded by the runner.

## Incremental coverage

The union of the independent baseline detections covers 6 of 8 stalled cases. The candidate uniquely detects: cross_tool_identical. This is a union of fixed-trace detections, not a composed middleware run: earlier baseline stops can prevent later candidate scoring.

## Decision limits and next evidence

Distinct result hashes veto the current candidate even with zero task_progress. The optimistic-score and missing-evaluation cases show its dependence on self-score compliance. Long productive cases still hit the raw-frequency guard; this candidate does not suppress it.

Before runtime adoption, replay provenance-reviewed real traces with independent task-progress labels and model-generated scores. Measure scoring calibration/compliance across pinned models, overhead with actual provider tokenizers, end-to-end latency, intervention usefulness, and provider message validity. This offline report measures none of those outcomes.

See report.json for source pins, package versions, fixture/config/runner hashes, and every observed audit transition.
