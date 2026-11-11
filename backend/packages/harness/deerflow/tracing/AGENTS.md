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
