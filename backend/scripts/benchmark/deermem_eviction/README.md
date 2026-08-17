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

The deterministic grader (`grading.py`) and the resumable live QA runner (`qa.py`, `provider.py`, `runner.py`) are implemented; both are documented below. Both policies receive fresh calls with the same `max_tokens=2048`; the historical optimization that reused a 1024-token confidence baseline is not reproduced.

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

Call the configured answer provider for both policies at the QA capacity (45 cases x 2 policies = 90 calls on a fresh run):

```bash
export DEERMEM_EVAL_ANSWER_API_KEY=...   # never committed or logged
export DEERMEM_EVAL_ANSWER_BASE_URL=...  # OpenAI-compatible endpoint
PYTHONPATH=. uv run python -m scripts.benchmark.deermem_eviction run-qa \
  --dataset "$LONGMEMEVAL_ORACLE_PATH" \
  --output-dir /tmp/deermem-eviction-qa-run
```

The runner resolves credentials only from the two environment variables named in the config and fails before touching the dataset when either is missing. Model, temperature, `max_tokens`, stream, timeout, retry attempts, and worker count all come from the versioned config; both policies use identical settings. Each row is written to `responses/<case>__<policy>.json` as soon as its call succeeds, so rerunning the same command resumes a partial run without repeating completed calls; `qa_run.json` binds the output directory to one config identity and rejects resumption with a different config. Row files contain the prediction and non-secret metadata only — never questions, reference answers, memory content, credentials, or response headers.

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

## Deterministic grading

`grading.py` implements the disclosed grader as a pure, offline module versioned as `deterministic-overlap-v1`; the config pins that identity via `qa.grader_version`, and `validate-contracts` rejects a mismatch. The grader is blind by construction: `grade_answer(prediction, reference)` accepts only the two answer strings and never a policy identity.

Normalization lowercases, replaces every non-alphanumeric character with a space, and maps the English number words one through ten and fifteen to digits. Rules apply in order:

1. reject an empty prediction or the exact `INSUFFICIENT` sentinel;
2. accept exact normalized-token equality;
3. accept containment of one token sequence in the other as a contiguous subsequence (token-level, so `5` never matches inside `25`);
4. accept a prediction whose integer tokens all fall inside an explicit `ranging from X ... to Y` reference range;
5. reject conflicting integer tokens when both sides contain integers;
6. otherwise require at least 60% unique non-stopword token overlap in both directions.

The disclosure in #4789 did not publish an exact stopword list, so the list committed in `grading.py` is a fixed part of this grader version: common English function words, with `yes`, `no`, and `not` deliberately excluded because negation can be the entire answer. Changing the list or any rule requires a new `grader_version`.

Before freezing, the grader was cross-checked locally against all 90 historical `(prediction, reference)` pairs disclosed in #4789 — the saved QA grades for both policies across 45 cases — and reproduced every historical grade exactly, with no per-result tuning afterward.

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

They cover config and manifest contracts, prompt hashing, dataset-integrity rejection, evidence extraction, distractor filtering, deterministic pool construction, production selector behavior, correction reservation, public-result redaction, overwrite protection, and every grading rule with its edge cases.
