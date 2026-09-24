# Advisory screening of fetched content

An experimental, operator-configured `AgentMiddleware` for [RFC #5737](https://github.com/bytedance/deer-flow/issues/5737).
It screens a bounded excerpt of `web_fetch`, `web_search`,
`image_search`, `web_capture` and MCP tool results with one TypeSafe Jev `noul`
question. A score at or above the configured threshold causes a fixed advisory
warning to be added before the next regular model call, in both async Gateway
runs and synchronous embedded-client runs. It does not block tools,
authorize actions or establish that the model will ignore an injected instruction.

## Configuration and local trial

The middleware is disabled by default. Enable it in operator-owned `config.yaml`:

```yaml
extensions:
  middlewares:
    - class: deerflow_extension_jev_screening:ScreeningMiddleware
      kwargs:
        enabled: true
        api_key_env: TYPESAFE_API_KEY
        model: jev-latest
        threshold: 0.5
        max_excerpt_chars: 4000
        timeout_seconds: 3.0
```

Supply `TYPESAFE_API_KEY` to the Gateway process. For a local trial, from `backend/`:

```bash
uv run --locked --with ../examples/deerflow-extension-jev-screening \
  uvicorn app.gateway.app:app --host 127.0.0.1 --port 8001
```

Keep `--with` on each trial startup; it supplies the package without changing the
backend dependency manifest or lock. For deployment, install the package into the
Gateway's Python environment through your normal dependency/build process and
restart Gateway with the configuration above. This package uses the existing
configured-middleware entry point, not `plugins:` or `deerflow extensions install`.
Missing packages or invalid constructor settings fail agent construction.

**Data sharing:** Enabling the middleware sends up to 4,000 characters of a raw
remote tool result to the configured TypeSafe service. This happens **before
DeerFlow's PII redaction, sanitization and output budgeting**; enabling host PII
redaction does not protect the excerpt sent to Jev. Enable this only for content
your deployment permits sharing with that service. The key is read from its
named environment variable, not stored in settings, tool results or logs. An
optional `endpoint` must use HTTPS or loopback HTTP.

## Runtime behavior and boundaries

The configured path supports normal middleware result/state transformations.
The observational plugin contract remains unchanged. The tool hook copies a
private pending flag into result metadata without changing the original text.
This allows the host to classify errors, stamp receipts, redact and sanitize the
result normally. The `before_model` lifecycle hook then consumes the flag and
returns a new `ToolMessage` with the same ID and a fixed warning. Subsequent
model calls do not add the warning again.

Original result objects are never modified. The screener itself does not remove
source text, but the host can still externalize or truncate output under its
configured budget, including after a warning is added. A small budget can also
shorten the warning. Do not interpret this example as a guarantee that all source
text or every warning reaches every model invocation.

One classifier request is made per eligible tool call containing text, including
`Command` results with tool messages. Text-only message blocks are supported;
multimodal messages and local file/shell results are skipped. Only the bounded
excerpt is classified, so instructions beyond it can be missed. The HTTP request
cancellation deadline defaults to 3 seconds and cannot exceed 10 seconds. Synchronous
runs reuse that coroutine with `asyncio.run`; cleanup, including system DNS
executor shutdown, can extend wall-clock return time beyond the request deadline.
There are no retries
or cache; a new client is used for each result. Missing credentials, provider
errors, invalid responses and local screening failures pass the original result
through. Tool failures, graph interrupts and cancellation propagate without
repeating the tool. LangGraph executes synchronous tools in worker threads; a
direct manual call to the synchronous hook on an already-running event-loop
thread passes through. Use the asynchronous hook on that thread.

The fixed question is the v2 wording in the evaluation kit attached to #5737.
Its stored detection measurements do not measure this middleware's latency or
its effect on agent behavior. The private pending flag is advisory metadata, not
a permission or trust credential. No security claim is made for auxiliary model
calls, summaries or downstream actions.

## Validation

`backend/tests/test_jev_result_screening_extension.py` checks bounded excerpts,
copy-on-write, malformed provider responses, cancellation and local failure
recovery. `backend/tests/test_jev_screening_pipeline.py` runs real lead/subagent
middleware builders and LangChain graphs against a recording model, including
error classification, PII/sanitization, budget boundaries and repeated turns.
All tests use synthetic data and offline HTTP transports.

A separate paired agent replay would be needed to measure whether warnings
reduce successful injections and whether they disrupt benign tasks. Detection
accuracy alone does not establish protective value.
