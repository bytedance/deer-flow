# Tracing (`deerflow/tracing/`)

Wires LangSmith, Langfuse and Monocle. The providers are enabled by environment
variables; the variable names and the Langfuse field mapping are in
`tracing/` and `config/`. The request correlation ID is covered in the
[harness guide](../AGENTS.md).

## Verify

```bash
cd backend
python -m pytest tests -q -k "tracing or langfuse or monocle"
```

## Distributed tracing

Gateway accepts a W3C `traceparent` and keeps the active server span when ASGI
is already instrumented. Strip untrusted trace headers at the deployment
ingress if clients should only start new traces. The host persists the
canonical parent with Run admission and manual scheduled occurrences, and
captures it in durable batch execution specs. Client JSON cannot set this
field. A continuation with no active parent resolves the selected checkpoint
after the Worker startup barrier. Its source Run reference selects the
admission parent only within the same owner and thread. Only span identity
and flags cross durable boundaries.

A fresh Gateway run without a parent starts a `deerflow.run.admit` span.
The Worker and native subagents emit `deerflow.run` and `deerflow.subagent`
through the same OpenTelemetry tracer provider. Without an SDK provider
this is propagation only. Use the existing task lifecycle and model
observers for extensions. Collector setup, downstream HTTP instrumentation,
and export policy belong to the deployment.

## LangSmith and Langfuse

- **Callbacks attach at the graph invocation root, not at the model.** One run
  then produces one trace, and the Langfuse handler lifts the trace attributes
  only when it sees the root chain start.
- **Three places merge the trace metadata before they invoke a graph**: the run
  worker, `DeerFlowClient.stream` and the subagent executor. A new entry point
  that invokes a graph does the same, after model selection.
- **A subagent trace carries the parent `thread_id` as its session**, so it groups
  with the parent thread.
- **`build_langfuse_trace_metadata()` returns `{}` when Langfuse is off.** A
  LangSmith-only deployment is unaffected.

## Monocle

- **Monocle is not a callback.** Its setup installs a process-global OpenTelemetry
  `TracerProvider` and instruments the clients, once per process.
- **The Gateway lifespan is the only call site.** Importing `deerflow.agents` must
  not start tracing, and `build_tracing_callbacks()` does not call the setup.
- **The embedded client and the TUI are not instrumented.** An embedded user who
  wants Monocle traces calls `setup_monocle_tracing_if_enabled()` before the run.
- **DeerFlow adds no per-run fields to Monocle traces.** There is no attribute
  layer to maintain here.
- **Monocle and Langfuse share the global provider.** The library that starts
  second attaches its span processor to the existing provider, so Monocle's
  exporters also receive Langfuse's spans when both are on.
