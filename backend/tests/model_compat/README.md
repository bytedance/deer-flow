# Model/tool compatibility smoke runner

This directory contains a manual live runner for checking whether configured
models satisfy DeerFlow's core chat, streaming, and sandbox-tool contracts.
It is not a pytest module, is not collected by the default test suite, and is
never run by CI.

> **Warning:** the smoke command calls real model APIs, may incur API charges,
> and may start the configured sandbox. Do not run it unless you intend to use
> real credentials and quota.

## Requirements

- A valid `config.yaml` at the repository root.
- Credentials required by the selected provider, supplied through the normal
  DeerFlow configuration/environment mechanism.
- Backend dependencies already installed. The runner never changes them.

The runner never reads or prints `.env` itself. Diagnostic text and JSON output
redact common credential forms, but prompts and model responses should still
avoid including secrets.

## Run explicitly

From `backend/`, list configured model names without making a model request:

```bash
make model-smoke ARGS="--list-models"
```

Run all five checks for one or more explicitly selected models:

```bash
make model-smoke ARGS="--model model-name"
make model-smoke ARGS="--model model-a --model model-b"
```

`make model-smoke` sets the required `DEER_FLOW_RUN_LIVE_TESTS=1`
acknowledgement. A direct invocation must set it explicitly:

```bash
DEER_FLOW_RUN_LIVE_TESTS=1 PYTHONPATH=.:packages/harness:packages/extension-api \
  uv run python tests/model_compat/run_smoke.py --model model-name
```

Use `--all-models` to select every configured model, or repeat `--case` to run
only named checks. `--help` lists the accepted case names. Every case is a real
model turn, so `--all-models` can consume substantially more API quota.

Each model/case pair receives unique smoke-only user and thread identifiers, an
in-memory checkpointer, and an isolated workspace. Local thread data is removed
after the case; `--keep-workspaces` is an explicit debugging override. Sandbox
resources are released through DeerFlow's normal middleware lifecycle. The
runner also disables title generation, summarization, and memory injection or
writes in its process-local config copy, preventing hidden auxiliary model
requests and persistent smoke-user memory without modifying `config.yaml`.

## Output and exit codes

The default output is a tab-separated summary with model, case, status, error
category, first-content latency (when applicable), and detail. Add
`--json-output /path/to/results.json` for a redacted JSON report. Failures are
classified as `configuration_error`, `model_incompatible`, `tool_failure`, or
`runner_error`.

| Exit code | Meaning |
| --- | --- |
| `0` | Every selected check passed, or `--list-models` succeeded. |
| `1` | A compatibility or tool check failed. |
| `2` | Opt-in, CI, argument, model selection, or local configuration error. |
| `3` | The runner or cleanup failed unexpectedly. |

The runner refuses live execution when `CI` is set. Offline unit tests for its
parser, selection, event analysis, summaries, cleanup, redaction, and exit code
logic live in `tests/test_model_compat_smoke.py` and use fakes only.
