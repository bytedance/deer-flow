"""Run-local routing, exporter lifetime and ambient instrumentation boundaries."""

from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.runnables import RunnableLambda
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, Decision
from pydantic import SecretStr


def provider(project="alpha", key="test-key"):
    return SimpleNamespace(provider="arize", endpoint="https://collector.example/v1/traces", project=project, space_id="space", public_key="", api_key=SecretStr(key), secret_key=None, transport="http")


def snapshot(project="alpha", *, mode="configured", key="test-key"):
    return SimpleNamespace(snapshot_id=str(uuid4()), owner_user_id="alice", agent_name=project, revision="1:1", mode=mode, providers=() if mode == "disabled" else (provider(project, key),), monocle_enabled=False)


@pytest.fixture
def memory_routes(monkeypatch):
    from deerflow.tracing import scoped

    routes = {}

    def create(config):
        exporter = InMemorySpanExporter()
        routes.setdefault((config.project, config.api_key.get_secret_value()), []).append(exporter)
        return scoped.OtelResource(config, exporter=exporter, batch=False)

    monkeypatch.setattr(scoped, "_create_resource", create)
    yield routes
    scoped.shutdown_tracing_exporters()


@pytest.mark.asyncio
async def test_concurrent_graphs_export_only_to_their_own_destination(memory_routes):
    from deerflow.tracing.factory import build_tracing_callbacks
    from deerflow.tracing.scoped import tracing_scope

    async def run(project):
        with tracing_scope(snapshot(project)):
            callbacks = build_tracing_callbacks()
            graph = RunnableLambda(lambda text: text.upper())
            await asyncio.sleep(0)
            assert await graph.ainvoke(project, config={"callbacks": callbacks, "metadata": {"thread_id": project, "deerflow_trace_id": project + "-correlation"}}) == project.upper()

    await asyncio.gather(run("alpha"), run("beta"))
    for project in ("alpha", "beta"):
        spans = memory_routes[(project, "test-key")][0].get_finished_spans()
        assert spans
        assert all(span.resource.attributes["openinference.project.name"] == project for span in spans)
        assert all(span.attributes["deerflow.agent.name"] == project for span in spans)
        assert all(span.attributes["deerflow_trace_id"] == project + "-correlation" for span in spans)


def test_disabled_scope_suppresses_environment_langsmith_without_mutating_env(monkeypatch):
    import os

    from langchain_core.callbacks.manager import CallbackManager
    from langchain_core.tracers.langchain import LangChainTracer

    from deerflow.tracing.factory import build_tracing_callbacks
    from deerflow.tracing.scoped import get_current_snapshot, tracing_scope

    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "not-a-live-credential")
    with tracing_scope(snapshot(mode="disabled")):
        assert build_tracing_callbacks() == []
        manager = CallbackManager.configure()
        assert not any(isinstance(handler, LangChainTracer) for handler in manager.handlers)
        assert os.environ["LANGSMITH_TRACING"] == "true"
    assert get_current_snapshot() is None


def test_rotation_keeps_old_exporter_until_last_session_closes(memory_routes):
    from deerflow.tracing.scoped import TracingSession

    old = snapshot(key="old")
    parent = TracingSession(old)
    child = TracingSession(old)
    replacement = TracingSession(snapshot(key="new"))
    assert len(memory_routes[("alpha", "old")]) == 1
    old_exporter = memory_routes[("alpha", "old")][0]
    parent.close()
    assert not old_exporter._stopped
    replacement.close()
    assert not old_exporter._stopped
    child.close()
    assert old_exporter._stopped


def test_generator_session_activation_does_not_leak_context_or_close_exporter(memory_routes):
    from deerflow.tracing.scoped import TracingSession, get_current_snapshot

    frozen = snapshot()
    with TracingSession(frozen) as session:
        with session.activate():
            assert get_current_snapshot() is frozen
        assert get_current_snapshot() is None
        assert not memory_routes[("alpha", "test-key")][0]._stopped
        with session.activate():
            assert get_current_snapshot() is frozen
    assert memory_routes[("alpha", "test-key")][0]._stopped


def test_global_sampler_drops_override_and_disabled_but_preserves_inheritance(monkeypatch):
    from deerflow.config.tracing_config import reset_tracing_config
    from deerflow.tracing.profiles import current_monocle_fingerprint
    from deerflow.tracing.scoped import ScopedRoutingSampler, tracing_scope

    sampler = ScopedRoutingSampler(ALWAYS_ON)
    with tracing_scope(snapshot(mode="disabled")):
        assert sampler.should_sample(None, 1, "global-auto-span").decision is Decision.DROP
    inherited = snapshot(mode="inherit")
    inherited.providers = ()
    inherited.monocle_enabled = True
    monkeypatch.setenv("MONOCLE_TRACING", "true")
    reset_tracing_config()
    inherited.monocle_fingerprint = current_monocle_fingerprint()
    try:
        with tracing_scope(inherited):
            assert sampler.should_sample(None, 1, "global-auto-span").decision is Decision.RECORD_AND_SAMPLE
    finally:
        monkeypatch.delenv("MONOCLE_TRACING")
        reset_tracing_config()


