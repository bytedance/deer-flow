# Observability


Request trace correlation is controlled by `logging.enhance.enabled` at **both** entry points, gated through the shared helper `deerflow.config.app_config.is_trace_correlation_enabled` so the Gateway and embedded paths cannot drift:

- **Gateway HTTP**: `app.gateway.trace_middleware.TraceMiddleware` binds one request-level trace id per HTTP request, inheriting inbound `X-Trace-Id` when present or generating a new id otherwise. A **valid** inbound header also marks the request so `runtime/runs/worker.py` prefers that id over `config.metadata.deerflow_trace_id`, keeping logs, response headers, Langfuse, and runtime context aligned when callers send both. The middleware writes the final value to every HTTP response at `http.response.start`, which covers SSE / streaming responses without consuming the body.
- **Embedded / TUI / CLI**: `DeerFlowClient.stream()` mints (or inherits) a request-level trace id per turn only when the flag is on. When it is off, no fresh id is minted — a caller that explicitly wraps `stream()` in `request_trace_context(...)` still opts in, because the downstream `get_current_trace_id()` read propagates that value into Langfuse metadata regardless of the flag. Because `stream()` is a sync generator (which shares the caller's context), the id binding is set/reset around each `next()` step rather than around `yield from`: this keeps LangGraph node execution and its log records inside the binding, while returning control to the caller with the ContextVar restored — avoids cross-request leak between yields and `ValueError: <Token> was created in a different Context` on GC-driven close of an abandoned generator (regression pinned by `tests/test_client_langfuse_metadata.py::test_stream_does_not_leak_trace_id_to_caller_context_between_yields` and `::test_stream_abandoned_generator_close_does_not_raise_cross_context`).

The same ContextVar value is injected into enhanced log records as `trace_id` and into Langfuse metadata as `deerflow_trace_id`.

`logging` is registered as a **restart-required** field
(`STARTUP_ONLY_FIELDS["logging"]`): `configure_logging()` installs the trace-context
filter and enhanced formatter on root handlers only during app.py lifespan startup,
and `TraceMiddleware` captures `logging.enhance.enabled` once when the FastAPI app
is constructed (via `resolve_trace_enabled(get_app_config())` in `create_app()`,
itself a thin alias for `is_trace_correlation_enabled`). This keeps the response
`X-Trace-Id` header, log `trace_id` fields, and Langfuse `deerflow_trace_id`
coherent — a runtime `config.yaml` edit to `logging.enhance.*` needs a Gateway
restart to take effect. The `deerflow_trace_id` chain inherits this guarantee
transitively because every injection point ultimately reads the same
`trace_context` ContextVar that the middleware alone populates. `DeerFlowClient`
reads its own `self._app_config` snapshot (captured at `__init__`) through the
same helper for the embedded gate.

`deerflow_trace_id` is a DeerFlow correlation metadata key, not Langfuse's native
trace id and not a DeerFlow `run_id`. Keep the existing subagent `trace_id` field
separate: that short id is still only for subagent execution logs/status.

## Tracing System (`packages/harness/deerflow/tracing/`)


LangSmith and Langfuse are both supported. The wiring lives in two layers:

- `factory.py::build_tracing_callbacks()` — returns the LangChain `CallbackHandler` list for the providers currently enabled via env vars (`LANGSMITH_TRACING`, `LANGFUSE_TRACING`, etc.). The handlers are attached at the **graph invocation root** for in-graph runs (`make_lead_agent` and `DeerFlowClient.stream` both append them to `config["callbacks"]` before invoking the graph) so a single run produces one trace with all node / LLM / tool calls as child spans. Standalone callers — anything that invokes a model outside such a graph (e.g. `MemoryUpdater`) — keep `create_chat_model`'s default `attach_tracing=True`, which falls back to model-level callback attachment.
- `metadata.py::build_langfuse_trace_metadata()` — builds the Langfuse-reserved trace attributes for `RunnableConfig.metadata`. The Langfuse v4 `langchain.CallbackHandler` lifts these onto the root trace (see its `_parse_langfuse_trace_attributes`), but only when it sees `on_chain_start(parent_run_id=None)` — which is why the callbacks have to live at the graph root, not the model.

**Trace-attribute injection points**: both `runtime/runs/worker.py::run_agent` (gateway path) and `client.py::DeerFlowClient.stream` (embedded path) merge the metadata into `config["metadata"]` right before constructing the graph. `subagents/executor.py::_aexecute` does the same for every subagent run so subagent traces group under the parent thread's session card (carrying the parent `thread_id` → `langfuse_session_id`, the user_id captured at `task_tool` → `langfuse_user_id`, and a `subagent:<normalized-name>` trace name). Caller-supplied keys win via `setdefault`, so an external `session_id` override is preserved. Field mapping:

| Langfuse field         | Source                                       |
|-----------------------|----------------------------------------------|
| `langfuse_session_id` | LangGraph `thread_id`                         |
| `langfuse_user_id`    | `get_effective_user_id()` (`default` in no-auth); for subagents, captured from `runtime.context` at `task_tool` time via `resolve_runtime_user_id()` |
| `langfuse_trace_name` | `RunRecord.assistant_id` / client `agent_name` (defaults to `lead-agent`); for subagents, `subagent:<name>` (lowercased, `_` → `-`) |
| `langfuse_tags`       | `env:<DEER_FLOW_ENV>` + `model:<model_name>`  |
| `deerflow_trace_id`   | Current request/entry trace id from `deerflow.trace_context`; matches `X-Trace-Id` for enhanced Gateway HTTP requests. Gated by `logging.enhance.enabled` in both gateway and embedded paths via `is_trace_correlation_enabled` — off by default; embedded callers can still opt in per-turn by wrapping `stream()` in `request_trace_context(...)` |

Returns `{}` when Langfuse is not in the enabled providers — LangSmith-only deployments are unaffected. Set `DEER_FLOW_ENV` (or `ENVIRONMENT`) to tag traces by deployment environment. Tests live in `tests/test_tracing_factory.py`, `tests/test_tracing_metadata.py`, `tests/test_worker_langfuse_metadata.py`, `tests/test_client_langfuse_metadata.py`, and `tests/test_subagent_executor.py::TestSubagentTracingWiring`.

**Monocle telemetry** is a third provider, structurally unlike LangSmith/Langfuse. It is **not** a LangChain callback: `tracing/monocle.py::setup_monocle_tracing_if_enabled()` calls `monocle_apptrace.setup_monocle_telemetry()` once, which installs a **process-global OTel `TracerProvider`**, patches span serialization, and auto-instruments the openai/langchain/langgraph clients. Because that is a one-time, process-global side effect (not a per-run callback), it is initialized from the **Gateway lifespan** (`app/gateway/app.py`) — never from `build_tracing_callbacks()` — and it is **off by default**. The setup call was deliberately moved out of `agents/__init__.py`, so `import deerflow.agents` must never start tracing (pinned by `tests/test_monocle_tracing.py::test_no_import_time_setup`). The Gateway lifespan is the **sole call site** (pinned by `test_gateway_lifespan_initializes_monocle`), so unlike LangSmith/Langfuse — which attach at the graph roots and cover every path — the embedded `DeerFlowClient` and the TUI are not instrumented; embedded users who want Monocle traces call `setup_monocle_tracing_if_enabled()` themselves before running the agent.

Unlike the Langfuse metadata above, DeerFlow injects **no** per-run fields into Monocle traces — the only attribute it sets is `workflow_name="deer-flow"`; every span attribute (`span.type`, `entity.*`, token usage, span inputs/outputs, `scope.agentic.session`) is produced by Monocle's own metamodel and auto-instrumentation, so there is no DeerFlow trace-attribute layer to maintain here.

Config is env-driven like the others — `MonocleTracingConfig`, built in `get_tracing_config()` and gated by `is_monocle_tracing_enabled()`. `MONOCLE_TRACING` enables it; `MONOCLE_EXPORTERS` selects exporters (default `file` → trace JSON in `.monocle/`; also `console`, `okahu`, `s3`, `blob`, `gcs`, where `okahu` requires `OKAHU_API_KEY`). `setup_monocle_tracing_if_enabled()` stays a thin wrapper on purpose: `monocle_apptrace` already guards duplicate setup (`instrumentor.py::check_duplicate_setup`) and never force-overrides an existing global provider, so the wrapper only gates on config. Coexistence with Langfuse (v4, also OTel-based) is **verified**: whichever library initializes second reuses the existing global `TracerProvider` and attaches its own span processor, so neither side loses spans (pinned by `test_coexists_with_langfuse`). Both processors see all spans, so Monocle's exporters also capture Langfuse's spans when both are enabled. (LangSmith is a plain callback and coexists trivially.) Tests: `tests/test_monocle_tracing.py`.
