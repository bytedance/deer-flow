# Progress-detection policy benchmark (#2805)

This draft benchmark responds to the benchmark-first review of [PR #5851](https://github.com/bytedance/deer-flow/pull/5851#pullrequestreview-5339033472).
It adds no runtime middleware, feature flag, model call, or Gateway behavior.
It replays eleven **synthetic, hand-scored** traces through the actual
`LoopDetectionMiddleware`, `ToolProgressMiddleware`, and the candidate from
PR #5851. It is a reproducible policy boundary check, not proof that a model can
score task progress accurately or that the candidate should ship.

## Source preparation

The baseline is pinned to upstream main at
`63e399f2bdf6ad1269724c10cfc98bb40c7550d3`; the candidate is pinned to
`974f8fc6a5edce3b1ee5aa478351b6f3cc572ea9`. The candidate runtime is **not copied
or installed into this PR**. Supply an explicit local Git checkout of that
revision. From the repository root, for example:

```bash
git fetch https://github.com/bytedance/deer-flow.git refs/pull/5851/head
git worktree add --detach ../deer-flow-progress-candidate 974f8fc6a5edce3b1ee5aa478351b6f3cc572ea9
```

`config.json` pins constructor parameters and SHA-256 values of directly used
policy sources (UTF-8 with normalized LF newlines, for Windows/POSIX parity).
The baseline runtime tree must match the configured upstream revision, even
when running from a later benchmark-only commit.
The runner rejects changed pinned files, a different candidate HEAD, and dirty
runtime sources/lockfiles. It never fetches code or datasets automatically.
The candidate is trusted operator-supplied Python code; replay imports it.

## Offline replay

Install this checkout's backend dependencies with `uv sync --locked`. Both
source arms use that same Python/dependency environment; this isolates source
differences rather than comparing different dependency locks. From `backend/`:

```bash
uv run python -m scripts.benchmark.progress_scoring \
  --candidate-root ../../deer-flow-progress-candidate \
  --output-dir ../.deer-flow/progress-benchmark-run
uv run pytest tests/test_bench_progress_scoring.py -q
```

The output directory must be new. It contains `report.json` (all decisions,
parameters, exact content bytes, revisions and hashes), `report.md`, and
`sources.json` (every loaded DeerFlow source path and normalized SHA-256).
Paths are relative to each checkout, so no local usernames, provider payloads,
credentials, or response headers enter the report. The fixed clock and seed are
recorded; neither randomness nor wall-clock latency is used by replay.

Default tests need neither network, a provider, nor the candidate checkout.
To exercise the pinned candidate in the optional offline regression:

```bash
PROGRESS_BENCH_CANDIDATE_ROOT=/absolute/path/deer-flow-progress-candidate \
  uv run pytest tests/test_bench_progress_scoring.py -q
```

In PowerShell, set `$env:PROGRESS_BENCH_CANDIDATE_ROOT` before the pytest command.

## Token accounting

Without a local tokenizer vocabulary, token fields are explicitly `null`;
exact UTF-8 byte counts are always measured. To count content tokens, obtain
`cl100k_base.tiktoken` separately from the canonical tiktoken encoding asset,
then provide it explicitly:

```bash
uv run python -m scripts.benchmark.progress_scoring \
  --candidate-root ../../deer-flow-progress-candidate \
  --tokenizer-file /absolute/path/cl100k_base.tiktoken \
  --output-dir ../.deer-flow/progress-benchmark-token-run
```

The vocabulary must match SHA-256
`223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7`.
It is loaded into a temporary verified local tiktoken cache. The runner does
not download tokenizers. Scores use fixed compact JSON; model-generated
formatting and evidence lengths will have different costs. Counts exclude
provider role/message envelopes, prompt caching, reasoning, and latency.
Baseline intervention text is measured separately from candidate protocol
input and score output. A trace with N tool-result steps has N+1 protocol
injections because the initial model call receives the instruction too.

## Fixtures and labels

`fixtures.json` version-controls goals, exact output templates, argument
templates, structured `deerflow_tool_meta`, task-stagnation labels, scores, and
trace lengths. Every step contains one call and result. Template expansion is
deterministic and annotations are independent of the policy decisions.

The first five scenario families correspond to the review's table:

1. Identical call/arguments/results, including a long enough result for Jaccard.
2. Varied arguments with recoverable `no_results` metadata.
3. Different tools with byte-identical results (one call per tool in the trace).
4. Distinct successful results with high usefulness but no task progress,
   including a variant that repeats the exact call.
5. Legitimate long bash/artifact and MCP/resource workflows, plus hypothesis
   elimination with low usefulness but positive task progress.

Additional cases pin optimistic self-scoring, omitted evaluation blocks, and
one noisy result. Scores are **hand-authored hypothetical model outputs**, not
collected model judgments. Repeated informative output is intentionally longer
than the baseline Jaccard minimum; short-result cases also show that boundary.

## Interpretation

Adapters call real `after_model`, `wrap_tool_call`, and `wrap_model_call` hooks,
not a copied approximation of their policies. A small recorder observes
production audit transitions; warnings are drained through the real request
wrappers. Each case gets fresh middleware/run state. Workers run in separate
processes, resolve imports against their designated checkout, and reject any
DeerFlow import escaping that root.

Loop detection observes the proposed call before results; tool progress
observes the stamped result; candidate scoring observes the post-result
response. The reported step is the same call/result ordinal, but these hook
phases differ. First hint/stop is a detection time, not successful replanning.

All three arms replay the entire fixed trace independently, even after a
hard stop. Later events and token totals are **counterfactual**: no real agent
continues after a blocked call or changes course after a hint. The report also
computes the union of baseline detections and candidate-only detections, but
this does not simulate a composed middleware chain. `eval_noncompliance` is
diagnostic and never counted as a stagnation intervention.

TPR and FPR use explicitly reported case denominators; each case gets one vote.
Adversarial fixture selection means they are not production population rates.
The raw frequency stop remains a baseline behavior, not a resource-budget
change proposed by this benchmark. Candidate scores cannot override it.

The [committed report](results/report.md) documents the first offline run.
Remaining decision-gate work includes provenance-reviewed real traces,
independent labels, model-generated scores with pinned model IDs/prompts and
inference settings, calibration/compliance, real provider token overhead and
latency, intervention quality, and provider message validity. This PR stays a
draft while those measurements and fixture representativeness are reviewed.
