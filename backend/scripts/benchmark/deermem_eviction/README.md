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

The deterministic grader (`grading.py`), the resumable live QA runner (`qa.py`, `provider.py`, `runner.py`), and the blind grading/statistics report (`report.py`, `stats.py`) are implemented; all are documented below. Both policies receive fresh calls with the same `max_tokens=2048`; the historical optimization that reused a 1024-token confidence baseline is not reproduced.

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

The CLI never downloads LongMemEval. The pinned file is `longmemeval_oracle.json` (about 15 MB) in the public, ungated Hugging Face dataset repository [`xiaowu0162/longmemeval-cleaned`](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned); no account or token is needed. Download it once at the pinned revision and expose its path locally:

```bash
export LONGMEMEVAL_ORACLE_PATH=/absolute/path/to/longmemeval_oracle.json
curl -L -o "$LONGMEMEVAL_ORACLE_PATH" \
  "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/98d7416c24c778c2fee6e6f3006e7a073259d48f/longmemeval_oracle.json"
shasum -a 256 "$LONGMEMEVAL_ORACLE_PATH"
# expected: 821a2034d219ab45846873dd14c14f12cfe7776e73527a483f9dac095d38620c
```

If `huggingface.co` is not reachable from your network, the same `/datasets/.../resolve/<revision>/...` path works through a Hugging Face mirror (for example, replace the host with `hf-mirror.com`), and `huggingface-cli download xiaowu0162/longmemeval-cleaned longmemeval_oracle.json --repo-type dataset --revision 98d7416c24c778c2fee6e6f3006e7a073259d48f` is equivalent. Whatever the source, every command rejects a file whose hash differs from the pinned value, so a wrong or modified download cannot pass silently. The dataset itself and prepared text-bearing pools belong outside the repository or under ignored local directories.

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

The runner resolves credentials only from the two environment variables named in the config and fails before touching the dataset when either is missing. Model, temperature, `max_tokens`, stream, timeout, retry attempts, and worker count all come from the versioned config; both policies use identical settings. Each row is written to `responses/<case>__<policy>.json` as soon as its call succeeds, so rerunning the same command resumes a partial run without repeating completed calls. `qa_run.json` binds the output directory to the full protocol identity — the SHA-256 of the config, both manifests, the answer prompt, and the dataset — and rejects resumption when any of them changed. A stored row is reused only when its row identity, kept facts, and `request_fingerprint` all match the task recomputed from the current protocol; a row whose fingerprint no longer matches is re-called rather than silently reused. Row files contain the prediction and non-secret metadata only — never questions, reference answers, memory content, credentials, or response headers.

Grade a completed answer run and write the public QA results (no provider calls):

```bash
PYTHONPATH=. uv run python -m scripts.benchmark.deermem_eviction grade-qa \
  --dataset "$LONGMEMEVAL_ORACLE_PATH" \
  --output-dir /tmp/deermem-eviction-qa-run
```

Grading happens through `grade_answer(prediction, reference)` — two strings, no policy identity — and is joined back to policies only afterwards through stable row IDs. Before grading, the command verifies (read-only) that the run marker's five protocol artifact hashes match the current config, manifests, prompt, and dataset, recomputes the deterministic selector output and every task's request fingerprint, and rejects any answer row whose kept facts, capacity, policy, or stored fingerprint disagree with the recomputed protocol; it refuses to proceed while any of the 90 rows is missing. A published `qa.rows.jsonl` therefore certifies that its predictions were produced under the exact protocol being graded, not under an earlier serialization.

## Deterministic reconstruction

Official samples are independently recomputed from the pinned dataset rather than merely checked for existence. For each of the two eligible question types, the loader applies the published exclusions, sorts by `question_id`, and selects the first 20. Consecutive groups of five are assigned according to the manifest's explicit `scenario_order` field.