def test_callback_preserves_llm_tool_parentage_and_usage(memory_routes):
    from langchain_core.messages import AIMessage, HumanMessage
    from langchain_core.outputs import ChatGeneration, LLMResult

    from deerflow.tracing.factory import build_tracing_callbacks
    from deerflow.tracing.scoped import tracing_scope

    with tracing_scope(snapshot()):
        callback = build_tracing_callbacks()[0]
        root, model, tool = uuid4(), uuid4(), uuid4()
        callback.on_chain_start({}, {"input": "hello"}, run_id=root, name="lead-agent", metadata={"thread_id": "thread-1", "run_id": "run-1", "deerflow_trace_id": "correlation"})
        callback.on_chat_model_start({"name": "model"}, [[HumanMessage(content="hello")]], run_id=model, parent_run_id=root)
        callback.on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage(content="hi", usage_metadata={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3}))]]), run_id=model)
        callback.on_tool_start({"name": "search"}, "query", run_id=tool, parent_run_id=root)
        callback.on_tool_end("answer", run_id=tool)
        callback.on_chain_end({"output": "done"}, run_id=root)
    spans = memory_routes[("alpha", "test-key")][0].get_finished_spans()
    root_span = next(s for s in spans if s.attributes["openinference.span.kind"] == "AGENT")
    llm = next(s for s in spans if s.attributes["openinference.span.kind"] == "LLM")
    tool_span = next(s for s in spans if s.attributes["openinference.span.kind"] == "TOOL")
    assert llm.parent.span_id == root_span.context.span_id
    assert tool_span.parent.span_id == root_span.context.span_id
    assert llm.attributes["llm.token_count.total"] == 3
    assert root_span.attributes["session.id"] == "thread-1"
    assert root_span.attributes["deerflow.run.id"] == "run-1"


def test_global_guard_does_not_change_private_provider_sampling(memory_routes):
    from deerflow.tracing.scoped import ScopedRoutingSampler, tracing_scope

    exporter = InMemorySpanExporter()
    global_provider = TracerProvider(sampler=ScopedRoutingSampler(ALWAYS_ON))
    global_provider.add_span_processor(SimpleSpanProcessor(exporter))
    with tracing_scope(snapshot(mode="disabled")):
        with global_provider.get_tracer("monocle-equivalent").start_as_current_span("must-not-export"):
            pass
    assert exporter.get_finished_spans() == ()
    global_provider.shutdown()


def test_delegated_callback_keeps_parent_trace_on_same_snapshot(memory_routes):
    from deerflow.tracing.factory import build_tracing_callbacks
    from deerflow.tracing.scoped import tracing_scope

    frozen = snapshot()
    with tracing_scope(frozen):
        parent = build_tracing_callbacks()[0]
        parent_id, child_id = uuid4(), uuid4()
        parent.on_chain_start({}, {}, run_id=parent_id, name="parent")
        with tracing_scope(frozen):
            child = build_tracing_callbacks()[0]
            child.on_chain_start({}, {}, run_id=child_id, parent_run_id=parent_id, name="child")
            child.on_chain_end({}, run_id=child_id)
        parent.on_chain_end({}, run_id=parent_id)
    spans = memory_routes[("alpha", "test-key")][0].get_finished_spans()
    parent_span = next(span for span in spans if span.name == "parent")
    child_span = next(span for span in spans if span.name == "child")
    assert child_span.parent is not None
    assert child_span.parent.span_id == parent_span.context.span_id
    assert child_span.context.trace_id == parent_span.context.trace_id


def test_finished_parent_context_is_retained_for_late_background_child(memory_routes):
    from deerflow.tracing.factory import build_tracing_callbacks
    from deerflow.tracing.scoped import tracing_scope

    with tracing_scope(snapshot()):
        callback = build_tracing_callbacks()[0]
        parent_id, child_id = uuid4(), uuid4()
        callback.on_chain_start({}, {}, run_id=parent_id, name="parent")
        callback.on_chain_end({}, run_id=parent_id)
        callback.on_chain_start({}, {}, run_id=child_id, parent_run_id=parent_id, name="late-child")
        callback.on_chain_end({}, run_id=child_id)
    spans = memory_routes[("alpha", "test-key")][0].get_finished_spans()
    parent_span = next(span for span in spans if span.name == "parent")
    child_span = next(span for span in spans if span.name == "late-child")
    assert child_span.parent is not None
    assert child_span.parent.span_id == parent_span.context.span_id


