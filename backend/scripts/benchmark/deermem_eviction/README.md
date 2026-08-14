# DeerMem Capacity-Eviction Evaluation

This directory makes the controlled comparison behind DeerMem's opt-in `hybrid-v1` capacity policy reproducible. It depends on [deer-flow#4789](https://github.com/bytedance/deer-flow/pull/4789), which implements the remediation proposed after the confidence-only eviction flaw reported in [deer-flow#4641](https://github.com/bytedance/deer-flow/issues/4641).

The evaluation calls the production `select_facts_for_capacity()` function. It does not copy the scoring implementation and does not introduce another eviction strategy.

## Current scope

The first stage is entirely offline:

- pins the cleaned LongMemEval oracle file by repository revision and SHA-256;
- commits only the 40 official question IDs, not the upstream questions, answers, or histories;
- commits the five independently authored synthetic correction guards disclosed in #4789;
- reconstructs each 10-fact pool deterministically;
- compares `confidence` and the production `hybrid-v1` policy at capacities 5, 7, and 9;
- writes metadata-only row results that are safe to publish.

The live QA runner and deterministic grader are intentionally not part of this first scaffold. They will use the fixed answer prompt and provider environment-variable names already recorded in the config. Both policies must be rerun with the same `max_tokens=2048`; the historical optimization that reused a 1024-token confidence baseline will not be reproduced.

## Pinned inputs

| Input | Value |
| --- | --- |
| Dataset | `xiaowu0162/longmemeval-cleaned` |
| Revision | `98d7416c24c778c2fee6e6f3006e7a073259d48f` |
| File | `longmemeval_oracle.json` |
| SHA-256 | `821a2034d219ab45846873dd14c14f12cfe7776e73527a483f9dac095d38620c` |
| Official cases | 40 fixed IDs: 20 `knowledge-update`, 20 `temporal-reasoning` |
| Synthetic cases | 5 correction guards |
| Pool | 1 support fact + 9 deterministic distractors |
| Capacities | 5, 7, 9; QA capacity 7 |
| Evaluation clock | `2026-08-13T00:00:00Z` |

The CLI never downloads LongMemEval. Obtain the pinned file separately and expose its path locally:

```bash
export LONGMEMEVAL_ORACLE_PATH=/absolute/path/to/longmemeval_oracle.json
shasum -a 256 "$LONGMEMEVAL_ORACLE_PATH"
```

The command rejects any file whose hash differs from the pinned value. The dataset itself and prepared text-bearing pools belong outside the repository or under ignored local directories.

## Commands

Run all commands from `backend/`.

Validate the committed config, manifests, and prompt without an upstream dataset:

```bash
PYTHONPATH=. uv run python -m scripts.benchmark.deermem_eviction validate-contracts
```

Validate the dataset hash, recompute the declared sample-selection rule, build the distractor bank, and prepare all 45 cases:

```bash
PYTHONPATH=. uv run python -m scripts.benchmark.deermem_eviction validate \
  --dataset "$LONGMEMEVAL_ORACLE_PATH"
```

Run deterministic capacity selection without any provider calls:

```bash
PYTHONPATH=. uv run python -m scripts.benchmark.deermem_eviction run-policy \
  --dataset "$LONGMEMEVAL_ORACLE_PATH" \
  --output-dir /tmp/deermem-eviction-policy-run
```

The command refuses to overwrite an existing run. Use a new output directory for every run.

## Deterministic reconstruction

Official samples are independently recomputed from the pinned dataset rather than merely checked for existence. For each of the two eligible question types, the loader applies the published exclusions, sorts by `question_id`, and selects the first 20. Consecutive groups of five are assigned according to the manifest's explicit `scenario_order` field.

Evidence extraction iterates `haystack_sessions`. Within each session it selects turns marked `has_answer`; when a session contains no marked turn, it falls back to user turns. Each rendered session is prefixed with its session ID and date. Evidence-length filters apply to this final rendered value.

The distractor bank contains the first 40 eligible `single-session-user` and `single-session-preference` records sorted by question ID. A case offset is derived from the first four bytes of:

```text
sha256("deermem-medium-v1:{case_id}")
```

Nine consecutive records are selected with wraparound. Facts are sorted by ID before they enter the production selector, making its stable input-order tie break equivalent to the published score-then-ID rule. Access metadata uses the fixed evaluation clock, so no wall-clock decay can change a rerun.

At capacity 7, the offline result reproduces the disclosed support-retention totals:

| Suite | `confidence` | `hybrid-v1` |
| --- | ---: | ---: |
| 40 official + 5 synthetic | 27/45 | 45/45 |

This is a deterministic selector result, not evidence that production reinforcement detection or query access heat is unbiased. The eventual QA report must keep official, synthetic-correction, and noisy-signal results separate.

## Output contract

`run-policy` creates three files:

- `run.json` records the git state, immutable dataset identity, evaluation clock, capacities, and SHA-256 values for config, manifests, and prompt.
- `policy.raw.jsonl` contains one row per case, capacity, and policy. Rows include fact IDs, kept/evicted IDs, score components, support retention, and correction reservation. They never include fact content, questions, or reference answers.
- `summary.json` aggregates support retention by source, scenario, capacity, and policy. Synthetic corrections are not folded into an official-only metric.

Full provider requests, dataset text, and prepared pools must remain in ignored local directories. Provider response headers must never be persisted because they can contain sensitive or account-specific data.

## Historical-result caveats

The row-level artifacts disclosed in #4789 corrected the PR text's noisy-signal QA result from `5/10 vs 5/10` to `5/10 vs 6/10`. They also showed that the historical confidence rows used a 1024-token baseline, while hybrid rows used 2048 tokens and new calls. The follow-up live run will therefore:

1. rerun both policies rather than reuse the historical baseline;
2. use the same model, prompt, 2048-token budget, retry policy, and concurrency;
3. blind the grader to policy identity;
4. save public row-level outputs without upstream dataset text;
5. report official and synthetic statistics separately.

## Tests

The default tests are offline and use only synthetic LongMemEval-shaped rows:

```bash
PYTHONPATH=. uv run pytest tests/test_bench_deermem_eviction_*.py -q
```

They cover config and manifest contracts, prompt hashing, dataset-integrity rejection, evidence extraction, distractor filtering, deterministic pool construction, production selector behavior, correction reservation, public-result redaction, and overwrite protection.
