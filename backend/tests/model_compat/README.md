# Model Compatibility Smoke Checks

These checks are opt-in live tests for model/provider compatibility. They call
real model APIs, may spend credits, and are not part of the default pytest
suite.

The goal is to validate the contract between a configured model and the
DeerFlow runtime:

- streaming produces usable content events;
- tool calls are emitted and parsed;
- tool calls carry enough arguments for the tools to execute;
- `write_file` can create an artifact;
- the model can recover after a tool error.

## Run

From the repository root:

```bash
python backend/tests/model_compat/run_smoke.py --list-models

python backend/tests/model_compat/run_smoke.py \
  --models deepseek-reasoner,volc-kimi-coding
```

Or from `backend/`:

```bash
PYTHONPATH=. uv run python tests/model_compat/run_smoke.py \
  --models deepseek-reasoner,volc-kimi-coding
```

You can also provide models through the environment:

```bash
DEERFLOW_COMPAT_MODELS=deepseek-reasoner,volc-kimi-coding \
PYTHONPATH=. uv run python tests/model_compat/run_smoke.py
```

Results are printed as a table and saved under:

```text
backend/.deer-flow/model-compat-runs/
```

## Cases

`basic_chat`

Verifies that the configured model can return a simple response through the
DeerFlow client.

`streaming_health`

Verifies that the stream produces at least one AI content event and records the
first-content latency.

`write_file_required_args`

Asks the model to call `write_file` and verifies the resulting artifact content.
This catches providers that emit malformed tool calls such as
`write_file({"path": "..."})` without the required `content` argument.

`write_then_read`

Asks the model to write a file, read it back, and report the content. This
checks a simple multi-tool chain.

`tool_error_recovery`

Asks the model to read a missing file first, then recover by writing a new file.
This checks whether the model continues after a tool error.

## Reading Failures

Common failure reasons:

- `model_not_configured`: the requested model name is not present in
  `config.yaml`.
- `provider_error`: the model provider or API gateway returned an API,
  authentication, rate-limit, or connectivity error.
- `no_ai_content_event`: no streamed AI text arrived before completion or
  timeout.
- `no_write_file_tool_call` / `no_read_file_tool_call` /
  `no_recovery_write_file_tool_call`: the model did not call the expected tool.
- `missing_path_arg` / `missing_content_arg`: the model emitted a malformed
  `write_file` call.
- `tool_args_not_object`: the parsed tool arguments were not a JSON object.
- `file_not_found`: the tool call looked valid, but the expected output artifact
  was not created.
- `content_mismatch`: the artifact exists but does not contain the expected
  content.
- `exception`: the live run raised an exception; inspect the saved JSON for the
  exception summary and captured tool events.

These checks are intentionally small. They should establish whether a model is
safe enough for basic DeerFlow tool use before testing larger workflows such as
skills, web research, subagents, or artifact generation.
