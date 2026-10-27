# Session continuity evaluation

Historical research prototype motivating the opt-in implementation in this PR. The measurements below were completed before production integration; they are not measurements of the implementation shipped here. The reported baseline uses the exact installed default summarization prompt, not the entire DeerFlow runtime. The protocol deliberately enables forced compaction to examine loss/recovery under context pressure.

## Published package

This directory freezes the original protocol, replay scripts, prompts, manifests,
aggregate results and per-case score metadata (`results/case-scores.json`). It does
not distribute dataset questions/answers, source histories, provider payloads,
response/vector caches, private endpoint settings or local workspaces. References
in the historical report to those paths describe the original local run. To
recompute every result, obtain the pinned public dataset and evaluator source
recorded in `input-sources.json`, then run the scripts manually. Network
execution requires your own endpoint configuration. Successful historical rows
were not rerun for this PR. Raw-result SHA-256 values bind the published score
projection to the original local evidence; they do not make omitted payloads
publicly inspectable. `report.py` recomputes from a complete local replay, not
from the reduced score export.

[Implementation validation](VALIDATION.md) records the actual feature checks and the clean-base comparison.

The production integration is documented in
[task-continuity.md](../../task-continuity.md). Its tests and manual live check
are separate evidence from this prototype's A/B/C/D tables.

For an offline consistency check of the published counts (without omitted raw data), run `python verify_published_scores.py`. This checks the original and extended-budget tables, including the two missing public rows; it does not re-grade model answers.

## Runtime

Python 3.12 with `httpx`, `numpy`, `tiktoken`, `pytest` (plus `matplotlib` for plotting); the existing DeerFlow backend environment was used. Credentials and addresses are supplied through `--endpoints /path/to/private.json`, outside this directory. The JSON keys are `llm_base`, `llm_model`, `embedding_base`, `embedding_model`, `embedding_key`. Bases include `/v1`. LLM requests have no Authorization header. Never publish the runtime configuration.

## Run

1. Obtain the pinned dataset and evaluator URLs from `input-sources.json`, put them in `data/longmemeval_s_cleaned.json` and `data/official_evaluate_qa.py`, and verify both SHA-256 values.
2. `python prepare.py` and `python task_cases.py` freeze the deterministic case sets.
3. `python -m pytest -q test_experiment.py` checks source isolation, gold exclusion, exact reads, budgets, and deterministic acceptance.
4. `python public_eval.py --endpoints /path/to/private.json --split dev --limit 2`
5. `python task_eval.py --endpoints /path/to/private.json --split dev`
6. `python public_eval.py --endpoints /path/to/private.json --split test --concurrency 12 --case-concurrency 6`
7. `python task_eval.py --endpoints /path/to/private.json --split test --concurrency 8 --case-concurrency 4`
8. `python report.py`

The delivered report also includes `python oracle_eval.py --endpoints /path/to/private.json` and `python known_goal_eval.py --endpoints /path/to/private.json`, governed by their separate diagnostic protocol files. The first reads only oracle source sessions; the second evaluates the 12 known-goal variants. `runtime-versions.json` records the actual package versions and prompt hashes.

Final conclusions are bound to the summary hash in `conclusion-metadata.json`. If a new experiment changes the results, regenerate `CONCLUSIONS.md` and its identity metadata; the reporter refuses to silently reuse stale conclusions.

The actual public run was resumed with 24 request slots / 12 concurrent cases to improve throughput; successful cached responses were reused. See `operational-events.json` and the original/expanded run logs. An operationally failing row stays in the selected denominator and is reported separately from conditional answer quality.

After the user requested more execution headroom, `python continue_tasks.py --endpoints /path/to/private.json --watch` continues only task trajectories that hit the original step/context cap. Original model calls must be found in the cache and the replayed tool prefix must match exactly; new model calls begin after the old stopping point. The extended allowance is 24 steps and 192,000 cumulative proxy context tokens. Four repeated actions or four failed validations without new historical evidence stop a stagnant loop. Original results and artifacts remain under `results/tasks` and `workspaces`; extensions are under `results/continued` and `workspaces-continued`. This is a separately reported, user-requested post-hoc condition.

Run `python audit_results.py --full --endpoints /path/to/private.json` after completion to verify immutable history hashes, actual written files, response/vector caches, result identities, and absence of private endpoint/token literals in deliverable text. `python plot_results.py` refuses to generate the final comparison before the evaluation has settled.

Network execution is an explicitly authorized manual experiment. Unit tests never call the network. Model requests are cached by complete payload and endpoint hash; memory artifacts additionally bind history, prompts and protocol. Keep failed/truncated generations and report them. Any changed protocol must be separately named and affected rows regenerated; do not select results by performance.

## What this can establish

- Public history QA: can each representation find/use the required past information after repeated compression?
- Controlled continuation: can an actor recover settings and actually write/validate a manifest, instead of merely claiming success?
- C versus D: does adding dense retrieval to the SAME history, chunks, scope and return budget help beyond keyword search?

It does not establish general coding-agent reliability, production restart recovery, a merged feature, or an official benchmark leaderboard score. The small stratified public sample is exploratory. Task fixtures are authored simulations with fixed history prefixes followed by live native tool calls, not naturally occurring full trajectories. A/B/C have the same hard context cap but consume different amounts; the report shows this overhead rather than attributing all added information to superior representation.

The compact summary/notebook output limits are intentional pressure-test conditions and frequently cause length-limited generations. They are **not** DeerFlow's complete production defaults, and the observed A score must not be presented as its normal deployed performance. Extending actor execution does not undo prior information loss from these compactions; both mechanisms are reported separately.

The original public dataset includes reference/evidence metadata. `prepare.py` writes model-facing records and scorer-only gold to separate directories. Neither notes nor summaries receive the final question, answer or evidence labels. Task acceptance values stay inside the verifier; failed validation exposes no expected values.

The public replay preserves the dataset-provided session order and dates. In 16 of the 42 selected rows this order is not monotonic by date; no post-hoc sorting was applied. Public QA therefore measures published-order historical recall, while the controlled tasks provide ordered three-stage continuation histories.
