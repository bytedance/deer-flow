# Benchmark recursion profiles

This generator emits a reproducible LangGraph run `config` for long-horizon
evaluations such as GAIA and SWE-bench Lite. It comes from
[issue #2820](https://github.com/bytedance/deer-flow/issues/2820), where runs
often used up the graph step budget before the agent produced a final patch or
answer. It does not run a benchmark harness, call a provider or change any
runtime default.

## Why the limit matters

The Gateway gives every run without an explicit value the top-level
`recursion_limit` from `config.yaml` (default `100`), and clamps any value to
`max_recursion_limit` (default `1000`). A run that reaches its limit ends with
status `error` and `stop_reason: recursion_capped`. See
[Recursion Limits](../../../docs/CONFIGURATION.md#recursion-limits).

A repository-repair task spends many legitimate steps before it writes a patch:
reading the issue, inspecting the layout, reading related files, locating the
implementation and tests, writing a fix, running tests and iterating. The traces
in issue #2820 show 50-80 steps on exploration alone, so a limit of 150 can stop
useful runs before the fix starts.

## Profiles

| Profile | Recursion limit | Use case |
| --- | ---: | --- |
| `gaia` | 150 | GAIA-style multi-step tool-use tasks. |
| `swebench-lite` | 250 | SWE-bench Lite repository-repair tasks. |
| `long-horizon` | 250 | Generic long-horizon DeerFlow evaluations. |

These are starting points, not correctness guarantees. Larger repositories or
subagent-heavy runs may need more headroom. Raising the limit only removes an
artificial stop; it does not fix a loop.

## Run

From `backend/`:

```bash
uv run --locked python -m scripts.benchmark.recursion_profiles --profile swebench-lite
uv run --locked pytest tests/test_bench_recursion_profiles.py -q
```

```json
{
  "recursion_limit": 250
}
```

Add model and mode overrides when a run needs them:

```bash
uv run --locked python -m scripts.benchmark.recursion_profiles \
  --profile swebench-lite --model-name k2.6 --thinking-enabled --plan-mode --subagent-enabled
```

```json
{
  "configurable": {
    "is_plan_mode": true,
    "model_name": "k2.6",
    "subagent_enabled": true,
    "thinking_enabled": true
  },
  "recursion_limit": 250
}
```

Override the profile limit only when the benchmark matrix records the override.
If the target Gateway sets a non-default `max_recursion_limit`, pass it with
`--max-recursion-limit` so the generator checks the override against the real
ceiling:

```bash
uv run --locked python -m scripts.benchmark.recursion_profiles --profile swebench-lite --recursion-limit 300 --max-recursion-limit 500
```

For a direct `/api/langgraph/*` call, put the generated JSON under the request
body's `config` key.

## What to record

Record these fields with every run:

- DeerFlow commit SHA, plus `recursion_limit` and `max_recursion_limit` from the
  Gateway's `config.yaml`.
- Benchmark name and dataset split, pinned by revision.
- Model provider and model name.
- Profile name and the full generated config JSON.
- Sandbox provider and host resources.
- Whether plan mode and subagents were enabled.
- Loop-detection settings.
- The failure class, especially `recursion_capped` and `loop_capped` stops,
  empty patches and network or tool failures.

With this metadata you can tell an underpowered recursion limit apart from
model, tool-use or loop-detection behaviour.

## Relationship to loop detection

The profiles do not change loop-detection thresholds. Use them to remove
recursion-limit noise first, then analyse the remaining failures separately. If
raising the limit mostly turns `recursion_capped` stops into repeated scaffold
files, repeated search scripts or empty patches, treat that as loop or tool-use
evidence rather than a reason to keep raising the limit.
