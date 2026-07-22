"""Tests for DeerFlowClient's graph-root tracing wiring.

Regression coverage for the Copilot review on PR #2944: when the title
and summarization middlewares request ``attach_tracing=False`` we must
make sure ``DeerFlowClient`` injects the tracing callbacks at the graph
invocation root instead, otherwise those middlewares produce untraced
LLM calls.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from deerflow.client import DeerFlowClient
from deerflow.trace_context import DEERFLOW_TRACE_METADATA_KEY, request_trace_context


class _FakeAgent:
    """Capture the ``config`` handed to ``agent.stream``."""

    def __init__(self) -> None:
        self.captured_config: dict | None = None
        self.checkpointer = None
        self.store = None

    def stream(self, state, *, config, context, stream_mode):
        self.captured_config = config
        return iter(())  # empty stream


@pytest.fixture(autouse=True)
def _clear_langfuse_env(monkeypatch):
    from deerflow.config.tracing_config import reset_tracing_config

    for name in ("LANGFUSE_TRACING", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    reset_tracing_config()
    yield
    reset_tracing_config()


def _stub_agent_creation(monkeypatch, fake_agent: _FakeAgent) -> dict[str, Any]:
    """Short-circuit the heavy parts of ``_ensure_agent`` so we can drive
    ``stream()`` against a fake graph without touching real models, tools
    or middleware factories.
    """
    captured: dict[str, Any] = {}

    def _stub_ensure_agent(self, config):
        captured["config"] = config
        self._agent = fake_agent
        self._agent_config_key = ("stub",)

    monkeypatch.setattr(DeerFlowClient, "_ensure_agent", _stub_ensure_agent)
    return captured


def _make_client(_monkeypatch, *, enhance_enabled: bool = True) -> DeerFlowClient:
    """Build a client without going through ``__init__`` so we never load
    config.yaml or perform any other side-effectful startup work.

    ``enhance_enabled`` seeds the ``logging.enhance.enabled`` flag that
    :func:`DeerFlowClient.stream` consults to gate request-trace binding
    (mirrors the Gateway ``TraceMiddleware`` startup snapshot).
    """
    fake_app_config = SimpleNamespace(
        models=[SimpleNamespace(name="stub-model")],
        logging=SimpleNamespace(enhance=SimpleNamespace(enabled=enhance_enabled)),
    )
    client = DeerFlowClient.__new__(DeerFlowClient)
    client._app_config = fake_app_config
    client._checkpoint_channel_mode = "full"
    client._extensions_config = None
    client._model_name = "stub-model"
    client._thinking_enabled = False
    client._plan_mode = False
    client._subagent_enabled = False
    client._agent_name = None
    client._available_skills = None
    client._middlewares = None
    client._checkpointer = None
    client._agent = None
    client._agent_config_key = None
    client._environment = None
    return client


def test_stream_injects_langfuse_metadata_when_enabled(monkeypatch):
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    from deerflow.config.tracing_config import reset_tracing_config

    reset_tracing_config()

    class _SentinelHandler:
        pass

    sentinel = _SentinelHandler()
    monkeypatch.setattr("deerflow.client.build_tracing_callbacks", lambda: [sentinel])

    fake_agent = _FakeAgent()
    captured = _stub_agent_creation(monkeypatch, fake_agent)
    client = _make_client(monkeypatch)

    list(client.stream("hi", thread_id="thread-client-1"))

    config = captured["config"]
    metadata = config.get("metadata") or {}
    assert metadata.get("langfuse_session_id") == "thread-client-1"
    assert metadata.get("langfuse_trace_name") == "lead-agent"
    assert metadata.get(DEERFLOW_TRACE_METADATA_KEY)
    # Default no-auth context falls back to ``"default"`` user.
    assert metadata.get("langfuse_user_id") in {"default", "test-user-autouse"}
    callbacks = config.get("callbacks") or []
    assert sentinel in callbacks


def test_stream_is_inert_when_langfuse_disabled(monkeypatch):
    monkeypatch.setattr("deerflow.client.build_tracing_callbacks", lambda: [])

    fake_agent = _FakeAgent()
    captured = _stub_agent_creation(monkeypatch, fake_agent)
    client = _make_client(monkeypatch)

    list(client.stream("hi", thread_id="thread-client-2"))

    config = captured["config"]
    assert "callbacks" not in config or not config["callbacks"]
    metadata = config.get("metadata") or {}
    assert "langfuse_session_id" not in metadata
    assert "langfuse_user_id" not in metadata


def test_stream_preserves_caller_metadata_overrides(monkeypatch):
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    from deerflow.config.tracing_config import reset_tracing_config

    reset_tracing_config()
    monkeypatch.setattr("deerflow.client.build_tracing_callbacks", lambda: [])

    fake_agent = _FakeAgent()
    captured = _stub_agent_creation(monkeypatch, fake_agent)
    client = _make_client(monkeypatch)

    # Drive stream with a pre-populated metadata so the worker-equivalent
    # ``setdefault`` semantics are exercised.
    original_get_config = DeerFlowClient._get_runnable_config

    def patched_get_runnable_config(self, thread_id, **overrides):
        cfg = original_get_config(self, thread_id, **overrides)
        cfg["metadata"] = {
            DEERFLOW_TRACE_METADATA_KEY: "explicit-client-trace",
            "langfuse_session_id": "explicit-session-override",
            "langfuse_user_id": "explicit-user",
        }
        return cfg

    monkeypatch.setattr(DeerFlowClient, "_get_runnable_config", patched_get_runnable_config)
    with request_trace_context("client-trace-3"):
        list(client.stream("hi", thread_id="thread-client-3"))

    metadata = captured["config"].get("metadata") or {}
    assert metadata["langfuse_session_id"] == "explicit-session-override"
    assert metadata["langfuse_user_id"] == "explicit-user"
    assert metadata[DEERFLOW_TRACE_METADATA_KEY] == "explicit-client-trace"
    # ``trace_name`` was not supplied by caller so the worker still fills it.
    assert metadata["langfuse_trace_name"] == "lead-agent"


def test_stream_omits_deerflow_trace_id_when_enhance_disabled(monkeypatch):
    """With ``logging.enhance.enabled=false`` the embedded client must not
    forge a fresh request trace id. Otherwise embedded / TUI callers on the
    default config would silently gain a new indexed ``deerflow_trace_id``
    key on every Langfuse trace they emit — the exact schema change the
    enhancement flag exists to opt into.
    """
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    from deerflow.config.tracing_config import reset_tracing_config

    reset_tracing_config()
    monkeypatch.setattr("deerflow.client.build_tracing_callbacks", lambda: [])

    fake_agent = _FakeAgent()
    captured = _stub_agent_creation(monkeypatch, fake_agent)
    client = _make_client(monkeypatch, enhance_enabled=False)

    list(client.stream("hi", thread_id="thread-client-disabled"))

    metadata = captured["config"].get("metadata") or {}
    # Session / user still bind — those are Langfuse-native trace attributes
    # unrelated to the request-trace-correlation enhancement.
    assert metadata.get("langfuse_session_id") == "thread-client-disabled"
    assert metadata.get("langfuse_trace_name") == "lead-agent"
    # The gated key stays out of metadata.
    assert DEERFLOW_TRACE_METADATA_KEY not in metadata


def test_stream_respects_caller_bound_trace_when_enhance_disabled(monkeypatch):
    """Even with the enhancement disabled, a caller that explicitly binds
    :func:`request_trace_context` has opted into propagation. The embedded
    client must not swallow that id — the flag only gates *implicit*
    per-turn id creation, not caller-supplied context."""
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    from deerflow.config.tracing_config import reset_tracing_config

    reset_tracing_config()
    monkeypatch.setattr("deerflow.client.build_tracing_callbacks", lambda: [])

    fake_agent = _FakeAgent()
    captured = _stub_agent_creation(monkeypatch, fake_agent)
    client = _make_client(monkeypatch, enhance_enabled=False)

    with request_trace_context("caller-opt-in"):
        list(client.stream("hi", thread_id="thread-client-opt-in"))

    metadata = captured["config"].get("metadata") or {}
    assert metadata.get(DEERFLOW_TRACE_METADATA_KEY) == "caller-opt-in"


def test_stream_does_not_leak_trace_id_to_caller_context_between_yields(monkeypatch):
    """Enable branch must bind the trace id only around each ``next()`` step
    and reset it before yielding. ``stream()`` is a sync generator, which
    shares the caller's context, so a ``with ensure_trace_context(): yield
    from ...`` would leak the stream's id into the caller's context between
    iterations — any caller code that read ``get_current_trace_id()`` (a
    log filter, a follow-up ``inject_langfuse_metadata`` for unrelated
    work) would pick up this stream's id instead of the caller's own trace
    state. Per-step set/reset keeps the caller's context clean at every
    yield boundary.
    """
    monkeypatch.setattr("deerflow.client.build_tracing_callbacks", lambda: [])

    class _TwoEventAgent:
        def __init__(self) -> None:
            self.checkpointer = None
            self.store = None

        def stream(self, state, *, config, context, stream_mode):
            yield ("values", {"messages": [], "artifacts": []})
            yield ("values", {"messages": [], "artifacts": []})

    _stub_agent_creation(monkeypatch, _TwoEventAgent())
    client = _make_client(monkeypatch, enhance_enabled=True)

    from deerflow.trace_context import get_current_trace_id

    # Caller's context starts with no trace id bound.
    assert get_current_trace_id() is None

    observations: list[str | None] = []
    for _event in client.stream("hi", thread_id="thread-no-leak"):
        observations.append(get_current_trace_id())

    # Between every yield the caller sees their own (unbound) trace state,
    # never the stream's minted id.
    assert observations, "expected at least one event"
    assert all(obs is None for obs in observations), observations
    # After iteration completes, still no leak.
    assert get_current_trace_id() is None


def test_stream_abandoned_generator_close_does_not_raise_cross_context(monkeypatch):
    """Closing a partially-iterated stream from a different ``Context`` must
    not raise ``ValueError: <Token> was created in a different Context``.
    Sync generators share the caller's context on set/reset; a ``with``
    block spanning ``yield from`` would create a Token in the caller's
    Context on the first ``next()`` and only release it via ``__exit__`` on
    ``close()`` — GC-driven finalization on a different asyncio Task (or,
    as simulated here, inside a ``copy_context()`` fork) would then blow up
    with a cross-context reset. Per-step set/reset never leaves a Token
    outstanding across yield boundaries.
    """
    monkeypatch.setattr("deerflow.client.build_tracing_callbacks", lambda: [])

    class _InfiniteAgent:
        def __init__(self) -> None:
            self.checkpointer = None
            self.store = None

        def stream(self, state, *, config, context, stream_mode):
            while True:
                yield ("values", {"messages": [], "artifacts": []})

    _stub_agent_creation(monkeypatch, _InfiniteAgent())
    client = _make_client(monkeypatch, enhance_enabled=True)

    gen = client.stream("hi", thread_id="thread-cross-ctx")
    # Pull one event in the current Context — a buggy implementation would
    # bind a Token here that only this Context could reset.
    next(gen)

    import contextvars

    isolated_ctx = contextvars.copy_context()
    # Invoke ``gen.close()`` inside a distinct Context; the outer Context's
    # Tokens (if any) cannot be reset from here. Reaching this line without
    # a ``ValueError`` is the assertion.
    isolated_ctx.run(gen.close)