def test_otlp_does_not_forward_deployment_headers_or_follow_redirects(monkeypatch):
    from deerflow.tracing.scoped import OtelResource

    captured = []

    class Collector(BaseHTTPRequestHandler):
        def do_POST(self):
            captured.append((self.path, dict(self.headers), self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args):
            pass

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "Authorization=Bearer%20deployment-only,x-global-token=deployment-key")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_HEADERS", "x-global-traces-token=deployment-traces-key")
    collector = ThreadingHTTPServer(("127.0.0.1", 0), Collector)
    thread = threading.Thread(target=collector.serve_forever, daemon=True)
    thread.start()
    try:
        config = provider()
        config.endpoint = f"http://127.0.0.1:{collector.server_port}/v1/traces"
        resource = OtelResource(config)
        with resource.provider.get_tracer("test").start_as_current_span("explicit-route"):
            pass
        resource.close()
        assert len(captured) == 1
        path, headers, payload = captured[0]
        assert path == "/v1/traces"
        assert headers["api_key"] == "test-key"
        assert payload
        assert "Authorization" not in headers
        assert not any(name.lower().startswith("x-global") for name in headers)
    finally:
        collector.shutdown()
        collector.server_close()
        thread.join(timeout=2)


def test_private_langsmith_callback_emits_under_ambient_suppression(monkeypatch):
    from unittest.mock import Mock

    from langsmith import Client

    from deerflow.tracing.scoped import LangSmithResource, TracingSession

    client = Mock(spec=Client)
    monkeypatch.setattr("langsmith.Client", lambda **kwargs: client)
    monkeypatch.setenv("LANGSMITH_RUNS_ENDPOINTS", '{"https://wrong.example":"deployment-key"}')
    config = provider()
    config.provider = "langsmith"
    resource = LangSmithResource(config)
    with TracingSession(snapshot(mode="disabled")).activate():
        callback = resource.callback(snapshot())
        run_id = uuid4()
        run = callback.on_chain_start({}, {}, run_id=run_id, name="private-smith")
        callback.on_chain_end({}, run_id=run_id)
    assert run.extra.get("__disabled") is not True
    assert client.create_run.call_count == 1
    assert client.update_run.call_count == 1
    assert client.create_run.call_args.kwargs.get("api_url") != "https://wrong.example"


def test_background_context_survives_exporter_recreation(memory_routes):
    from deerflow.tracing.factory import build_tracing_callbacks
    from deerflow.tracing.scoped import capture_tracing_parent_context, tracing_scope

    frozen = snapshot()
    with tracing_scope(frozen):
        callback = build_tracing_callbacks()[0]
        root_id = uuid4()
        callback.on_chain_start({}, {}, run_id=root_id, name="parent-process")
        parent_contexts = capture_tracing_parent_context()
        callback.on_chain_end({}, run_id=root_id)
    parent_span = memory_routes[("alpha", "test-key")][0].get_finished_spans()[0]
    # No live provider/session remains: durable background work has only the
    # immutable snapshot and these non-secret transport contexts.
    with tracing_scope(frozen, parent_contexts=parent_contexts):
        callback = build_tracing_callbacks()[0]
        child_id = uuid4()
        callback.on_chain_start({}, {}, run_id=child_id, name="background-process")
        callback.on_chain_end({}, run_id=child_id)
    child_span = memory_routes[("alpha", "test-key")][1].get_finished_spans()[0]
    assert child_span.parent.span_id == parent_span.context.span_id
    assert child_span.context.trace_id == parent_span.context.trace_id


def test_disabled_scope_removes_ambient_provider_callbacks():
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.runnables.config import var_child_runnable_config

    from deerflow.tracing.scoped import tracing_scope

    observed = []

    class DeploymentExporter(BaseCallbackHandler):
        deerflow_scoped_tracing = True

        def on_chain_start(self, serialized, inputs, **kwargs):
            observed.append(inputs)

    token = var_child_runnable_config.set({"callbacks": [DeploymentExporter()]})
    try:
        with tracing_scope(snapshot(mode="disabled")):
            assert RunnableLambda(lambda value: value).invoke("private-input") == "private-input"
        assert observed == []
    finally:
        var_child_runnable_config.reset(token)


def test_private_langsmith_does_not_inherit_deployment_workspace(monkeypatch):
    from langsmith import Client

    from deerflow.tracing.scoped import LangSmithResource

    monkeypatch.setattr("langsmith.Client", lambda **kwargs: Client(auto_batch_tracing=False, info={}, **kwargs))
    monkeypatch.setenv("LANGSMITH_WORKSPACE_ID", "deployment-workspace")
    monkeypatch.setattr("langsmith.client._profiles.load_profile_client_config", lambda: SimpleNamespace())
    config = provider()
    config.provider = "langsmith"
    config.workspace_id = ""
    resource = LangSmithResource(config)
    try:
        assert resource.client.workspace_id is None
        assert "X-Tenant-Id" not in resource.client._headers
    finally:
        resource.close()
