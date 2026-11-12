# Tracing and Observability

## Request Trace Correlation

Every Gateway HTTP response carries an `X-Trace-Id` header. The id is inherited
from an inbound `X-Trace-Id` when the caller sends one and generated otherwise, so
a proxy or an upstream service can pin one id across services. It needs no
configuration and cannot be turned off.

The same id stays attached to work that outlives the HTTP response: the detached
run task, any subagents it delegates to, and the background memory-update threads.
It is recorded as `deerflow_trace_id` on the run record (visible in the runs API),
in the thread's checkpoint metadata, and in Langfuse traces. Scheduled tasks, MCP
task notification runs, and IM channel messages start outside HTTP and mint their
own id per occurrence.

Log records carry that id only when enhanced logging is on:

```yaml
logging:
  enhance:
    enabled: true   # print trace_id into log records
    format: text    # or json
```

This is off by default because turning it on changes the log format. `logging` is
restart-required, so edit `config.yaml` and restart the Gateway. The setting
affects log output only — the id, the response header, and the run metadata are
unaffected.

`deerflow_trace_id` is a DeerFlow correlation id: it is not a run id, and it is not
a provider's native trace id. It is not a lookup key either — nothing resolves a
thread or a run from it; use it to correlate log lines. A `deerflow_trace_id` sent
in a run request's `metadata` or `config.context` is ignored and overwritten, so
the response header, the logs, and the persisted run can never disagree. To pin a
correlation id, send the `X-Trace-Id` header.

Gateway run history also records one terminal `run.delivery` receipt per run,
including zero-output and crash-recovered runs. The receipt is persisted before
the durable terminal run status during normal execution. Orphan recovery first
atomically claims an expired lease and then idempotently backfills the receipt,
so a stale recovery scan cannot overwrite a live run's detailed delivery facts.
Receipt persistence remains best-effort during an event-store outage. Runs that
fail checkpoint preflight (or are cancelled while waiting for prior
finalization) keep the existing completion-data behavior: they receive the
zero-delivery receipt but do not overwrite RunStore completion fields with an
empty snapshot.

When `tool_progress.enabled` is true, the same run event history also records
result-quality guard phase changes. It records loop-detection decisions and
deferred MCP tool promotions for both the lead agent and ordinary task
subagents. Promotion
events identify deferred-tool names selected by `tool_search`, without copying the search query, routing keywords,
schemas, arguments, results, or catalog hash into the promotion event itself.

## LangSmith Tracing

DeerFlow has built-in [LangSmith](https://smith.langchain.com) integration for observability. When enabled, all LLM calls, agent runs, and tool executions are traced and visible in the LangSmith dashboard.

Add the following to your `.env` file:

```bash
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=lsv2_pt_xxxxxxxxxxxxxxxx
LANGSMITH_PROJECT=xxx
```

## Langfuse Tracing

DeerFlow also supports [Langfuse](https://langfuse.com) observability for LangChain-compatible runs.

Add the following to your `.env` file:

```bash
LANGFUSE_TRACING=true
LANGFUSE_PUBLIC_KEY=pk-lf-xxxxxxxxxxxxxxxx
LANGFUSE_SECRET_KEY=sk-lf-xxxxxxxxxxxxxxxx
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

If you are using a self-hosted Langfuse instance, set `LANGFUSE_BASE_URL` to your deployment URL.

**Trace correlation fields.** Every agent run is annotated with Langfuse's reserved trace attributes so the Sessions and Users pages light up automatically:

- `session_id` = LangGraph `thread_id` — groups every trace of the same conversation
- `user_id` = effective user from `get_effective_user_id()` (falls back to `default` in no-auth mode)
- `trace_name` = assistant id (defaults to `lead-agent`)
- `tags` = `[env:<DEER_FLOW_ENV>, model:<model_name>]` (built-in Gateway lead-agent and embedded client runs tag the selected model after default or fallback resolution; custom graph factories may only provide the requested model; the environment tag is omitted when unset)
- `metadata.deerflow_trace_id` = DeerFlow request correlation id, matching `X-Trace-Id` when request trace correlation is enabled

These are injected into `RunnableConfig.metadata` at the graph invocation root for both the gateway path (`runtime/runs/worker.py::run_agent`) and the embedded path (`client.py::DeerFlowClient.stream`), so any LangChain-compatible callback can read them. Set `DEER_FLOW_ENV` (or `ENVIRONMENT`) to tag traces by deployment environment.

## Monocle Tracing

DeerFlow also supports [Monocle](https://github.com/monocle2ai/monocle), an OpenTelemetry-based tracer for agentic applications. It records each run end-to-end: LLM calls, agent steps, and tool and MCP invocations, with their inputs, outputs, timings, and token counts.

Add the following to your `.env` file:

```bash
MONOCLE_TRACING=true
MONOCLE_EXPORTERS=file          # file, console, okahu, s3, blob, gcs (default: file)
OKAHU_API_KEY=okh_xxxxxxxx      # required only for the `okahu` exporter
```

Each run writes one trace file to `.monocle/`; open it in the [Monocle VS Code extension](https://marketplace.visualstudio.com/items?itemName=OkahuAI.monocle-apptrace) to inspect the span timeline and token counts. Connect to [Okahu](https://www.okahu.ai), an agent-observability platform, to analyze traces across runs and run trace-based and agentic evaluations (via the `okahu` exporter).

Traces capture span inputs and outputs verbatim — prompts, tool arguments, and model responses — plus token usage and timings. The `file` exporter keeps them on local disk and never rotates or cleans them up, so prune `.monocle/` periodically; the remote exporters (`okahu`, `s3`, `blob`, `gcs`) send that same data off-box, so enable only destinations you trust. Monocle is initialized once at Gateway startup: a configuration error (unknown exporter, missing `OKAHU_API_KEY`) is logged there and tracing stays off until the Gateway restarts.
