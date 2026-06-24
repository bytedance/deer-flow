# Benchmark Recursion Profiles

This guide records reproducible run-config defaults for long-horizon DeerFlow evaluations. It is based on the discussion in [issue #2820](https://github.com/bytedance/deer-flow/issues/2820), where SWE-bench Lite and GAIA runs often exhausted the graph step budget before the agent reached a final patch or answer.

## Why Recursion Limits Matter

LangGraph's native `recursion_limit` default is 25. DeerFlow's Gateway and IM-channel paths raise that to 100, but direct `/api/langgraph/*` clients and external benchmark harnesses must set the limit explicitly.

For repository-repair benchmarks, a run can spend many graph steps on legitimate exploration before writing a patch:

1. Read the issue.
2. Inspect the repository layout.
3. Read related files.
4. Locate the implementation and tests.
5. Write a fix.
6. Run tests.
7. Debug and iterate.

The issue #2820 traces indicate that SWE-bench tasks can spend 50-80 steps on exploration alone. A limit of 150 can therefore still terminate useful runs before the model starts the fix.

## Recommended Profiles

| Profile | Recursion limit | Use case |
| --- | ---: | --- |
| `gaia` | 150 | GAIA-style multi-step tool-use tasks. |
| `swebench-lite` | 250 | SWE-bench Lite repository-repair tasks. |
| `long-horizon` | 250 | Generic long-horizon DeerFlow evaluations. |

These values are starting points, not correctness guarantees. Larger repositories, slower tool-use strategies, or subagent-heavy runs may need more headroom. Raising the limit only removes an artificial stop condition; it does not fix pathological loops.

## Generate A Run Config

Use `scripts/benchmark_run_config.py` to generate the `config` object for a benchmark harness or direct LangGraph API request:

```bash
python scripts/benchmark_run_config.py --profile swebench-lite
```

Output:

```json
{
  "recursion_limit": 250
}
```

Add model and mode overrides when a benchmark run needs them:

```bash
python scripts/benchmark_run_config.py \
  --profile swebench-lite \
  --model-name k2.6 \
  --thinking-enabled \
  --plan-mode \
  --subagent-enabled
```

Output:

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

Override the profile limit only when the benchmark matrix explicitly records the override:

```bash
python scripts/benchmark_run_config.py --profile swebench-lite --recursion-limit 300
```

## Direct API Example

For direct `/api/langgraph/*` calls, put the generated JSON under the request body's `config` key:

```bash
curl -X POST http://localhost:2026/api/langgraph/threads/<thread_id>/runs \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "messages": [
        {"role": "user", "content": "<benchmark task prompt>"}
      ]
    },
    "config": {
      "recursion_limit": 250,
      "configurable": {
        "model_name": "k2.6",
        "thinking_enabled": true
      }
    },
    "stream_mode": ["values", "messages-tuple", "custom"]
  }'
```

## Reproducibility Checklist

Record these fields for every benchmark run:

- DeerFlow commit SHA.
- Benchmark name and dataset split.
- Model provider and model name.
- Generated profile name and full run config JSON.
- Sandbox provider and host resources.
- Whether plan mode and subagents were enabled.
- Loop-detection configuration.
- Failure classification, especially recursion-limit stops, loop-detection stops, empty patches, and network/tool failures.

This metadata makes it possible to distinguish an underpowered recursion limit from model/tool-use behavior or loop-detection behavior.

## Relationship To Loop Detection

Issue #2820 also links benchmark quality to loop-detection work in #2517 and related issues. The benchmark profiles in this document do not change loop-detection thresholds or behavior. Use them to remove obvious recursion-limit noise first, then analyze remaining failures separately.

If raising the recursion limit mostly converts `GraphRecursionError` failures into repeated scaffold files, repeated search scripts, or empty patches, treat that as loop/tool-use evidence rather than a reason to keep increasing the limit.
