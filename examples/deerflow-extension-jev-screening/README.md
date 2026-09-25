# Advisory screening of fetched content — extension example

An opt-in packaged extension for [RFC #5737](https://github.com/bytedance/deer-flow/issues/5737).
It contributes one `AgentMiddleware` through the extension API, placed at
`TOOL_VISIBLE` for lead agents and subagents. The middleware screens a bounded
excerpt of `web_fetch`, `web_search`, `image_search`, `web_capture` and MCP tool
results with one TypeSafe Jev `noul` question. A score at or above the configured
threshold adds a fixed advisory warning to that tool result before the next model
call. It does not block tools, authorize actions or establish that the model will
ignore an injected instruction.

The package imports only `deerflow_extension_api` from DeerFlow, so it can move
out of this repository unchanged.

## Install and configure

From `backend/` in a compatible DeerFlow deployment:

```sh
uv run deerflow extensions install ../examples/deerflow-extension-jev-screening --yes
export TYPESAFE_API_KEY='your-deployment-secret'
```

Set the registered entry in the deployment configuration:

```yaml
plugins:
  - use: deerflow_extension_jev_screening:install
    enabled: true
    config:
      enabled: true
      threshold: 0.5
      max_excerpt_chars: 4000
      timeout_seconds: 3.0
```

Optional keys are `api_key_env` (default `TYPESAFE_API_KEY`), `model` (default
`jev-latest`) and `endpoint`, which must use HTTPS or loopback HTTP. Provide the
key to the actual Gateway process and restart Gateway after installing or changing
the configuration. The outer switch loads the package; `config.enabled` turns
screening on and defaults to off. Invalid settings make `install()` fail, which
the Gateway reports as an extension diagnostic while starting without the
extension, unless the entry is `required: true`.

**Data sharing:** `config.enabled: true` is also the consent to send up to
`max_excerpt_chars` characters from each text message of an eligible tool result,
for at most eight messages per tool call, to the configured TypeSafe endpoint. The middleware sits outside the host's tool-result truncation,
sanitization and PII redaction, so the excerpt is the text the model would see:
with `pii_redaction` enabled, redacted values are replaced before the excerpt
leaves the host. The key is read only from its named environment variable, never
from settings, tool results or logs.

## How it works

1. **Detect.** The tool-call wrapper classifies each text message of an eligible
   tool's visible result on its own, with one request per message. For every
   message whose score reaches the threshold, it records that message's tool-call
   ID in the run's extension task store (`task_store_from_runtime`). A benign
   message with its own tool-call ID therefore does not take the warning meant for
   another message in the same `Command`; messages that share an ID are warned
   together. The wrapper cannot change the result: extension tool wrappers are
   observational, and the host's isolation wrapper always returns the downstream
   result.
2. **Warn.** `before_model` takes the recorded IDs and returns copies of the
   matching tool messages from the latest tool step, with the warning prepended
   and the same message ID (including a valid empty string), so the messages
   reducer replaces them. The warning is added once; later model calls see the
   same message.
3. **Declare.** `release_policy_parameters()` declares the enabled state, model,
   threshold, excerpt limit, per-call message cap, timeout and key variable name,
   plus SHA-256 hashes of the endpoint, question and warning. The host's assembly
   descriptor unwraps the isolation wrapper to read it, so changing a setting moves
   the fingerprint while rotating a key does not.

## Runtime behavior and boundaries

- Gateway lead runs and subagents bind a task store, and both use the async hook.
  The sync hook runs the same classifier on LangGraph's synchronous tool worker
  threads for embedders that run the graph synchronously. Called directly on an
  event-loop thread, it passes the result through. Its per-request deadline does
  not cover shutting down that temporary event loop, which waits for a pending
  name lookup, so a stalled DNS resolver can hold a synchronous tool call longer.
- The embedded `DeerFlowClient` does not load `plugins:` extensions and binds no
  extension task store. Without a task store the middleware sends nothing.
- One classifier request is made per text message of an eligible result,
  including each message of a `Command`, for at most eight messages per tool call.
  The requests share one client and run concurrently, so one slow or failed
  request does not hide another message's flag. Multimodal messages are skipped.
  Only each message's excerpt is classified, so instructions beyond it can be
  missed, as can messages past the eighth.
- Each request has its own deadline, 3 seconds by default and at most 10. There
  are no retries or cache, and a new client is used for each tool call.
- Requests ask for an uncompressed response and drop an encoded one, so the
  16 KiB response cap also bounds memory.
- A plain-HTTP loopback endpoint ignores `HTTP_PROXY` and `ALL_PROXY`, so the key
  and excerpts never reach a proxy in cleartext. HTTPS endpoints keep the usual
  proxy settings.
- A missing or unusable key, provider errors, invalid, malformed, oversized or
  compressed responses and timeouts pass the result through silently, and one
  failed request does not cancel the others. Unexpected local errors are reported
  by the host as extension diagnostics, and the tool result is kept. Tool failures,
  graph interrupts and cancellation propagate without repeating the tool.
- A flag lives only as long as its task. If a run is interrupted between the tool
  step and the next model call, the resumed run does not add the warning.
- The host can still truncate or externalize output under its model-input budget,
  including the warning.
- The fixed question is the v2 wording in the evaluation kit attached to #5737. Its
  detection measurements do not measure this middleware's latency or its effect on
  agent behavior. No security claim is made for auxiliary model calls, summaries
  or downstream actions.

## What this example exercises in the extension API

Everything above works without host changes: packaging and `plugins:` loading,
private configuration with install-time validation, `TOOL_VISIBLE` placement for
lead agents and subagents, the per-task store, lifecycle state updates, isolation
diagnostics and assembly identity. Four gaps showed up along the way:

1. **Transforming a tool result takes two hooks.** Wrap hooks are observe-only, so
   the example detects in the tool wrapper and edits state in `before_model`. The
   extension manual says contributions are observational and cannot replace tool
   output, while the same page says a lifecycle hook's returned dict is applied as a
   state update. This example depends on the second rule. Saying whether rewriting
   a tool message by ID from a lifecycle hook is intended would settle it for
   extension authors.
2. **No public signal for remote content.** The example repeats the sanitizer's
   list of remote tools and reads the host's `deerflow_mcp` tool metadata key,
   which is not part of the extension contract.
3. **No structured flag for a tool result.** The provenance contract labels whole
   messages that middleware injects. Nothing can attach a flag to a tool result, so
   the example can only prefix text. This is the second review question in #5737.
4. **Gateway only.** Only the Gateway loads `plugins:` and binds a task store, so
   embedded-client runs get neither. If an embedder loads extensions itself, a
   contributed middleware that implements only an async lifecycle hook, such as
   `abefore_model`, makes every synchronous run raise `TypeError` before the
   isolation wrapper is called. The wrapper adds sync pass-throughs for wrap hooks
   but not for lifecycle hooks. This example implements both forms.

## Validation

`backend/tests/test_jev_result_screening_extension.py` loads the package through
the real extension loader and host isolation wrapper. It checks install and
configuration diagnostics, bounded requests, the task-store handover, copy
semantics, fail-open provider errors and isolation diagnostics.
`backend/tests/test_jev_screening_pipeline.py` runs real lead and subagent
middleware builders and LangChain graphs against a recording model, with a task
store bound the way the Gateway worker binds it. It covers the redacted excerpt,
error classification, budget boundaries, repeated turns and runs without a store.
`backend/tests/test_jev_screening_policy.py` verifies that assembly fingerprints
change with policy settings and text and stay stable across credential rotation.
All tests use synthetic data and offline HTTP transports.

A separate paired agent replay would be needed to measure whether warnings reduce
successful injections and whether they disrupt benign tasks. Detection accuracy
alone does not establish protective value.