Evidence extraction iterates `haystack_sessions`. Within each session it selects turns marked `has_answer`; when a session contains no marked turn, it falls back to user turns. Each rendered session is prefixed with the historical `SESSION {id} AT {date}` line — the exact byte representation matters, because evidence-length filters apply to this final rendered value and the 700-character distractor-bank bound decides bank membership (the cross-check in #4810 caught a divergent prefix format precisely this way).

The distractor bank contains the first 40 eligible `single-session-user` and `single-session-preference` records sorted by question ID. A case offset is derived from the first four bytes of:

```text
sha256("deermem-medium-v1:{case_id}")
```

Nine consecutive records are selected with wraparound. Pool facts carry the historical protocol fact IDs: the support fact is `gold_{case}` and distractor `i` (0-based, in bank-draw order) is `d_{case}_{i}_{source}`. Facts are sorted by these IDs before they enter the production selector and before prompt rendering, so the selector's stable input-order tie break reproduces the historical tie-break exactly (distractors in draw order first, the support fact last), and the rendered `STORED MEMORY` joins fact blocks with a blank line. Access metadata uses the fixed evaluation clock, so no wall-clock decay can change a rerun.

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

`grade-qa` adds three publishable files to a completed answer run and refuses to overwrite them:

- `qa.rows.jsonl` contains one graded row per case and policy: IDs, scenario/source, kept-fact metadata, the model's prediction, the grade with its deciding rule, the grader version, and non-secret response metadata.
- `qa.summary.json` reports accuracy by source, scenario, and policy; the summary never folds official scenarios and synthetic corrections into one figure. The only combined figure is the explicitly labeled `overall` suite in `qa.stats.json`, reported alongside — never instead of — the separate official and synthetic suites.
- `qa.stats.json` reports the exact paired McNemar test and the seeded paired bootstrap difference (`hybrid-v1` minus `confidence`) for the official, synthetic, and overall suites, using the statistics parameters pinned in the config.

Full provider requests, dataset text, and prepared pools must remain in ignored local directories. Provider response headers must never be persisted because they can contain sensitive or account-specific data.

## Model addressing

The historical protocol disclosed in #4789 recorded the answer model as `deepseek/deepseek-v4-flash`, an aggregator-style namespace. This evaluation calls the same underlying model (DeepSeek-V4-Flash-0731, released before the historical run) directly through DeepSeek's official OpenAI-compatible API, whose canonical ID is `deepseek-v4-flash`; the config pins that ID. The model actually serving each call is recorded from the provider response in every answer row as `response_model`.

## Published live QA results

`results/pr4789-reproduction-v1/` contains the published artifacts of the equal-budget live run executed at repository revision `01f99d61` (2026-08-18, DeepSeek official API, `deepseek-v4-flash`), after the evidence rendering, the historical fact-ID scheme, and the prompt serialization identified in the artifact cross-check were all adopted: `qa_run.json` (provenance), `qa.rows.jsonl` (90 graded rows), `qa.summary.json`, and `qa.stats.json`. Earlier live runs executed under divergent serializations were discarded entirely rather than partially reused. The offline suite verifies that the published statistics are recomputable from the published rows.

QA accuracy at capacity 7 with identical settings for both policies:

| Suite | `confidence` | `hybrid-v1` | Exact McNemar p | Accuracy difference (95% CI) |
| --- | ---: | ---: | ---: | --- |
| 40 official | 23/40 | 35/40 | 0.0018 | +0.300 [+0.150, +0.450] |
| 5 synthetic corrections | 1/5 | 5/5 | 0.1250 | +0.800 [+0.400, +1.000] |
| 45 overall | 24/45 | 40/45 | 0.0001 | +0.356 [+0.200, +0.511] |

Scenario breakdown: `confirmation_help` 3/10 vs 10/10, `access_help` 3/10 vs 9/10, `confidence_control` 8/10 vs 7/10, `noisy_signal_control` 9/10 vs 9/10, synthetic corrections 1/5 vs 5/5. The confidence control is the one scenario where `hybrid-v1` scored below the confidence baseline in this run; it is reported separately and not folded into any other metric.

Decomposing the discordant cells from the published rows: `hybrid-v1` lost exactly one case against the baseline (`1cea1afa`, confidence-control), and its support fact was retained, so it is not an eviction failure — the model abstained with `INSUFFICIENT` despite the retained support. The policies retain different distractor sets, which nudges answer phrasing and abstention; the grader remains frozen and the cell is reported as-is.

Both totals sit well above the historical `14/45` vs `23/45`, primarily because the historical confidence baseline was limited to 1024 output tokens while this run gives both policies the same 2048-token budget. The run consumed 86,342 input and 12,340 output tokens across the 90 calls.

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
