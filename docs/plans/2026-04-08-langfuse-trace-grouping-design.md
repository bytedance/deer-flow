# Langfuse Trace Grouping — Design

**Date:** 2026-04-08
**Branch:** `fix/langfuse-trace-grouping`
**Scope:** Bug fix. Group all model / tool / node calls of one agent run into a single Langfuse trace, instead of producing one root trace per LLM call.

---

## Problem

`packages/harness/deerflow/models/factory.py:114-118` attaches the Langfuse `CallbackHandler` to `model_instance.callbacks`. In LangChain, callbacks set on a model instance are *local* — they create their own callback manager that does not inherit the parent run_id from the surrounding graph invocation. Result: every LLM call becomes its own root trace in Langfuse, with no link to the agent run that produced it.

LangSmith does not show this symptom because LangSmith's `LangChainTracer` is auto-injected by `langchain_core.callbacks.manager._configure()` whenever `LANGSMITH_TRACING=true` (or `LANGCHAIN_TRACING_V2=true`) is set. That auto-injection happens at the root callback manager of every run, independent of the model-level attachment in `factory.py`. The model-level LangSmith attachment is therefore redundant dead code.

## Fix

Attach the Langfuse handler at the **invocation config root**, not the model level. The handler then participates in the root callback manager of every `agent.astream()` / `agent.ainvoke()` call, and all child runs (nodes, LLM calls, tool calls) are recorded as spans of one trace.

Concretely, in `make_lead_agent(config)`, append the handler to `config["callbacks"]` before returning the compiled graph. Both runtime modes pass the very same `RunnableConfig` dict into graph execution afterward:

- **Standard mode**: LangGraph Server calls `make_lead_agent(config)` per invocation with the request's RunnableConfig, then invokes the returned graph with the same config.
- **Gateway mode**: `runtime/runs/worker.py` calls `agent_factory(config=runnable_config)` and then `agent.astream(graph_input, config=runnable_config, ...)` using the same dict.

This mutation pattern is consistent with how `make_lead_agent` already populates `config["metadata"]` for trace tagging (a few lines above). An alternative — wrapping the compiled graph with `compiled.with_config({"callbacks": [handler]})` — was considered but rejected because it would return a `RunnableBinding` instead of a `CompiledStateGraph`, which breaks LangGraph Server's subsequent attribute writes (e.g. `agent.checkpointer = ...`).

Single injection point covers both modes.

## Changes

### 1. `packages/harness/deerflow/tracing/factory.py`

- Add `build_langfuse_handler() -> Any | None`. Returns a Langfuse `CallbackHandler` when the provider is enabled and configured; returns `None` when disabled; raises `RuntimeError` with provider name when explicitly enabled but initialization fails.
- Delete `_create_langsmith_tracer()` and the LangSmith branch in `build_tracing_callbacks()`. LangSmith is fully handled by the `LANGSMITH_TRACING` env-var path inside langchain-core; the model-level attachment is redundant.
- Delete `build_tracing_callbacks()` entirely (no remaining callers after the model-factory cleanup below). `validate_enabled_tracing_providers()` is still called from `build_langfuse_handler()` so the explicit-enabled-but-misconfigured failure mode is preserved for both providers.

### 2. `packages/harness/deerflow/models/factory.py`

- Remove the `build_tracing_callbacks()` import and the block at lines 114-118 that appends callbacks to `model_instance.callbacks`. Models no longer carry tracing callbacks.

### 3. `packages/harness/deerflow/agents/lead_agent/agent.py`

- In `make_lead_agent(config)`, after the existing `config["metadata"].update(...)` block and before the `create_agent(...)` calls, append the Langfuse handler to `config["callbacks"]`:
  ```python
  langfuse_handler = build_langfuse_handler()
  if langfuse_handler is not None:
      existing = config.get("callbacks") or []
      if not isinstance(existing, list):
          existing = list(existing)
      config["callbacks"] = [*existing, langfuse_handler]
  ```
- Build the handler **once per `make_lead_agent` call** (not module-level), so config reload picks it up on subsequent invocations.
- `create_agent(...)` return value is unchanged — both bootstrap and default branches return the compiled graph directly, as before.

### 4. Tests

- **`tests/test_tracing_factory.py`**: Replace existing tests. Cover `build_langfuse_handler()` for: provider disabled (returns `None`), provider enabled and configured (returns handler instance), provider explicitly enabled but init throws (raises `RuntimeError` mentioning "Langfuse"), explicitly enabled but missing keys (raises through `validate_enabled_tracing_providers`).
- **`tests/test_model_factory.py`**: Drop the `build_tracing_callbacks` monkeypatch and the assertion that callbacks were attached to the model instance. Models should no longer have tracing callbacks attached by `create_chat_model`.
- **New: `tests/test_lead_agent_tracing.py`**: Monkeypatch `build_langfuse_handler` to return a sentinel object. Call `make_lead_agent(config)`. Assert the returned runnable's bound config callbacks contain the sentinel. Also assert: when the handler is `None`, the returned runnable is not wrapped with extra callbacks.
- **`tests/test_tracing_config.py`**: Unchanged. LangSmith config detection, Langfuse config detection, and validation behaviors are not modified.

### 5. Docs

- `backend/CLAUDE.md`: Add a short note under "Model Factory" / new "Tracing" subsection: tracing callbacks are attached at the graph level in `make_lead_agent`, not at the model level. LangSmith continues to work via the `LANGSMITH_TRACING` env var (langchain-core auto-injection).
- `README.md` / `backend/README.md`: No change to env-var docs. Optionally add one sentence: "All model and tool calls within one agent run are grouped under a single Langfuse trace."

## Out of Scope (separate PR)

- Tagging Langfuse traces with `session_id = thread_id` / `user_id` for cross-turn grouping in the Langfuse UI.
- Linking subagent LLM calls to the parent trace. `SubagentExecutor` runs subagents in a separate thread pool, which breaks asyncio contextvar propagation; the parent run_id has to be passed explicitly. This is a follow-up.

## Risk: LangSmith Regression

The fix removes the model-level LangSmith tracer attachment. LangSmith continues to work because:

1. `tracing_config.py` still reads `LANGSMITH_TRACING` / `LANGCHAIN_TRACING_V2` and exposes the LangSmith config block — unchanged.
2. When the env var is set, `langchain_core.callbacks.manager._configure()` auto-injects `LangChainTracer` at the root callback manager of every run. This path is independent of `factory.py` and has been the canonical LangSmith integration in langchain-core for years.
3. `validate_enabled_tracing_providers()` still raises if `LANGSMITH_TRACING=true` but no API key is set — unchanged.

Manual smoke test (left to the contributor before merge): start the app with `LANGSMITH_TRACING=true` and a valid API key, run one agent turn, confirm a trace appears in LangSmith with nested LLM / tool spans.

## Acceptance

- Unit tests: `cd backend && uv run pytest tests/test_tracing_config.py tests/test_tracing_factory.py tests/test_model_factory.py tests/test_lead_agent_tracing.py -q` passes.
- Lint: `cd backend && uv run ruff check packages/harness/deerflow/tracing packages/harness/deerflow/models/factory.py packages/harness/deerflow/agents/lead_agent/agent.py` clean.
- Manual: with Langfuse enabled, one agent turn produces exactly one Langfuse trace containing the model and tool calls as spans.
- Manual: with LangSmith enabled, one agent turn still produces a properly nested LangSmith trace.
